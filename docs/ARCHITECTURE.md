# CS Library Architecture

CS Library is a local-first reading system with one shared shelf interface and
platform-specific desktop readers.

## Components

### Catalog and content service

`scripts/library_ui.py` owns the catalog model, EPUB parsing, file discovery,
range requests, security headers, and token-protected operating-system actions.
It binds only to loopback.

`scripts/cross_platform_server.py` wraps that service for desktop use. It adds a
stable library identity, a protocol version, parent-process monitoring, a
versioned SQLite reader store, export/import endpoints, and the static Windows
reader assets.

### Shared shelf interface

`ui/` is the browser-compatible catalog and EPUB reader. The same files render
inside WKWebView on macOS and WebView2 on Windows. Native applications inject:

- `native/SharedReaderState.js` at document start to hydrate and mirror all
  `cs-library:*` browser state through SQLite; and
- `native/ImmersiveEPUB.js` after document load for native-app EPUB shortcuts,
  reading sessions, quotes, and notes.

### macOS application

`native/` contains the AppKit shell and PDFKit workspace. PDF state continues to
use the existing reader model, while `ReaderDataStore.swift` mirrors it into the
same SQLite schema used by the cross-platform server. The app validates the
library identity before connecting to any existing loopback process.

### Windows application

`windows/CSLibrary.Windows/` is a .NET 8 WPF application using WebView2. It
renders the same shelf and EPUB UI, validates the local service identity, and
intercepts PDF navigation to open `windows/reader/`, an offline PDF.js
workspace. The release build bundles the Python server with PyInstaller, so the
portable Windows package does not require Python.

### Reader state

The desktop database is named `reader-state.sqlite3` and lives in the operating
system's application-data directory. The schema is intentionally simple and
versioned:

- `kv_state` stores namespaced JSON state;
- `reading_sessions` reserves durable active-reading records; and
- `schema_meta` records migrations.

PDF records use a stable base64url key derived from the material's relative
library path. Browser/EPUB state is stored under the `localStorage` namespace.
The same JSON export can be imported on either platform.

## Trust boundaries

- Book bytes never leave the selected library folder.
- HTTP listeners bind to `127.0.0.1` only.
- Host headers, origins, action tokens, path traversal, and symlink escapes are
  validated.
- EPUB resources execute no publisher scripts and cannot make network requests.
- The desktop host verifies `libraryId` and `protocolVersion` before attaching
  to a running server.
- The server exits when its owning desktop process disappears.

## Build outputs

Generated applications and dependency trees are ignored by Git:

- `CS Library.app/`
- `windows/build/`
- `windows/reader/vendor/`
- `windows/reader/node_modules/`
- `artifacts/`

The macOS script builds and verifies a staged application before atomically
replacing the existing app. The Windows script builds a self-contained WPF app,
a one-file local server, offline PDF.js assets, and a portable ZIP.
