# Reader Data, Backup, and Recovery

## Location

The native Mac app stores user-created reading data at:

```text
~/Library/Application Support/CS Library/Library.sqlite
```

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

## Stable identities

A document ID uses the catalog work ID when available, then the recorded
SHA-256, and finally the relative path. This allows cataloged progress and
annotations to follow ordinary filename changes.

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
{"type":"pdf","page":42}
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

When a PDF is opened, version 2 imports the previous UserDefaults-based page,
zoom, display mode, bookmarks, and page notes once. EPUB state is restored
through the formal bridge and then saved in ReaderStore. The app no longer uses
browser localStorage as the authoritative native reader database.

## Recovery

1. Quit CS Library.
2. Preserve `Library.sqlite`, `Library.sqlite-wal`, and `Library.sqlite-shm` if
   present.
3. Use the Diagnostics command to run `PRAGMA integrity_check` when the app can
   start.
4. Restore a recent backup only after copying the current files elsewhere.
5. Import a JSON export to merge portable reader records.

Do not edit the live database while the app is running.
