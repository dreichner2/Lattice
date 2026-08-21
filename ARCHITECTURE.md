# CS Library Architecture

CS Library is a local-first macOS and Windows reading and study system. The repository keeps
source code, catalog metadata, provenance records, and integrity manifests in
Git. Book and paper payloads remain on the selected local computers.

## System boundaries

```text
┌──────────────────────────────── macOS app ────────────────────────────────┐
│ AppKit shell                                                             │
│  ├─ library-folder selection and import                                  │
│  ├─ menus, diagnostics, export/import, and application lifecycle          │
│  ├─ native PDFKit reader                                                  │
│  └─ durable ReaderStore (SQLite)                                          │
│                                                                          │
│ WKWebView                                                                 │
│  ├─ shared shelf interface (`ui/`)                                        │
│  ├─ EPUB renderer                                                        │
│  ├─ native EPUB enhancement (`ImmersiveEPUB.js`)                          │
│  └─ unified notebook/search workspace (`LibraryWorkspace.js`)             │
│                                                                          │
│ Formal bridge (`ReaderBridge`)                                            │
│  └─ typed request/response messages between WKWebView and ReaderStore      │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │ loopback HTTP only
┌───────────────────────────────▼───────────────────────────────────────────┐
│ Python local service (`scripts/library_ui.py`)                            │
│  ├─ validates the library root and server instance identity               │
│  ├─ builds the catalog payload and watches local files                     │
│  ├─ serves bundled or repository UI resources                             │
│  ├─ serves byte-ranged PDF/TXT payloads                                   │
│  ├─ parses and securely serves EPUB resources                             │
│  └─ exposes token-protected platform file actions                         │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │ read-only indexing
┌───────────────────────────────▼───────────────────────────────────────────┐
│ Selected library folder                                                   │
│  ├─ CATALOG.md / metadata / manifests / provenance                        │
│  ├─ books/                                                                │
│  └─ papers/                                                               │
└───────────────────────────────────────────────────────────────────────────┘
```

## Native reader data

Reader-created data is stored at:

```text
~/Library/Application Support/CS Library/Library.sqlite
```

The database is versioned and migrated in place. It contains:

- stable document identities;
- reading positions;
- bookmarks;
- PDF and EPUB annotations;
- notes and quotations;
- elapsed reading sessions;
- preferences; and
- a local full-text index for documents, annotations, and indexed content.

The document identity uses the catalog work ID when available, then the recorded
SHA-256, and finally the normalized relative path. Cataloged works therefore
survive ordinary filename changes.

See [Reader data and recovery](docs/READER_DATA.md) for schema and recovery
behavior.

## Web/native message bridge

`ReaderBridge.swift` injects a small promise-based API into the main frame:

```javascript
window.csLibraryNativeCall(action, payload)
```

Messages are accepted only from the main frame. The bridge handles document
opening, position saves, bookmark and annotation changes, reader sessions,
full-text indexing, notebook queries, search, and diagnostics.

Reader UI code must not scrape native state from DOM text or depend on URL
navigation as its primary integration path. A narrow PDF URL interceptor remains
only as a compatibility fallback for older interface builds.

## PDF reader

PDFs opened in the native app use PDFKit. The reader owns rendering, page
labels, thumbnails, navigation, search, zoom and display modes, notes,
bookmarks, highlights, and reading sessions. PDF content is indexed locally in
the background when the document is opened.

The browser version continues to use the browser's PDF renderer.

## EPUB reader

EPUB package parsing and resource serving happen in Python. Rendering happens in
the shared WebKit reader. The native enhancement layer adds durable quotations
and notes, chapter text indexing, elapsed reading sessions, and the native
notebook. EPUB content never executes book-supplied scripts.

## Local service identity

The app accepts a running service only when all of the following match:

- application name;
- protocol version; and
- SHA-256 library-root identity.

This prevents the app from attaching to an old server or a different checkout
that happens to use the same local port. A parent-process watcher stops a service
started by the app if the native parent process disappears.

## Build and distribution

`scripts/build-macos-app.sh` stages a complete app in a private temporary directory, compiles
and signs it, verifies resources and code signing, and only then replaces the
previous app. The previous app is restored if installation fails.

The app bundle contains the shared UI, local Python service, and native reader
scripts. Books remain external in the selected library folder. Python 3 is still
a runtime dependency for the local service.

## Windows host

`windows/CSLibrary.Windows` is a .NET 8 WPF shell around WebView2. The packaged
app starts a PyInstaller-built `CSLibraryServer.exe`, verifies readiness through
the same protocol/library identity contract, and navigates only to the loopback
service. External HTTP links open in the system browser.

The Windows service subclasses the shared Python server to add Windows-safe
open/reveal actions and a WAL-backed mirror of `cs-library:*` web-reader state.
State rows are scoped by library identity and stored under the current user's
local application-data directory. This database is deliberately outside the
Syncthing folder so two machines never concurrently synchronize live SQLite
WAL files.

The Windows CI build publishes a self-contained x64 WPF app, the bundled Python
service, the metadata/UI skeleton, and empty `books/` and `papers/` directories
as a portable ZIP. Copyrighted reading payloads are never part of the artifact.

## Change rules

When changing a boundary, update its tests and documentation:

- database or bridge: update ReaderStore smoke tests and `READER_DATA.md`;
- Python protocol: update `test_server_contract.py` and protocol version;
- EPUB behavior: update the Node tests;
- AppKit/PDFKit: ensure the macOS Actions build passes;
- WPF/WebView2 or Windows service: ensure the Windows Actions build passes;
- security boundary: update `SECURITY.md`.
