# Importing Material and Metadata Sidecars

Lattice accepts local PDF, EPUB, and TXT reading material through the
dedicated **Add** button or by dragging files onto the library window. The same
workflow is available in the shared browser UI, macOS app, and Windows app.

## What happens during import

1. Choose `books`, `papers`, or `lectures` as the destination kind.
2. Lattice validates the request, filename, supported format, size, and
   library boundary.
3. The local server streams the payload to a Syncthing-reserved temporary
   filename, calculates its SHA-256, chooses a collision-safe destination, and
   atomically installs it. Partial uploads are never synchronization candidates.
4. The server writes a metadata sidecar beside the payload.
5. The library refreshes immediately; Syncthing then carries both files to the
   other paired computers.

No content directory or metadata file needs to be created by hand. For a file
named `example.pdf`, the exact pair is:

```text
books/example.pdf
books/example.pdf.library.json
```

The suffix is appended to the full payload filename. Consequently,
`example.pdf` and `example.epub` have distinct sidecars.

## Sidecar schema version 1

Every generated sidecar is a JSON object with these stable top-level keys:

| Key | Shape | Ownership |
|---|---|---|
| `schema_version` | integer | Server-owned; currently `1`. |
| `work_id` | string | Server-owned stable imported-work identity. |
| `path` | string | Server-owned repository-relative payload path. |
| `title` | string | Editable descriptive metadata. |
| `authors` | string array | Editable descriptive metadata. |
| `year` | integer or `null` | Editable descriptive metadata. |
| `edition` | string | Editable descriptive metadata. |
| `subject_id` | string | Editable only to an ID in `library-taxonomy.json`. |
| `topics` | string array | Editable descriptive metadata. |
| `material_type` | string | Server-owned destination/material classification. |
| `bytes` | integer | Server-owned size of the installed payload. |
| `sha256` | string | Server-owned lowercase SHA-256 of the payload. |
| `access` | string | Server-owned conservative access default. |
| `metadata_status` | string | Server-owned enrichment/completeness state. |
| `added_at` | string | Server-owned import timestamp. |
| `import` | object | Server-owned `method` and `originalFilename`. |
| `embedded_metadata` | object | Publication metadata extracted locally. |
| `ai` | object | Enrichment status described below. |

The `ai` object always contains `status`, `model`, and `inputPolicy`. A finished
attempt may add `completedAt`; a failed or unavailable attempt may add `error`.
These fields are diagnostic metadata, not proof that the suggested description
is correct.

Never hand-edit `path`, `bytes`, `sha256`, `access`, `work_id`,
`material_type`, timestamps, or import provenance. Lattice recalculates and
protects integrity fields; Codex and manual edits are limited to title, authors,
year, edition, subject, and topics.

## Optional Codex enrichment

If the local Codex CLI is installed and authenticated, Lattice can invoke
`gpt-5.6-luna` to suggest title, authors, year, edition, subject, and topics.
Each computer uses its own existing Codex sign-in. Lattice
does not read, copy, display, or synchronize `auth.json`, API keys, or other
credential material.

The model input policy is metadata-only: it includes the filename, selected
material kind, publication metadata extracted locally from the container, and
the allowed subject list. Document bytes and full text are not included. Output
must match the expected structured schema, and `subject_id` must exist in
`library-taxonomy.json` before a suggestion is accepted.

PDF imports use the filename only because arbitrary PDF byte searches can
mistake page content for metadata. EPUB imports may include bounded title,
creator, and language fields from the package metadata. All values are treated
as untrusted strings, and the ephemeral Codex run disables local execution,
browser, app, image, and workspace tools before sending the request.

Codex is optional. If the executable is missing, the user is signed out, the
model is unavailable, a timeout occurs, or output is invalid, import still
finishes. Lattice derives a readable title locally, uses conservative unknown
values where needed, and applies the taxonomy's `default_import_subject_id`
(`other`). The result can be edited later.

## Subject classification

Subjects are broad disciplines; topics are narrower tags. The checked-in
taxonomy currently defines:

- Computer Science
- Electrical Engineering
- Computer Engineering
- Mathematics
- Statistics & Data Science
- Physics
- Mechanical Engineering
- Civil Engineering
- Chemical Engineering
- General Engineering
- Interdisciplinary
- Other

The original catalog defaults to Computer Science, with a Mathematics default
for its mathematics shelf and selected work overrides such as RISC-V under
Computer Engineering and MacKay's information-theory text under Electrical
Engineering.

## Sync and conflict expectations

Sidecars are private library data. Git ignores them, while the repository-root
`.stignore` includes them because they sit inside `books/`, `papers/`, or
`lectures/`. The same rules exclude partial uploads, Git placeholders, and the
curated lecture catalog. Wait for Syncthing to report **Up to Date** before
editing the same item on the other computer. If Syncthing creates a conflict
copy, keep the payload whose hash is authoritative and review the descriptive
sidecar fields before removing either copy.
