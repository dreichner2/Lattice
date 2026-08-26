# Study Lab

Study Lab is Lattice's notebook workspace: classic Jupyter-style notebooks
with **explicit cell kinds only — `latex` and `python`**. There are no prose
cells and no automatic content detection; the user chooses the kind when
adding a cell. (The auto-segmenting "unified cell" model from Lunaris was
evaluated and intentionally rejected.)

## Storage

Notebooks live in `Study.sqlite` under the user's private application area,
keyed by a SHA-256 namespace of the stable Syncthing folder identity when one
is available (with a canonical-path identity as the local fallback):

- Windows: `%LOCALAPPDATA%\Lattice\Study\<identity-sha256>\`
- macOS: `~/Library/Application Support/Lattice/Study/<identity-sha256>/`
- Linux: `$XDG_STATE_HOME/lattice/study/<identity-sha256>/`

This database is **device-local by design** — like reader state and the Tutor
cache, it never lives inside the synchronized library folder, so a live SQLite
file is never synced or merged. Set `LATTICE_STUDY_ROOT` to relocate the private
base in tests; Lattice still appends the identity namespace. Storage inside the
library is rejected, as are symbolic-link or Windows-reparse database roots and
files. On POSIX systems, the namespace is mode `0700` and the database is mode
`0600`. SQLite uses WAL, full synchronous commits, foreign keys, and a bounded
busy timeout.

## Schema (version 1)

- `notebooks(id, title, created_at, updated_at)`
- `cells(id, notebook_id → notebooks ON DELETE CASCADE, position, kind CHECK IN ('latex','python'), source, created_at, updated_at)`
- `notebook_links(notebook_id PK/FK, work_path, work_title)` — links a
  notebook to a catalog payload path.

## Concurrency

Every mutation of an existing notebook carries the caller's base revision
(`baseUpdatedAt`, the notebook's prior `updated_at`) and successful non-delete
responses return the fresh token (`notebookUpdatedAt`). A missing or stale base
is rejected with HTTP 409 so two open editors cannot silently clobber each
other. Revision tokens increase strictly even when the wall clock does not.
The browser serializes autosaves and flushes them before other notebook actions.

## HTTP surface (token-guarded like other mutations)

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/study/status` | availability + cell kinds |
| GET | `/api/study/notebooks` | list notebooks |
| POST | `/api/study/notebooks` | create notebook |
| GET | `/api/study/notebook/{id}` | notebook + cells |
| POST | `/api/study/notebook/{id}` | rename |
| POST | `/api/study/notebook/{id}/delete` | delete notebook and its cells |
| POST | `/api/study/notebook/{id}/link` | set/clear work link |
| POST | `/api/study/notebook/{id}/cells` | add cell (`kind`, `source`) |
| POST | `/api/study/cell/update` | save cell source |
| POST | `/api/study/cell/move` | move up/down |
| POST | `/api/study/cell/delete` | delete cell |
| GET | `/api/study/kernel/status` | local CPython kernel status |
| POST | `/api/study/kernel/run` | run source in the notebook's persistent kernel |
| POST | `/api/study/kernel/restart` | stop the notebook kernel and clear its state |

Work links must match an exact path in the current catalog; the server derives
the displayed title rather than trusting client text. Limits: titles ≤ 200
chars, work paths ≤ 1 024 chars, cell sources ≤ 100 000 chars, and ≤ 500 cells
per notebook. LaTeX renders locally through the vendored KaTeX under
`ui/vendor/katex/` (same offline-first policy as pdf.js). Python source is
stored and rendered as inert code until the user explicitly presses **Run**.

## Python execution

Each notebook gets a persistent CPython bridge process on first use, so names
survive across cell runs until the kernel is restarted, evicted while idle, or
the app closes. Python writes to `sys.stdout` and `sys.stderr`, trailing
expression values, exceptions, and bounded matplotlib PNG figures (when
matplotlib is available in the selected Python runtime) are returned as
structured outputs. Low-level writes made directly to native standard-I/O file
descriptors, including output inherited by child processes, are discarded so
they cannot corrupt the kernel control channel. A cell may run for at most 120
seconds, and at most eight notebook kernels are retained at once.
Common built-in expression values keep their bounded representation. Custom
objects are shown with a type marker instead of invoking an arbitrary
potentially unbounded `__repr__` method.

Timeout, restart, deletion, idle eviction, and app shutdown stop the kernel's
managed process tree and discard any result from the retired kernel generation.
Windows uses a kill-on-close Job Object; macOS and Linux use a dedicated process
group. The packaged Windows service uses a directory bundle so the
interpreter-hosting bridge is assigned to that Job before notebook code can
start. This is lifecycle cleanup rather than a security sandbox, so deliberately
hostile trusted code can still evade cleanup on POSIX by creating a new session.

Python execution is trusted local execution, not a sandbox. A cell has the same
filesystem, network, and process permissions as the user running Lattice, just
like a script started from a terminal. Only run code you trust. Every kernel
endpoint requires the private per-launch Study capability, mutations also
require the action token, and the child kernel does not inherit the private
Study capability.
