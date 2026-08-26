# Changelog

## Unreleased

### Fixed

- Windows Tutor now uses Codex's standard read-only sandbox for its disposable
  excerpt workspace instead of a custom split-read filesystem permission map,
  which the unelevated Windows restricted-token sandbox refuses to enforce.
  Tutor turns therefore reach the model instead of exiting during sandbox
  initialization.

### Security

- Windows Tutor disables shell, unified-exec, and code-mode access for the
  Codex child. Only the bounded prompt and response schema are present in the
  temporary workspace; the original library and private Tutor index remain
  outside the turn.

## 2.3.2 — 2026-08-23

### Fixed

- Windows Tutor no longer asks Codex to enforce separate read grants for every
  selected library file. Lattice now resolves and extracts the chosen material
  itself, stages only the bounded turn context in one disposable read-only
  workspace, and keeps the original library outside Codex's filesystem scope.
  This also avoids direct sandbox grants to books stored on an external SSD or
  another drive letter.
- The supported single-workspace profile retains the `codex.cmd` quoting fix
  from 2.3.1. Codex launch failures continue to report the real exit code and
  preserve bounded stderr; they are not presented as corrupt Tutor sessions or
  repaired by clearing a conversation.

### Security

- The Windows Codex child receives one isolated per-turn Lattice content root
  under the system temporary directory. It receives no grant to the original
  library root, selected source paths, unrelated volumes, or the private Tutor
  index.

## 2.3.1 — 2026-08-23

### Fixed

- Windows Tutor now launches `codex.cmd` through one explicit `cmd.exe`
  quoting boundary, preserving the quoted TOML filesystem-permission values
  that Codex requires even when paths contain spaces, command metacharacters,
  or trailing backslashes.
- Tutor now preserves the latest bounded Codex stderr output in its private
  per-device cache and reports the Codex exit code plus diagnostic-log path,
  instead of hiding the underlying failure behind a generic sign-in or model
  access message.

## 2.3.0 — 2026-08-23

### Added

- Added a compact reader Tutor peek that stays scoped to the open book, keeps
  the page visible and interactive, and expands to the full Tutor only when
  requested. The session can collapse again without closing, and PDFs expose it
  through a quiet bottom-right button because their immersive reader
  intentionally hides the host toolbar.
- Added an optional, library-first Lattice Tutor drawer using the same local
  Codex/ChatGPT sign-in as import enrichment. Users can choose Luna, Terra, or
  Sol; select Light through Max reasoning; and ground a conversation in either
  all eligible works or only selected books, papers, notes, and video courses.
- Added clickable, server-validated citations back to local files, PDF pages,
  library documents, and video-course catalog entries. Video grounding is
  explicitly metadata-only.
- Added incremental local extraction and private full-text indexing for PDF,
  EPUB, text, and supported source archives, including a vendored BSD-licensed
  `pypdf` parser for consistent desktop packaging.

### Changed

- The in-reader Tutor launcher is now the small star symbol only; it no longer
  reveals a partial “Tutor” label on hover.
- Successful macOS updates delete their transient recovery bundle immediately
  after candidate health is proven. Failed candidates are discarded after the
  prior app is restored, so updates do not retain application rollback copies.
- The macOS launcher prevents bundled Python services from writing bytecode
  caches into the app, preserving its code-signing seal after launch.
- Video-course Tutor now opens as the same compact, reversible companion used
  while reading, with a quiet symbol-only launcher that leaves the lecture visible.

### Fixed

- Embedded lecture players now receive explicit fullscreen permission and no
  longer sit beneath a transformed parent layer that could render video black
  during WebKit fullscreen transitions.

### Security

- Tutor Codex turns are ephemeral, ignore user config/rules, sanitize the child
  environment, disable external tools and model-tool network access, and receive
  exact-file read grants only for the resolved active source scope.
- Human-study-only and personalized/private works are excluded and pruned from
  the Tutor index. Chat/cancel/reset endpoints require the loopback action token,
  conversations remain bounded in memory, and citations are validated against
  the active scope before display.

## 2.2.9 — 2026-08-22

### Fixed

- A real Windows SSD test of 2.2.8 still returned
  `PNP_VetoOutstandingOpen` on all three attempts. The main process had exited,
  but the detached helper had not been given the identities of the existing
  WebView2 subprocesses and could ask Configuration Manager to eject before
  that full process set finished closing.
- Before disposal, Lattice now snapshots every process reported by its WebView2
  environment plus the browser process. The detached helper binds each wait to
  both PID and start time, and does not call Configuration Manager until the
  main app and every captured WebView process have exited.
- After the exact process set closes, the helper allows a two-second handle
  drain and retries only pending-close or outstanding-open vetoes up to eight
  times at 1.5-second intervals. Other veto types still stop immediately.
- Every eject attempt now writes a local diagnostic to
  `%LOCALAPPDATA%\CS Library\last-eject-diagnostic.txt`, including process-wait
  completion, timing, Configuration Manager result, veto type, and veto name.
  **Safe to unplug** still requires `CR_SUCCESS`.

## 2.2.8 — 2026-08-22

### Fixed

- Windows safe eject now runs in a detached local helper only after the main
  Lattice process has fully exited, eliminating the app-owned handle race that
  produced `PNP_VetoOutstandingOpen` on the external library volume.
- The eject helper visibly remains in **Ejecting…**, verifies that the saved USB
  device identity has not changed, and retries briefly only when Configuration
  Manager reports a pending close or outstanding open.
- **Safe to unplug** still appears only after native Configuration Manager
  success. A final failure preserves the disconnected library state and shows
  the exact Windows veto type, name, and result.
- After a healthy Windows update, an exact `Lattice.exe` copy on the desktop is
  replaced atomically with the verified new executable after the superseded
  process exits. The launcher remains in the same location and redirects to the
  healthy versioned installation on later opens.

## 2.2.7 — 2026-08-22

### Added

- **Disconnect library drive** on Windows now resolves the external disk's
  parent USB device and awaits the native Configuration Manager eject request.
  The app shows **Ejecting…** during the request and **Safe to unplug** only
  after Windows returns success.
- Native eject failures now show the exact Windows veto type, veto name, and
  Configuration Manager result while leaving the library disconnected.
- Reconnecting an ejected library resolves its saved volume identity even if
  Windows assigns a different drive letter, restores the same Syncthing folder
  path, rescans it, and waits for Up to Date before reporting success.

### Fixed

- Windows ejection uses no manual volume lock, dismount, offline, or mount-point
  operations, avoiding the remount race observed with the same SSD.
- Disconnect verifies that an already-paused Syncthing folder has no pending
  items or errors before stopping the dedicated process.
- Reconnect now rescans and verifies an already-unpaused folder instead of
  treating process availability alone as synchronization success.

## 2.2.6 — 2026-08-22

### Fixed

- **Reconnect library sync** now detects when Syncthing is running but the
  stable Lattice folder is still paused, and offers to resume that exact folder
  on both Windows and macOS.
- Lattice preserves a pre-existing pause until the user explicitly chooses
  **Resume Sync**, then scans the library and waits for a healthy Syncthing
  state before reporting that synchronization is connected.
- Reconnect status no longer calls a paused library connected or synchronized.

## 2.2.5 — 2026-08-22

### Fixed

- **Disconnect library drive** on Windows now shuts down the dedicated Lattice
  Syncthing instance and verifies that both its loopback API and process have
  stopped before claiming the external drive is ready to eject. Pausing the
  folder alone did not reliably release Syncthing's Windows volume handle.
- **Reconnect library sync** continues to restart that same dedicated instance
  and resumes only a pause that Lattice created.
- Disconnect recognizes Syncthing v2's empty database-model state for a folder
  whose configuration has separately confirmed that it is paused.

## 2.2.4 — 2026-08-22

### Added

- **Disconnect library drive** pauses only the stable Lattice Syncthing folder,
  waits for the paused state, stops Lattice's drive-backed local service, and
  closes the app so an external SSD can be ejected safely.
- **Reconnect library sync** restores only a pause created by Lattice. On
  Windows it can also restart the dedicated per-user Syncthing instance when
  that process was stopped.

### Fixed

- Moving a library to external storage no longer leaves users without an
  in-app path to release Syncthing's filesystem watcher before ejecting the
  drive.

## 2.2.3 — 2026-08-22

### Changed

- Public macOS and Windows packages now carry version 2.2.3 so release metadata
  and installed application versions remain aligned. Version 2.2.2 was not
  published.

## 2.2.1 — 2026-08-22

### Added

- Direct in-app macOS updates from `/Applications/Lattice.app`. Lattice now
  verifies the shared RSA-signed release manifest and exact macOS ZIP digest,
  stages and validates the bundle, preserves the installed version, relaunches
  the candidate, and automatically rolls back unless the updated shelf becomes
  healthy.

### Fixed

- Rapid macOS close-and-reopen cycles no longer attach to a stale local server;
  each relaunched app verifies that its own isolated service is healthy before
  completing an update.
- The macOS CI signing-key equivalence check no longer depends on an
  OpenSSL-version-specific conversion command.
- macOS update bundles now use bounded in-process Mach-O and Security framework
  validation instead of depending on command-line verifier behavior.

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
