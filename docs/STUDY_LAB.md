# Study Lab

Study Lab is Lattice's notebook workspace: classic Jupyter-style notebooks
with **explicit cell kinds only — `latex` and `python`**. There are no prose
cells and no automatic content detection; the user chooses the kind when
adding a cell. (The auto-segmenting "unified cell" model from Lunaris was
evaluated and intentionally rejected.)

## Storage

Notebooks live in `Study.sqlite` under the user's private application area,
keyed by library identity:

- Windows: `%LOCALAPPDATA%\Lattice\Study\<library-id>\`
- macOS: `~/Library/Application Support/Lattice/Study/<library-id>/`
- Linux: `$XDG_STATE_HOME/lattice/study/<library-id>/`

This database is **device-local by design** — like reader state and the Tutor
cache, it never lives inside the synchronized library folder, so a live SQLite
file is never synced or merged. Set `LATTICE_STUDY_ROOT` to relocate the root
in tests.

## Schema (version 1)

- `notebooks(id, title, created_at, updated_at)`
- `cells(id, notebook_id → notebooks ON DELETE CASCADE, position, kind CHECK IN ('latex','python'), source, created_at, updated_at)`
- `notebook_links(notebook_id PK/FK, work_path, work_title)` — links a
  notebook to a catalog payload path.

## Concurrency

Every mutation carries the caller's base revision (`baseUpdatedAt`, the
notebook's prior `updated_at`) and every response returns the fresh token
(`notebookUpdatedAt`). A stale base is rejected with HTTP 409 so two open
editors cannot silently clobber each other. Cell appends are non-destructive
and skip the check; destructive operations (rename, delete, update, move) and
the UI always send it. Omitting the base opts out explicitly for programmatic
edits.

## HTTP surface (token-guarded like other mutations)

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/study/status` | availability + cell kinds |
| GET | `/api/study/notebooks` | list notebooks |
| POST | `/api/study/notebooks` | create notebook |
| GET | `/api/study/notebook/{id}` | notebook + cells |
| POST | `/api/study/notebook/{id}` | rename |
| POST | `/api/study/notebook/{id}/link` | set/clear work link |
| POST | `/api/study/notebook/{id}/cells` | add cell (`kind`, `source`) |
| POST | `/api/study/cell/update` | save cell source |
| POST | `/api/study/cell/move` | move up/down |
| POST | `/api/study/cell/delete` | delete cell |

Limits: titles ≤ 200 chars, cell sources ≤ 100 000 chars, ≤ 500 cells per
notebook. LaTeX renders locally through the vendored KaTeX under
`ui/vendor/katex/` (same offline-first policy as pdf.js). Python cells render
as inert code; execution arrives with the separate runtime PR and will be a
trusted local kernel, not a sandbox.
