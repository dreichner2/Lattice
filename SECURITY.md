# Security Policy

Lattice is a local desktop application that opens untrusted PDF, EPUB, and
text files. The principal security goal is to keep those files and all reading
data on the selected computer while preventing local content from escaping the
library boundary or executing active web content.

## Supported version

The current development line is version 2.x on macOS 13 or later and Windows
10 build 19041 or later. Security fixes
are made on the repository's protected development branch and should be included
in the next tagged release.

## Reporting a vulnerability

Do not post sensitive details in a public issue. Send the repository owner a
private GitHub message or use a private GitHub security advisory when available.
Include the affected commit, reproduction steps, expected impact, and whether a
malicious document is required.

## Security properties

### Local service

- Binds only to `127.0.0.1`.
- Rejects non-loopback `Host` values.
- Publishes a protocol version and library-root identity.
- Serves only currently indexed files beneath approved payload roots.
- Resolves paths and rejects traversal and symlink escape.
- Requires a random in-memory token for platform file actions and reader-state APIs.
- Requires that token for file import and metadata mutation. Browser requests
  must be same-origin; native clients may omit `Origin` and authenticate with
  the token over loopback.
- Streams imports to a bounded temporary file, validates the supported format,
  computes integrity fields locally, and atomically installs a collision-safe
  payload and adjacent sidecar.
- Exits when its desktop parent disappears when launched by either packaged app.

### EPUB isolation

- Book resources are served with a restrictive content security policy.
- Book-supplied JavaScript is disabled.
- External connections, forms, objects, and child frames are disabled.
- Archive traversal, encrypted entries, duplicate paths, excessive resource
  counts, excessive uncompressed size, and suspicious compression ratios are
  rejected.
- Only resources from the validated EPUB package are served.

### Native files

- Native file resolution accepts only relative paths under approved payload roots.
- Paths are canonicalized and symlinks are resolved before containment checks.
- Only PDF, EPUB, and TXT files are accepted by the reader/import workflow.

### Imported metadata and Codex

- Sidecar names append `.library.json` to the full payload filename; clients do
  not supply an arbitrary destination path.
- `path`, `bytes`, `sha256`, material type, access defaults, and import
  provenance are computed and owned by the local server. Model output and
  manual edits cannot replace them.
- Sidecars are parsed as untrusted, size-bounded JSON. Unknown subject IDs and
  malformed fields fall back to the checked-in taxonomy instead of changing the
  server's trust boundary.
- Optional enrichment invokes the authenticated local Codex CLI with
  `gpt-5.6-luna` in an ephemeral temporary read-only context with execution,
  browser, app, image, and workspace tools disabled. Lattice does not read,
  copy, print, or synchronize Codex credential files.
- The model prompt contains the filename, selected material kind, extracted
  EPUB publication metadata, and allowed subject list—not the document bytes or
  full text. PDF requests are filename-only. Supplied fields are treated as
  untrusted strings, and structured output is validated before it can update
  descriptive fields.
- Missing CLI, signed-out state, timeout, model error, or invalid output never
  prevents the already validated local import from completing.

### Reader data

- Native Mac progress, notes, bookmarks, annotations, and sessions are stored
  in its local SQLite database. Windows web-reader state uses a separate local
  SQLite database scoped by library identity.
- Database writes use transactions and WAL mode.
- Daily local backups are retained.
- Reader data can be exported to JSON or Markdown.
- No telemetry, cloud synchronization, or remote annotation service is present.
  Syncthing payload/sidecar replication and optional Codex enrichment are
  separate, explicit boundaries; neither includes live reader databases.

## Remaining trust boundaries

- PDF parsing and rendering depend on Apple's PDFKit on macOS and the installed
  Microsoft Edge WebView2 Runtime on Windows.
- Web rendering depends on WebKit on macOS and WebView2 on Windows.
- The Mac local service depends on the user's Python 3 runtime; the Windows
  artifact bundles its Python service with PyInstaller.
- Optional metadata enrichment depends on the locally installed Codex CLI, its
  authenticated session, model availability, and OpenAI service connectivity.
- Ad-hoc signing verifies bundle consistency but is not Developer ID
  notarization.
- Imported books may have restrictive copyright or machine-processing terms;
  access rights are tracked separately from software security.

## Secure-development expectations

Changes that affect path handling, EPUB parsing, native bridge messages,
database migrations, uploads, sidecars, Codex invocation, or server lifecycle
require tests. Do not weaken content security policy, host validation, catalog
allowlisting, upload limits, archive limits, taxonomy validation, or native path
containment to support a single malformed document.
