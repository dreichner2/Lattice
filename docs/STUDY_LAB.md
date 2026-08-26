# Study Workspace

Study Workspace is Lattice's local notebook environment for turning reading
into usable understanding. A notebook contains explicit cells of three kinds:

- `markdown` for prose, headings, lists, quotations, links, fenced code, and
  inline or display math;
- `latex` for a focused, display-math canvas; and
- `python` for trusted, executable local experiments.

Markdown is the default. Lattice never guesses a cell's kind and never splits
mixed content automatically: the reader chooses the appropriate canvas for the
next idea.

## Workspace experience

The standalone workspace is a responsive, keyboard-accessible page with a
searchable and collapsible notebook rail. Empty libraries offer practical
Reading notes, Worked problem, and Python experiment starters. Empty notebooks
offer the same choices without adding placeholder content to the user's notes.

Save state is always visible as **Saving**, **Saved locally**, **Could not
save**, or **Needs review**. The browser serializes autosaves and flushes them
before any action that changes notebook structure. A stale revision remains a
visible conflict; it is never silently overwritten.

Useful shortcuts:

| Shortcut | Action |
|---|---|
| Command/Control-S | Flush pending saves |
| Command/Control-Enter | Preview Markdown/LaTeX or run Python |
| Command/Control-Option-M | Add a Markdown note |
| Command/Control-Option-L | Add a LaTeX cell |
| Command/Control-Option-P | Add a Python cell |
| Command/Control-Shift-N | Create a notebook |
| Command/Control-Backslash | Toggle the notebook rail |
| `/` | Focus notebook search when not editing |
| Escape | Leave cell edit mode |

Markdown is rendered into DOM nodes rather than injected as authored HTML.
External Markdown links are limited to HTTP(S) and open with
`noopener noreferrer`. Inline and display math use the vendored KaTeX renderer
with `trust: false`.

## Embedded reader mode

PDF and EPUB readers can embed `/study-lab.html` in a same-origin iframe. The
child detects that it is framed, switches to a compact surface, and hides its
standalone navigation. `mode: "notes"` further reduces the surface to
Markdown note-taking; `mode: "lab"` keeps Markdown, math, and Python available.
The standalone page remains fully useful without a parent.

The reader and workspace use this versioned `postMessage` protocol:

1. The child sends `{type: "lattice-study-ready", version: 1}` to
   `location.origin`.
2. The parent replies with:

   ```js
   {
     type: "lattice-study-context",
     version: 1,
     context: {
       workPath: "catalog/exact-path.pdf",
       workTitle: "Displayed title",
       mode: "notes", // or "lab"
       compact: true
     }
   }
   ```

3. The child accepts context only when `event.origin === location.origin`,
   `event.source === window.parent`, and both the message type and version
   match. It also confirms that `workPath` is an exact current-catalog path.
4. It selects an existing notebook linked to that path, or creates and links a
   Markdown-first notebook when none exists.
5. The child publishes save confidence with
   `{type: "lattice-study-status", version: 1, dirty, saved, notebookId?}`.

No work path, title, action token, or private Study capability is put in the
iframe URL. The private per-launch capability remains in same-origin
`sessionStorage` and is carried only in the `X-Lattice-Private-Token` header.

## Storage

Notebooks live in `Study.sqlite` under the user's private application area,
keyed by a SHA-256 namespace of the stable Syncthing folder identity when one
is available (with a canonical-path identity as the local fallback):

- Windows: `%LOCALAPPDATA%\Lattice\Study\<identity-sha256>\`
- macOS: `~/Library/Application Support/Lattice/Study/<identity-sha256>/`
- Linux: `$XDG_STATE_HOME/lattice/study/<identity-sha256>/`

This database is **device-local by design**—like reader state and the Tutor
cache, it never lives inside the synchronized library folder, so a live SQLite
file is never synced or merged. Set `LATTICE_STUDY_ROOT` to relocate the private
base in tests; Lattice still appends the identity namespace. Storage inside the
library is rejected, as are symbolic-link or Windows-reparse database roots and
files. On POSIX systems, the namespace is mode `0700` and the database is mode
`0600`. SQLite uses WAL, full synchronous commits, foreign keys, and a bounded
busy timeout.

## Schema (version 2)

- `notebooks(id, title, created_at, updated_at)`
- `cells(id, notebook_id -> notebooks ON DELETE CASCADE, position, kind CHECK
  IN ('markdown','latex','python'), source, created_at, updated_at)`
- `notebook_links(notebook_id PK/FK, work_path, work_title)` links a notebook to
  a catalog payload path.

Opening a version-1 database performs a transactionally guarded migration. It
rebuilds only the `cells` table to widen its kind constraint, preserves all
existing LaTeX/Python cells and notebook links, and advances the schema marker
only after the copy succeeds.

## Concurrency

Every mutation of an existing notebook carries the caller's base revision
(`baseUpdatedAt`, the notebook's prior `updated_at`) and successful non-delete
responses return the fresh token (`notebookUpdatedAt`). A missing or stale base
is rejected with HTTP 409 so two open editors cannot silently clobber each
other. Revision tokens increase strictly even when the wall clock does not.

## HTTP surface

Every endpoint requires the private Study capability; mutations also require
the library action token.

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/study/status` | availability and supported cell kinds |
| GET | `/api/study/notebooks` | list notebooks |
| POST | `/api/study/notebooks` | create notebook |
| GET | `/api/study/notebook/{id}` | notebook and cells |
| POST | `/api/study/notebook/{id}` | rename |
| POST | `/api/study/notebook/{id}/delete` | delete notebook and cells |
| POST | `/api/study/notebook/{id}/link` | set or clear exact work link |
| POST | `/api/study/notebook/{id}/cells` | add cell (`kind`, `source`) |
| POST | `/api/study/cell/update` | save cell source |
| POST | `/api/study/cell/move` | move cell up or down |
| POST | `/api/study/cell/delete` | delete cell |
| GET | `/api/study/kernel/status` | local CPython kernel status |
| POST | `/api/study/kernel/run` | run source in persistent notebook kernel |
| POST | `/api/study/kernel/restart` | stop kernel and clear its state |

Work links must match an exact path in the current catalog; the server derives
the displayed title rather than trusting client text. Limits: titles at most
200 characters, work paths at most 1,024 characters, cell sources at most
100,000 characters, and at most 500 cells per notebook. Python source remains
inert until the user explicitly runs its cell.

## Python execution

Each notebook gets a persistent CPython bridge process on first use, so names
survive across cell runs until the kernel is restarted, evicted while idle, or
the app closes. Python writes to `sys.stdout` and `sys.stderr`, trailing
expression values, exceptions, and bounded matplotlib PNG figures (when
matplotlib is available) are returned as structured outputs. Low-level writes
made directly to native standard-I/O file descriptors, including output
inherited by child processes, are discarded so they cannot corrupt the kernel
control channel. A cell may run for at most 120 seconds, and at most eight
notebook kernels are retained at once. Common built-in expression values keep
their bounded representation. Custom objects are shown with a type marker
instead of invoking a potentially unbounded `__repr__` method.

Timeout, restart, deletion, idle eviction, and app shutdown stop the kernel's
managed process tree and discard any result from the retired kernel generation.
Windows uses a kill-on-close Job Object; macOS and Linux use a dedicated process
group. The packaged Windows service uses a directory bundle so the
interpreter-hosting bridge is assigned to that Job before notebook code can
start. This is lifecycle cleanup, not a security sandbox; deliberately hostile
trusted code can still evade cleanup on POSIX by creating a new session.

Python execution has the same filesystem, network, and process permissions as
the user running Lattice, just like a script started from a terminal. Only run
code you trust. The child kernel does not inherit the private Study capability.
