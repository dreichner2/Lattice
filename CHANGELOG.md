# Changelog

## 2.0.1 — 2026-08-21

### Fixed

- Dropping a file onto the main Lattice window now begins the import
  immediately with the selected material type instead of silently waiting for
  a second Add click.
- A queued file no longer displays a spinning activity indicator before any
  upload or Luna metadata work has started.
- Luna metadata enrichment now uses the supported Structured Outputs schema
  subset; uniqueness is still enforced by Lattice before metadata is saved.
- The zero-argument Windows onboarding launcher now resolves the cloned
  library root correctly under Windows PowerShell 5.1.

## 2.0.0 — 2026-08-21

### Added

- Lattice display identity and “A shared knowledge library” descriptor across
  the macOS, Windows, browser, and
  Syncthing experiences while preserving established storage and protocol IDs.
- Versioned cross-subject taxonomy covering computing, engineering,
  mathematics, statistics and data science, physics, interdisciplinary work,
  and safe fallback classification.
- Dedicated Add and drag-and-drop import with collision-safe payload writes and
  adjacent Syncthing-shared `.library.json` metadata sidecars.
- Optional `gpt-5.6-luna` metadata suggestions through the authenticated local
  Codex CLI, with metadata-only inputs, structured validation, and a fully local
  fallback when Codex is unavailable.
- Versioned SQLite reader database with migrations, backups, integrity checks,
  JSON import/export, Markdown export, and stable document IDs.
- Formal WKWebView/native bridge for reader state and commands.
- Unified notebook and full-library search workspace.
- Native PDF highlights, notes, bookmarks, page labels, thumbnails,
  continuous/page/spread modes, fit-page controls, search, and elapsed sessions.
- EPUB chapter indexing, durable quotations and notes, chapter/page progress,
  resize-safe pagination, and elapsed sessions.
- Portable library-folder selection and collision-safe PDF/EPUB/TXT import.
- Exact local-server instance verification and parent-process shutdown.
- Bundled UI/service resources and atomic application replacement.
- Expanded macOS, Python, JavaScript, storage, and protocol tests.
- A polished Windows-native frame around the shared Lattice shelf and a
  verified clone-to-app onboarding path for the Syncthing hub.

### Changed

- The Syncthing display label is now Lattice; the established folder ID
  remains `cs-library-3b8290f24f15` so paired devices do not need migration.
- The original computer-science catalog is now one subject collection inside a
  subject-agnostic library rather than the application-wide identity.
- Native reader state is no longer primarily stored in UserDefaults or WebKit
  localStorage.
- The Mac app is no longer required to remain beside the repository after it has
  been built, although Python 3 remains required for the local service.
- The local protocol reports version and library identity.
- EPUB archive limits and content serving are stricter.

### Security

- Import-generated integrity, path, and access fields remain server-owned;
  Codex and manual edits may change only descriptive metadata.
- Codex enrichment receives filenames and extracted publication metadata, not
  document bytes or full text, and cannot prevent a local import from finishing.
- Codex executable discovery rejects relative, current-directory,
  library-owned, and symlinked-into-library command paths.
- Native path validation now resolves symlinks and matches the selected library
  boundary, including imported lecture PDF, EPUB, and TXT files.
- The app refuses to attach to a service for another library folder.
- EPUB resource count, expansion size, and compression-ratio limits reduce
  archive-bomb risk.
- Windows update manifests are production-key signed; candidate servers are
  isolated, full interface readiness is required, activation is monotonic
  across concurrent candidates, and installer authority is published before
  shortcut replacement.
