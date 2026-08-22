import Foundation
import SQLite3

enum ReaderStoreError: LocalizedError {
    case database(String)
    case invalidImport(String)

    var errorDescription: String? {
        switch self {
        case .database(let message): return "Reader database error: \(message)"
        case .invalidImport(let message): return "Invalid reading-data import: \(message)"
        }
    }
}

private enum SQLiteValue {
    case text(String)
    case integer(Int64)
    case double(Double)
    case null
}

final class ReaderStore {
    static let currentSchemaVersion = 1
    static let exportFormatVersion = 1

    let dataDirectory: URL
    let databaseURL: URL

    private let lock = NSRecursiveLock()
    private var database: OpaquePointer?
    private var transactionDepth = 0
    private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    init(dataDirectory: URL? = nil) throws {
        let manager = FileManager.default
        if let dataDirectory {
            self.dataDirectory = dataDirectory
        } else {
            self.dataDirectory = manager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("CS Library", isDirectory: true)
        }
        databaseURL = self.dataDirectory.appendingPathComponent("Library.sqlite")
        try manager.createDirectory(at: self.dataDirectory, withIntermediateDirectories: true)
        try manager.createDirectory(at: backupsDirectory, withIntermediateDirectories: true)
        try manager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: self.dataDirectory.path)
        try manager.setAttributes([.posixPermissions: 0o700], ofItemAtPath: backupsDirectory.path)

        var connection: OpaquePointer?
        let flags = SQLITE_OPEN_CREATE | SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX
        guard sqlite3_open_v2(databaseURL.path, &connection, flags, nil) == SQLITE_OK, let connection else {
            let message = connection.map { String(cString: sqlite3_errmsg($0)) } ?? "Could not open Library.sqlite"
            if let connection { sqlite3_close_v2(connection) }
            throw ReaderStoreError.database(message)
        }
        database = connection
        try? manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: databaseURL.path)

        do {
            try execute("PRAGMA journal_mode=WAL")
            try execute("PRAGMA synchronous=FULL")
            try execute("PRAGMA foreign_keys=ON")
            try execute("PRAGMA busy_timeout=5000")
            try migrate()
            try createBackupIfNeeded(force: false)
        } catch {
            sqlite3_close_v2(connection)
            database = nil
            throw error
        }
    }

    deinit {
        lock.lock()
        if let database { sqlite3_close_v2(database) }
        database = nil
        lock.unlock()
    }

    var backupsDirectory: URL {
        dataDirectory.appendingPathComponent("Backups", isDirectory: true)
    }

    // MARK: Documents and progress

    func upsertDocument(_ document: ReaderDocument) throws {
        try execute(
            """
            INSERT INTO documents(id, work_id, path, sha256, title, format, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              work_id=excluded.work_id, path=excluded.path, sha256=excluded.sha256,
              title=excluded.title, format=excluded.format, updated_at=excluded.updated_at
            """,
            [.text(document.id), optionalText(document.workID), .text(document.path), optionalText(document.sha256),
             .text(document.title), .text(document.format), .double(document.updatedAt)]
        )
    }

    func document(id: String) throws -> ReaderDocument? {
        try queryOne(
            "SELECT id, work_id, path, sha256, title, format, updated_at FROM documents WHERE id=?",
            [.text(id)]
        ) { statement in
            ReaderDocument(
                id: text(statement, 0), workID: optionalColumnText(statement, 1), path: text(statement, 2),
                sha256: optionalColumnText(statement, 3), title: text(statement, 4), format: text(statement, 5),
                updatedAt: sqlite3_column_double(statement, 6)
            )
        }
    }

    func document(path: String) throws -> ReaderDocument? {
        try queryOne(
            "SELECT id, work_id, path, sha256, title, format, updated_at FROM documents WHERE path=? ORDER BY updated_at DESC LIMIT 1",
            [.text(path)]
        ) { statement in
            ReaderDocument(
                id: text(statement, 0), workID: optionalColumnText(statement, 1), path: text(statement, 2),
                sha256: optionalColumnText(statement, 3), title: text(statement, 4), format: text(statement, 5),
                updatedAt: sqlite3_column_double(statement, 6)
            )
        }
    }

    func documents() throws -> [ReaderDocument] {
        try query("SELECT id, work_id, path, sha256, title, format, updated_at FROM documents ORDER BY title COLLATE NOCASE") { statement in
            ReaderDocument(
                id: text(statement, 0), workID: optionalColumnText(statement, 1), path: text(statement, 2),
                sha256: optionalColumnText(statement, 3), title: text(statement, 4), format: text(statement, 5),
                updatedAt: sqlite3_column_double(statement, 6)
            )
        }
    }

    func savePosition(_ position: ReaderPosition) throws {
        try execute(
            """
            INSERT INTO reading_positions(document_id, locator_json, page, progress, updated_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(document_id) DO UPDATE SET locator_json=excluded.locator_json,
              page=excluded.page, progress=excluded.progress, updated_at=excluded.updated_at
            """,
            [.text(position.documentID), .text(position.locator), optionalInteger(position.page),
             .double(clamp(position.progress)), .double(position.updatedAt)]
        )
    }

    func position(documentID: String) throws -> ReaderPosition? {
        try queryOne(
            "SELECT document_id, locator_json, page, progress, updated_at FROM reading_positions WHERE document_id=?",
            [.text(documentID)]
        ) { statement in
            ReaderPosition(
                documentID: text(statement, 0), locator: text(statement, 1),
                page: optionalInt(statement, 2), progress: sqlite3_column_double(statement, 3),
                updatedAt: sqlite3_column_double(statement, 4)
            )
        }
    }

    // MARK: Bookmarks and annotations

    func saveBookmark(_ bookmark: ReaderBookmark) throws {
        try execute(
            """
            INSERT INTO bookmarks(id, document_id, locator_json, label, created_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET locator_json=excluded.locator_json, label=excluded.label
            """,
            [.text(bookmark.id), .text(bookmark.documentID), .text(bookmark.locator), .text(bookmark.label), .double(bookmark.createdAt)]
        )
        try indexSearchItems([
            ReaderSearchItem(id: "bookmark:\(bookmark.id)", documentID: bookmark.documentID, kind: "bookmark",
                             title: bookmark.label, body: bookmark.locator, updatedAt: bookmark.createdAt)
        ])
    }

    func deleteBookmark(id: String) throws {
        try transaction {
            try execute("DELETE FROM bookmarks WHERE id=?", [.text(id)])
            try execute("DELETE FROM search_items WHERE id=?", [.text("bookmark:\(id)")])
            try execute("DELETE FROM search_items_fts WHERE id=?", [.text("bookmark:\(id)")])
        }
    }

    func bookmarks(documentID: String? = nil) throws -> [ReaderBookmark] {
        let filter = documentID == nil ? "" : " WHERE document_id=?"
        return try query(
            "SELECT id, document_id, locator_json, label, created_at FROM bookmarks\(filter) ORDER BY created_at DESC",
            documentID.map { [.text($0)] } ?? []
        ) { statement in
            ReaderBookmark(id: text(statement, 0), documentID: text(statement, 1), locator: text(statement, 2),
                           label: text(statement, 3), createdAt: sqlite3_column_double(statement, 4))
        }
    }

    func saveAnnotation(_ annotation: ReaderAnnotation) throws {
        try execute(
            """
            INSERT INTO annotations(id, document_id, locator_json, quote, note, color, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET locator_json=excluded.locator_json, quote=excluded.quote,
              note=excluded.note, color=excluded.color, updated_at=excluded.updated_at
            """,
            [.text(annotation.id), .text(annotation.documentID), .text(annotation.locator), .text(annotation.quote),
             .text(annotation.note), .text(annotation.color), .double(annotation.createdAt), .double(annotation.updatedAt)]
        )
        try indexSearchItems([
            ReaderSearchItem(id: "annotation:\(annotation.id)", documentID: annotation.documentID, kind: "annotation",
                             title: annotation.quote.isEmpty ? "Reader note" : annotation.quote,
                             body: annotation.note, updatedAt: annotation.updatedAt)
        ])
    }

    func deleteAnnotation(id: String) throws {
        try transaction {
            try execute("DELETE FROM annotations WHERE id=?", [.text(id)])
            try execute("DELETE FROM search_items WHERE id=?", [.text("annotation:\(id)")])
            try execute("DELETE FROM search_items_fts WHERE id=?", [.text("annotation:\(id)")])
        }
    }

    func annotations(documentID: String? = nil) throws -> [ReaderAnnotation] {
        let filter = documentID == nil ? "" : " WHERE document_id=?"
        return try query(
            "SELECT id, document_id, locator_json, quote, note, color, created_at, updated_at FROM annotations\(filter) ORDER BY updated_at DESC",
            documentID.map { [.text($0)] } ?? []
        ) { statement in
            ReaderAnnotation(id: text(statement, 0), documentID: text(statement, 1), locator: text(statement, 2),
                             quote: text(statement, 3), note: text(statement, 4), color: text(statement, 5),
                             createdAt: sqlite3_column_double(statement, 6), updatedAt: sqlite3_column_double(statement, 7))
        }
    }

    // MARK: Sessions and preferences

    func startSession(documentID: String, at timestamp: Double = Date().timeIntervalSince1970) throws -> ReaderSession {
        let session = ReaderSession(id: UUID().uuidString.lowercased(), documentID: documentID, startedAt: timestamp,
                                    endedAt: nil, seconds: 0, pagesRead: 0)
        try execute(
            "INSERT INTO reading_sessions(id, document_id, started_at, ended_at, seconds, pages_read) VALUES(?, ?, ?, NULL, 0, 0)",
            [.text(session.id), .text(documentID), .double(timestamp)]
        )
        return session
    }

    func finishSession(id: String, pagesRead: Int = 0, at timestamp: Double = Date().timeIntervalSince1970) throws {
        try execute(
            """
            UPDATE reading_sessions SET ended_at=?, seconds=MAX(0, CAST(? - started_at AS INTEGER)), pages_read=?
            WHERE id=? AND ended_at IS NULL
            """,
            [.double(timestamp), .double(timestamp), .integer(Int64(max(0, pagesRead))), .text(id)]
        )
    }

    func sessions() throws -> [ReaderSession] {
        try query("SELECT id, document_id, started_at, ended_at, seconds, pages_read FROM reading_sessions ORDER BY started_at DESC") { statement in
            ReaderSession(id: text(statement, 0), documentID: text(statement, 1), startedAt: sqlite3_column_double(statement, 2),
                          endedAt: optionalDouble(statement, 3), seconds: Int(sqlite3_column_int64(statement, 4)),
                          pagesRead: Int(sqlite3_column_int64(statement, 5)))
        }
    }

    func setPreference(key: String, value: String) throws {
        try execute(
            "INSERT INTO preferences(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [.text(key), .text(value)]
        )
    }

    func preference(key: String) throws -> String? {
        try queryOne("SELECT value FROM preferences WHERE key=?", [.text(key)]) { text($0, 0) }
    }

    func preferences() throws -> [String: String] {
        var result: [String: String] = [:]
        _ = try query("SELECT key, value FROM preferences ORDER BY key") { statement -> Bool in
            result[text(statement, 0)] = text(statement, 1)
            return true
        }
        return result
    }

    // MARK: Search

    func indexSearchItems(_ items: [ReaderSearchItem]) throws {
        guard !items.isEmpty else { return }
        try transaction {
            for item in items {
                try execute(
                    """
                    INSERT INTO search_items(id, document_id, kind, title, body, updated_at) VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET document_id=excluded.document_id, kind=excluded.kind,
                      title=excluded.title, body=excluded.body, updated_at=excluded.updated_at
                    """,
                    [.text(item.id), .text(item.documentID), .text(item.kind), .text(item.title), .text(item.body), .double(item.updatedAt)]
                )
                try execute("DELETE FROM search_items_fts WHERE id=?", [.text(item.id)])
                try execute(
                    "INSERT INTO search_items_fts(id, document_id, kind, title, body) VALUES(?, ?, ?, ?, ?)",
                    [.text(item.id), .text(item.documentID), .text(item.kind), .text(item.title), .text(item.body)]
                )
            }
        }
    }

    func search(_ value: String, limit: Int = 50) throws -> [ReaderSearchResult] {
        let tokens = value.split { !$0.isLetter && !$0.isNumber }.map(String.init).filter { !$0.isEmpty }
        guard !tokens.isEmpty else { return [] }
        let match = tokens.prefix(12).map { "\"\($0.replacingOccurrences(of: "\"", with: "\"\""))\"*" }.joined(separator: " AND ")
        return try query(
            """
            SELECT id, document_id, kind, title,
              snippet(search_items_fts, 4, '', '', ' … ', 24), bm25(search_items_fts)
            FROM search_items_fts WHERE search_items_fts MATCH ? ORDER BY bm25(search_items_fts) LIMIT ?
            """,
            [.text(match), .integer(Int64(min(max(limit, 1), 200)))]
        ) { statement in
            ReaderSearchResult(id: text(statement, 0), documentID: text(statement, 1), kind: text(statement, 2),
                               title: text(statement, 3), snippet: text(statement, 4), rank: sqlite3_column_double(statement, 5))
        }
    }

    // MARK: Export, import, backup, diagnostics

    func snapshot() throws -> ReaderExportSnapshot {
        ReaderExportSnapshot(
            formatVersion: Self.exportFormatVersion,
            exportedAt: Date().timeIntervalSince1970,
            documents: try documents(),
            positions: try query("SELECT document_id, locator_json, page, progress, updated_at FROM reading_positions ORDER BY document_id") {
                ReaderPosition(documentID: text($0, 0), locator: text($0, 1), page: optionalInt($0, 2),
                               progress: sqlite3_column_double($0, 3), updatedAt: sqlite3_column_double($0, 4))
            },
            bookmarks: try bookmarks(), annotations: try annotations(), sessions: try sessions(),
            preferences: try preferences(),
            searchItems: try query("SELECT id, document_id, kind, title, body, updated_at FROM search_items ORDER BY id") {
                ReaderSearchItem(id: text($0, 0), documentID: text($0, 1), kind: text($0, 2), title: text($0, 3),
                                 body: text($0, 4), updatedAt: sqlite3_column_double($0, 5))
            }
        )
    }

    func exportJSON(to url: URL) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        try encoder.encode(snapshot()).write(to: url, options: .atomic)
    }

    func exportMarkdown(to url: URL) throws {
        let documentsByID = Dictionary(uniqueKeysWithValues: try documents().map { ($0.id, $0) })
        let notes = try annotations()
        var lines = ["# Lattice Reading Notebook", "", "Exported \(ISO8601DateFormatter().string(from: Date()))", ""]
        for group in Dictionary(grouping: notes, by: \ReaderAnnotation.documentID).sorted(by: {
            (documentsByID[$0.key]?.title ?? $0.key) < (documentsByID[$1.key]?.title ?? $1.key)
        }) {
            let title = documentsByID[group.key]?.title ?? group.key
            lines += ["## \(title)", ""]
            for annotation in group.value.sorted(by: { $0.createdAt < $1.createdAt }) {
                if !annotation.quote.isEmpty { lines += ["> \(annotation.quote.replacingOccurrences(of: "\n", with: "\n> "))", ""] }
                if !annotation.note.isEmpty { lines += [annotation.note, ""] }
                lines += ["_\(annotation.locator) · \(ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: annotation.updatedAt)))_", ""]
            }
        }
        try (lines.joined(separator: "\n") + "\n").write(to: url, atomically: true, encoding: .utf8)
    }

    func importJSON(from url: URL) throws {
        let imported: ReaderExportSnapshot
        do { imported = try JSONDecoder().decode(ReaderExportSnapshot.self, from: Data(contentsOf: url)) }
        catch { throw ReaderStoreError.invalidImport(error.localizedDescription) }
        guard imported.formatVersion == Self.exportFormatVersion else {
            throw ReaderStoreError.invalidImport("Unsupported format version \(imported.formatVersion)")
        }
        try transaction {
            for document in imported.documents { try upsertDocument(document) }
            for position in imported.positions { try savePosition(position) }
            for bookmark in imported.bookmarks { try saveBookmark(bookmark) }
            for annotation in imported.annotations { try saveAnnotation(annotation) }
            for session in imported.sessions {
                try execute(
                    """
                    INSERT INTO reading_sessions(id, document_id, started_at, ended_at, seconds, pages_read)
                    VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET ended_at=excluded.ended_at,
                      seconds=excluded.seconds, pages_read=excluded.pages_read
                    """,
                    [.text(session.id), .text(session.documentID), .double(session.startedAt),
                     session.endedAt.map(SQLiteValue.double) ?? .null, .integer(Int64(session.seconds)), .integer(Int64(session.pagesRead))]
                )
            }
            for (key, value) in imported.preferences { try setPreference(key: key, value: value) }
            try indexSearchItems(imported.searchItems)
        }
    }

    func createBackupIfNeeded(force: Bool) throws {
        try withLock {
            let manager = FileManager.default
            let backups = try backupFiles()
            if !force, let newest = backups.last,
               Calendar.current.isDateInToday((try? newest.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate) ?? .distantPast) {
                return
            }
            let formatter = DateFormatter()
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.dateFormat = "yyyyMMdd-HHmmss"
            let destination = backupsDirectory.appendingPathComponent("Library-\(formatter.string(from: Date())).sqlite")
            var target: OpaquePointer?
            guard sqlite3_open_v2(destination.path, &target, SQLITE_OPEN_CREATE | SQLITE_OPEN_READWRITE, nil) == SQLITE_OK, let target else {
                if let target { sqlite3_close_v2(target) }
                throw ReaderStoreError.database("Could not create backup")
            }
            defer { sqlite3_close_v2(target) }
            guard let backup = sqlite3_backup_init(target, "main", requiredDatabase(), "main") else {
                throw ReaderStoreError.database(errorMessage(target))
            }
            let result = sqlite3_backup_step(backup, -1)
            let finishResult = sqlite3_backup_finish(backup)
            guard result == SQLITE_DONE, finishResult == SQLITE_OK else {
                try? manager.removeItem(at: destination)
                throw ReaderStoreError.database(errorMessage(target))
            }
            try? manager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: destination.path)
            let excess = max(0, (try backupFiles()).count - 14)
            for old in try backupFiles().prefix(excess) { try? manager.removeItem(at: old) }
        }
    }

    func diagnostics() throws -> ReaderDiagnostics {
        let backups = try backupFiles()
        let newestDate = backups.last.flatMap { try? $0.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate }?.timeIntervalSince1970
        return ReaderDiagnostics(
            databasePath: databaseURL.path,
            integrity: try queryOne("PRAGMA integrity_check") { text($0, 0) } ?? "unknown",
            schemaVersion: Int(try scalarInt("PRAGMA user_version")),
            documentCount: Int(try scalarInt("SELECT COUNT(*) FROM documents")),
            bookmarkCount: Int(try scalarInt("SELECT COUNT(*) FROM bookmarks")),
            annotationCount: Int(try scalarInt("SELECT COUNT(*) FROM annotations")),
            sessionCount: Int(try scalarInt("SELECT COUNT(*) FROM reading_sessions")),
            backupCount: backups.count,
            lastBackupAt: newestDate
        )
    }

    // MARK: Schema and SQLite plumbing

    private func migrate() throws {
        let version = Int(try scalarInt("PRAGMA user_version"))
        guard version <= Self.currentSchemaVersion else {
            throw ReaderStoreError.database("Database schema \(version) is newer than this app supports")
        }
        if version < 1 {
            try transaction {
                try execute("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL)")
                try execute("CREATE TABLE documents(id TEXT PRIMARY KEY, work_id TEXT, path TEXT NOT NULL, sha256 TEXT, title TEXT NOT NULL, format TEXT NOT NULL, updated_at REAL NOT NULL)")
                try execute("CREATE TABLE reading_positions(document_id TEXT PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE, locator_json TEXT NOT NULL, page INTEGER, progress REAL NOT NULL, updated_at REAL NOT NULL)")
                try execute("CREATE TABLE bookmarks(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, locator_json TEXT NOT NULL, label TEXT NOT NULL, created_at REAL NOT NULL)")
                try execute("CREATE INDEX bookmarks_document ON bookmarks(document_id, created_at)")
                try execute("CREATE TABLE annotations(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, locator_json TEXT NOT NULL, quote TEXT NOT NULL, note TEXT NOT NULL, color TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)")
                try execute("CREATE INDEX annotations_document ON annotations(document_id, updated_at)")
                try execute("CREATE TABLE reading_sessions(id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE, started_at REAL NOT NULL, ended_at REAL, seconds INTEGER NOT NULL DEFAULT 0, pages_read INTEGER NOT NULL DEFAULT 0)")
                try execute("CREATE TABLE preferences(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                try execute("CREATE TABLE search_items(id TEXT PRIMARY KEY, document_id TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, updated_at REAL NOT NULL)")
                try execute("CREATE VIRTUAL TABLE search_items_fts USING fts5(id UNINDEXED, document_id UNINDEXED, kind UNINDEXED, title, body, tokenize='unicode61')")
                try execute("INSERT OR REPLACE INTO schema_migrations(version, applied_at) VALUES(1, ?)", [.double(Date().timeIntervalSince1970)])
                try execute("PRAGMA user_version=1")
            }
        }
    }

    private func transaction<T>(_ body: () throws -> T) throws -> T {
        try withLock {
            if transactionDepth > 0 {
                transactionDepth += 1
                defer { transactionDepth -= 1 }
                return try body()
            }
            try execute("BEGIN IMMEDIATE")
            transactionDepth = 1
            do {
                let value = try body()
                try execute("COMMIT")
                transactionDepth = 0
                return value
            } catch {
                _ = try? execute("ROLLBACK")
                transactionDepth = 0
                throw error
            }
        }
    }

    @discardableResult
    private func execute(_ sql: String, _ values: [SQLiteValue] = []) throws -> Int32 {
        try withLock {
            let statement = try prepare(sql)
            defer { sqlite3_finalize(statement) }
            try bind(values, to: statement)
            let result = sqlite3_step(statement)
            guard result == SQLITE_DONE || result == SQLITE_ROW else { throw ReaderStoreError.database(errorMessage(requiredDatabase())) }
            return result
        }
    }

    private func query<T>(_ sql: String, _ values: [SQLiteValue] = [], map: (OpaquePointer) throws -> T) throws -> [T] {
        try withLock {
            let statement = try prepare(sql)
            defer { sqlite3_finalize(statement) }
            try bind(values, to: statement)
            var result: [T] = []
            while true {
                let code = sqlite3_step(statement)
                if code == SQLITE_DONE { return result }
                guard code == SQLITE_ROW else { throw ReaderStoreError.database(errorMessage(requiredDatabase())) }
                result.append(try map(statement))
            }
        }
    }

    private func queryOne<T>(_ sql: String, _ values: [SQLiteValue] = [], map: (OpaquePointer) throws -> T) throws -> T? {
        try query(sql, values, map: map).first
    }

    private func prepare(_ sql: String) throws -> OpaquePointer {
        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(requiredDatabase(), sql, -1, &statement, nil) == SQLITE_OK, let statement else {
            throw ReaderStoreError.database(errorMessage(requiredDatabase()))
        }
        return statement
    }

    private func bind(_ values: [SQLiteValue], to statement: OpaquePointer) throws {
        for (offset, value) in values.enumerated() {
            let index = Int32(offset + 1)
            let code: Int32
            switch value {
            case .text(let string): code = sqlite3_bind_text(statement, index, string, -1, transient)
            case .integer(let integer): code = sqlite3_bind_int64(statement, index, integer)
            case .double(let double): code = sqlite3_bind_double(statement, index, double)
            case .null: code = sqlite3_bind_null(statement, index)
            }
            guard code == SQLITE_OK else { throw ReaderStoreError.database(errorMessage(requiredDatabase())) }
        }
    }

    private func scalarInt(_ sql: String) throws -> Int64 {
        try queryOne(sql) { sqlite3_column_int64($0, 0) } ?? 0
    }

    private func backupFiles() throws -> [URL] {
        try FileManager.default.contentsOfDirectory(at: backupsDirectory, includingPropertiesForKeys: [.contentModificationDateKey])
            .filter { $0.pathExtension == "sqlite" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    private func requiredDatabase() -> OpaquePointer {
        precondition(database != nil, "ReaderStore used after database closed")
        return database!
    }

    private func errorMessage(_ connection: OpaquePointer) -> String { String(cString: sqlite3_errmsg(connection)) }
    private func withLock<T>(_ body: () throws -> T) rethrows -> T { lock.lock(); defer { lock.unlock() }; return try body() }
    private func optionalText(_ value: String?) -> SQLiteValue { value.map(SQLiteValue.text) ?? .null }
    private func optionalInteger(_ value: Int?) -> SQLiteValue { value.map { .integer(Int64($0)) } ?? .null }
    private func clamp(_ value: Double) -> Double { min(max(value, 0), 1) }
}

private func text(_ statement: OpaquePointer, _ column: Int32) -> String {
    guard let value = sqlite3_column_text(statement, column) else { return "" }
    return String(cString: value)
}

private func optionalColumnText(_ statement: OpaquePointer, _ column: Int32) -> String? {
    sqlite3_column_type(statement, column) == SQLITE_NULL ? nil : text(statement, column)
}

private func optionalInt(_ statement: OpaquePointer, _ column: Int32) -> Int? {
    sqlite3_column_type(statement, column) == SQLITE_NULL ? nil : Int(sqlite3_column_int64(statement, column))
}

private func optionalDouble(_ statement: OpaquePointer, _ column: Int32) -> Double? {
    sqlite3_column_type(statement, column) == SQLITE_NULL ? nil : sqlite3_column_double(statement, column)
}
