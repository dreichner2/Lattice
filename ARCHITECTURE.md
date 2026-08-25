# Lattice Architecture

Lattice is a shared knowledge library and local-first macOS and Windows reading
and study system. The
repository keeps source code, the cross-subject taxonomy, curated catalog
metadata, provenance records, and integrity manifests in Git. Private books,
papers, lectures, and their adjacent sidecars remain on the selected computers
and can be synchronized through Syncthing.

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
│  ├─ optional source-scoped Tutor drawer (`tutor.js`)                       │
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
│  ├─ validates imports and writes collision-safe payloads and sidecars      │
│  ├─ optionally asks local Codex for metadata-only classification           │
│  ├─ brokers source-scoped Tutor turns (`lattice_tutor.py`)                 │
│  ├─ extracts PDF/EPUB/text into a private per-device Tutor index           │
│  ├─ serves bundled or repository UI resources                             │
│  ├─ serves byte-ranged PDF/TXT payloads                                   │
│  ├─ parses and securely serves EPUB resources                             │
│  └─ exposes token-protected platform file actions                         │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │ validated local reads and writes
┌───────────────────────────────▼───────────────────────────────────────────┐
│ Selected library folder                                                   │
│  ├─ CATALOG.md / library-taxonomy.json / metadata / manifests              │
│  ├─ books/       payload + `<filename>.library.json`                       │
│  ├─ papers/      payload + `<filename>.library.json`                       │
│  └─ lectures/    payload + `<filename>.library.json`                       │
└───────────────────────────────────────────────────────────────────────────┘
```

## Storage relocation

The native Windows and macOS shells expose Move Library, backed by the bundled
`scripts/move_library.py` helper (a standalone `LatticeStorage.exe` in the
Windows package). The helper treats relocation as a gated transaction:

Move Library relocates the selected reading-library checkout, not the installed
application or private reader state. Executables, update infrastructure, WebView
profiles, Tutor data, and language runtimes remain on internal storage. Keeping
the small catalog/scaffold beside the payload roots preserves stable relative
paths, adjacent sidecars, library identity, and the established Syncthing root.

1. validate the complete library and reject linked or special filesystem
   entries, nested destinations, insufficient capacity, and an app running from
   inside the library;
2. discover Syncthing's local configuration without exposing its API key,
   authenticate only to a loopback HTTP API, verify the stable folder ID/path,
   and require an up-to-date Send & Receive folder;
3. pause that folder, copy to a unique destination-side staging directory,
   flush writes, and compare SHA-256 for every source/destination file;
4. atomically publish the destination directory, patch the existing Syncthing
   folder path, restore its pause state, rescan, and require a healthy status;
   and
5. remove the source only after those gates pass. Before path activation,
   failures remove only operation-owned staging data. After activation, failures
   attempt to restore Syncthing's original path and preserve both verified
   copies if that rollback cannot be confirmed.

Reader databases remain in their existing per-user application-support paths;
they are not moved or synchronized. The helper never edits `config.xml`, stores
the Syncthing API key, or sends it beyond the configured loopback endpoint.

## macOS direct updates

`MacUpdateChecker` downloads the same fixed, RSA-signed release manifest used
by Windows and selects the version-pinned `macos-arm64` asset. The manifest
authorizes the exact GitHub URL, size, and SHA-256 before `MacUpdateInstaller`
downloads or extracts code.

Direct replacement is enabled only for `/Applications/Lattice.app`. The app
stages the update in a private per-user directory, rejects linked or special
files, validates the bundle identifier, version, arm64 executable, and strict
code-signature consistency, then launches its existing executable in helper
mode. After the current process exits, the helper re-verifies the signed
manifest and archive, preserves the old bundle under a collision-safe hidden
name, installs the candidate, and launches it with an operation-bound private
activation record.
The token lives only in private mode-0600 operation records; process arguments
contain an opaque operation ID. The candidate writes its token-bound health
marker only after the local service and shared shelf finish loading. A missing
marker or early exit restores and relaunches the previous bundle; the library
folder, Syncthing configuration, and reader database are outside this
transaction. Once the candidate is healthy, the transient previous bundle is
deleted; successful updates do not retain application rollback copies.

## Product identity and compatibility IDs

**Lattice** is the visible product and Syncthing label. Existing internal
identifiers remain stable so upgrades do not orphan data or require device
re-pairing:

- repository and checkout name: `cs-library`;
- Syncthing folder ID: `cs-library-3b8290f24f15`;
- native support directory: `~/Library/Application Support/CS Library/`;
- Windows state directory: `%LOCALAPPDATA%\CS Library`;
- web state namespace: `cs-library:*`; and
- established server protocol and storage identifiers.

The display name may change independently from these compatibility contracts.

## Subjects, topics, and imported metadata

`library-taxonomy.json` is the classification authority. Its stable subject IDs
span computing, engineering, mathematics, science, interdisciplinary material,
and an explicit `other` fallback. The existing curated catalog defaults to
`computer-science`; topic defaults and selected work overrides place known items
more precisely without rewriting the catalog's useful shelf organization.

Normal UI imports do not modify Git-tracked `CATALOG.md` or `metadata/`. For a
payload such as `books/example.pdf`, the service writes
`books/example.pdf.library.json`. Appending the suffix to the full filename
avoids PDF/EPUB same-stem collisions. The payload and sidecar are inside the
same Syncthing-allowlisted directory and therefore converge together on paired
devices. The loader treats sidecars as untrusted input and falls back safely if
one is missing or invalid.

Optional enrichment invokes the locally installed, authenticated Codex CLI with
`gpt-5.6-luna`. Only the filename, selected material kind, locally extracted
publication metadata, and allowed subject list are included in the
classification prompt; document bytes and full text are not.
The process runs in a temporary context with read-only sandboxing, and import
completion never depends on model availability or valid model output.

## Lattice Tutor

Tutor is a separate, optional path from the shelf and reader. The UI sends a
token-protected request containing the chosen Luna/Terra/Sol model, reasoning
effort, scope, selected work/course IDs, and one question. Conversation history
is bounded and retained only in the local service's memory.

Reader launches use a compact presentation scoped to the open work. It has no
scrim, leaves the reading surface interactive, and keeps model/source controls
behind an explicit expand action. The immersive PDF reader exposes the same
path through a small edge control because its host toolbar is intentionally
hidden.

`lattice_tutor.py` resolves source IDs against the current server-built catalog;
the client cannot submit arbitrary paths. Eligible PDF, EPUB, archive, and text
sources are extracted incrementally into a SQLite/FTS cache outside both the
library and reader database. `pypdf` 6.15.0 is vendored for consistent PDF text
extraction on macOS, Windows, and source checkouts. Human-study-only and
personalized/private works are never admitted and are pruned if eligibility
changes. Video sources contribute catalog and lecture-title metadata only.

Each turn invokes the same installed, authenticated Codex CLI used by import
enrichment, but as a fresh ephemeral run that ignores user configuration and
repository rules. The child environment is allowlisted, model tools have no
network access, apps/plugins/browser/computer-use/multi-agent features are
disabled, and filesystem permissions stay read-only. macOS grants only the
exact eligible files in the active scope. Windows stages the bounded turn
context in a single disposable workspace and grants only that root, so the
native sandbox never needs split permissions or access to an external library
volume. Source text is labeled as untrusted data. The structured response
schema and every returned citation are validated against that same scope before
the browser can display or open them.

## Native reader data

Reader-created data is stored at:

```text
~/Library/Application Support/CS Library/Library.sqlite
```

`CS Library` in this path is an intentionally retained storage ID, not the
visible application name.

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
scripts. Reading payloads and private sidecars remain external in the selected
library folder. Python 3 is still a runtime dependency for the local service.

## Windows host

`windows/CSLibrary.Windows` is a .NET 8 WPF shell around WebView2. The packaged
app starts a PyInstaller-built `LatticeServer.exe`, verifies readiness through
the same protocol/library identity contract, and navigates only to the loopback
service. External HTTP links open in the system browser.

The host keeps the standard compact Windows caption and does not render a
second native command bar. A document-start WebView2 message bridge exposes a
small allowlist of desktop actions to the shared inline header menu: update,
Move Library, open/switch library, and reload. Messages are accepted only while
the WebView is on the owned loopback origin.

The Windows service subclasses the shared Python server to add Windows-safe
open/reveal actions and a WAL-backed mirror of `cs-library:*` web-reader state.
State rows are scoped by library identity and stored under the current user's
local application-data directory. This database is deliberately outside the
Syncthing folder so two machines never concurrently synchronize live SQLite
WAL files.

The Windows CI build publishes a self-contained x64 WPF app, the bundled Python
service, the metadata/UI skeleton, the taxonomy, and empty `books/`, `papers/`,
and `lectures/` directories as a portable ZIP. Copyrighted reading payloads and
private sidecars are never part of the artifact.

## Change rules

When changing a boundary, update its tests and documentation:

- database or bridge: update ReaderStore smoke tests and `READER_DATA.md`;
- Python protocol: update `test_server_contract.py` and protocol version;
- taxonomy, scaffold, or sidecar naming: update `library-layout.json`,
  `library-taxonomy.json`, and `test_library_layout.py`;
- EPUB behavior: update the Node tests;
- AppKit/PDFKit: ensure the macOS Actions build passes;
- WPF/WebView2 or Windows service: ensure the Windows Actions build passes;
- security boundary: update `SECURITY.md`.
