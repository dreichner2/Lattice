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

Work links must match an exact path in the current catalog; the server derives
the displayed title rather than trusting client text. Limits: titles ≤ 200
chars, work paths ≤ 1 024 chars, cell sources ≤ 100 000 chars, and ≤ 500 cells
per notebook. LaTeX renders locally through the vendored KaTeX under
`ui/vendor/katex/` (same offline-first policy as pdf.js). Python cells are
stored and rendered as inert code; this release does not execute them.
