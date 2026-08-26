# Reader Data, Backup, and Recovery

## Location

The native Mac app stores user-created reading data at:

```text
~/Library/Application Support/CS Library/Library.sqlite
```

`CS Library` is the retained storage identifier from earlier releases. The
visible application is **Lattice**, but the support directory does not
move; this preserves existing notes, progress, and backups during upgrade.

Backups are written to:

```text
~/Library/Application Support/CS Library/Backups/
```

The application keeps up to 14 timestamped database backups, attempts one
backup per day, and also backs up on a clean app shutdown. A manual export is
still recommended before major library reorganization.

## What is stored

- document identities and latest paths;
- exact PDF page and EPUB location;
- bookmarks;
- PDF page notes;
- PDF and EPUB highlights;
- quotations and annotations;
- elapsed reading sessions while a reader is open;
- reader preferences; and
- local full-text index entries.

The shared Reading Desk also keeps its working copy and unsaved drafts in the
local WebView/browser profile. In the Mac app, saved notes and bookmarks are
mirrored into this SQLite store; neither store is telemetry or remote state.

## Stable identities

A document ID uses the payload SHA-256 when available and otherwise its relative
path. Reader state therefore follows an unchanged file when it moves, while a
PDF and EPUB belonging to the same catalog work remain separate. Opening an old
work-scoped record migrates only locator data matching the exact payload format;
ambiguous mixed-format data is preserved under its legacy record rather than
being guessed or deleted.

## Schema

The database currently contains:

```text
schema_migrations
  version, applied_at

documents
  id, work_id, path, sha256, title, format, updated_at

reading_positions
  document_id, locator_json, page, progress, updated_at

bookmarks
  id, document_id, locator_json, label, created_at

annotations
  id, document_id, locator_json, quote, note, color,
  created_at, updated_at

reading_sessions
  id, document_id, started_at, ended_at, seconds, pages_read

preferences
  key, value

search_items / search_items_fts
  local searchable document, content, bookmark, and annotation records
```

`locator_json` is deliberately format-specific. Typical examples:

```json
{"type":"pdf","page":42,"pageBase":1}
```

```json
{
  "type":"epub",
  "entry":"EPUB/chapter-03.xhtml",
  "ratio":0.41,
  "quote":"selected text",
  "range":{"startPath":"/html/body/p[2]","startOffset":14,"endPath":"/html/body/p[2]","endOffset":58}
}
```

## Export

The File menu can export:

- **JSON** — complete machine-readable reader data for backup or migration;
- **Markdown** — human-readable notebook containing quotations and notes.

JSON import merges records by stable IDs. It does not delete unrelated current
records.

## Legacy migration

When a PDF is opened, Lattice imports previous UserDefaults-based page, zoom,
display mode, bookmarks, and page notes once. Zero-based PDFKit locators are
converted to explicit one-based pages, while already one-based web locators are
left unchanged. Former work-scoped identities migrate only matching-work,
matching-format locators; path-fallback identities additionally require the
exact path. The operation is idempotent. EPUB state is restored through the
formal bridge and then saved in ReaderStore.

## Recovery

1. Quit Lattice.
2. Preserve `Library.sqlite`, `Library.sqlite-wal`, and `Library.sqlite-shm` if
   present.
3. Use the Diagnostics command to run `PRAGMA integrity_check` when the app can
   start.
4. Restore a recent backup only after copying the current files elsewhere.
5. Import a JSON export to merge portable reader records.

Do not edit the live database while the app is running.
