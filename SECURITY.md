# Security Policy

CS Library is a local desktop application that opens untrusted PDF, EPUB, and
text files. The principal security goal is to keep those files and all reading
data on the selected Mac while preventing local content from escaping the
library boundary or executing active web content.

## Supported version

The current development line is version 2.x on macOS 13 or later. Security fixes
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
- Serves only currently indexed files beneath `books/` or `papers/`.
- Resolves paths and rejects traversal and symlink escape.
- Requires a random in-memory token for Finder/open actions.
- Accepts those actions only from loopback origins.
- Exits when its native parent disappears when launched by the Mac app.

### EPUB isolation

- Book resources are served with a restrictive content security policy.
- Book-supplied JavaScript is disabled.
- External connections, forms, objects, and child frames are disabled.
- Archive traversal, encrypted entries, duplicate paths, excessive resource
  counts, excessive uncompressed size, and suspicious compression ratios are
  rejected.
- Only resources from the validated EPUB package are served.

### Native files

- Native file resolution accepts only relative paths under `books/` or `papers/`.
- Paths are canonicalized and symlinks are resolved before containment checks.
- Only PDF, EPUB, and TXT files are accepted by the reader/import workflow.

### Reader data

- Progress, notes, bookmarks, annotations, and sessions are stored in a local
  SQLite database.
- Database writes use transactions and WAL mode.
- Daily local backups are retained.
- Reader data can be exported to JSON or Markdown.
- No telemetry, cloud synchronization, or remote annotation service is present.

## Remaining trust boundaries

- PDF parsing and rendering depend on Apple's PDFKit.
- Web rendering depends on WebKit.
- The local service depends on the user's Python 3 runtime.
- Ad-hoc signing verifies bundle consistency but is not Developer ID
  notarization.
- Imported books may have restrictive copyright or machine-processing terms;
  access rights are tracked separately from software security.

## Secure-development expectations

Changes that affect path handling, EPUB parsing, native bridge messages,
database migrations, imports, or server lifecycle require tests. Do not weaken
content security policy, host validation, catalog allowlisting, archive limits,
or native path containment to support a single malformed book.
