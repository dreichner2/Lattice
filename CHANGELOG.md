# Changelog

## 2.2.0 — 2026-08-22

### Added

- EPUB-style focus mode in the shared PDF reader on macOS, Windows, and the
  browser. The PDF page keeps its reading position while the header, controls,
  status bar, and navigation drawer recede; press `F` to toggle or `Escape` to
  restore the controls.
- Native **Move Library** commands on Windows and macOS relocate the complete
  library to external storage, preserve the `.stfolder` marker and stable
  Syncthing folder ID, verify every copied file, roll back failed redirects, and
  remove the original only after a healthy post-move scan.
- An inline three-dot menu beside the macOS library header controls shows the
  installed version and provides both update checking and external-storage relocation.
- The Windows app removes its duplicate 58-pixel navigation/command strip and
  uses the compact system caption plus the shared in-app Add and three-dot controls.

### Fixed

- A newly activated Windows version can check for another update immediately;
  reopening the window is no longer required.
- The activated Windows update label now reads `Version <ID>` and remains an
  enabled update-check command.

## 2.1.1 — 2026-08-22

### Fixed

- Left and right arrow keys now move between PDF pages in the ordinary
  windowed reader, including continuous layout and the macOS native key bridge.
- Returning to the Shelf from PDF fullscreen now exits the browser and native
  fullscreen surfaces before removing the reader frame, preventing the black,
  unclickable window left behind by WebKit.
- The packaged Windows smoke test now proves windowed arrow navigation in
  addition to rendering, two-page layout, and Shelf return.

## 2.1.0 — 2026-08-22

### Added

- A bundled shared Lattice PDF reader for macOS, Windows, and the browser,
  built on PDF.js 6.2.108 with fast range loading instead of waiting for an
  entire large document before showing the first page.
- Continuous, single-page, and two-page spread layouts; search, thumbnails,
  outlines, fit and zoom controls, rotation, keyboard navigation, and true
  fullscreen integration with the Windows-native frame.
- Per-document page, layout, zoom, and rotation restoration, plus a Shelf
  control that returns to the existing collection without losing shelf state.
- macOS now opens PDFs in that same shared Lattice reader instead of silently
  routing them into the separate PDFKit workspace.

### Fixed

- A successfully activated Windows update now closes the exact superseded
  Lattice window automatically instead of leaving it stuck on “Verifying.”
- Update handoffs bind new launchers to their process ID and executable path;
  the first fixed release also safely handles legacy 2.0.1 activation records.
- The packaged Windows smoke test now opens and renders a real two-page PDF,
  captures visual proof, returns to the shelf, and verifies that the reader
  frame is fully closed.

## 2.0.1 — 2026-08-21

### Fixed

- Dropping a file onto the main Lattice window now begins the import
  immediately with the selected material type instead of silently waiting for
  a second Add click.
- A queued file no longer displays a spinning activity indicator before any
  upload or Luna metadata work has started.
- Luna metadata enrichment now uses the supported Structured Outputs schema
  subset; uniqueness is still enforced by Lattice before metadata is saved.
- XHTML chapters that contain Kobo-style self-closing script markers now render
  normally instead of appearing as blank pages; embedded scripts remain blocked.
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
