# Changelog

## 2.0 — In development

### Added

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

### Changed

- Native reader state is no longer primarily stored in UserDefaults or WebKit
  localStorage.
- The Mac app is no longer required to remain beside the repository after it has
  been built, although Python 3 remains required for the local service.
- The local protocol reports version and library identity.
- EPUB archive limits and content serving are stricter.

### Security

- Native path validation now resolves symlinks and matches the selected library
  boundary.
- The app refuses to attach to a service for another library folder.
- EPUB resource count, expansion size, and compression-ratio limits reduce
  archive-bomb risk.
