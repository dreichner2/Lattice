import AppKit
import Foundation
import SQLite3

final class ReaderDataStore {
    static let shared = ReaderDataStore()

    private let queue = DispatchQueue(label: "com.danny.cslibrary.reader-data")
    private var database: OpaquePointer?
    private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

    private init() {
        queue.sync {
            openDatabase()
            migrate()
        }
    }

    deinit {
        if let database {
            sqlite3_close(database)
        }
    }

    var databaseURL: URL {
        let base = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0]
        return base
            .appendingPathComponent("CS Library", isDirectory: true)
            .appendingPathComponent("reader-state.sqlite3", isDirectory: false)
    }

    private func openDatabase() {
        let url = databaseURL
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        guard sqlite3_open_v2(
            url.path,
            &database,
            SQLITE_OPEN_CREATE | SQLITE_OPEN_READWRITE | SQLITE_OPEN_FULLMUTEX,
            nil
        ) == SQLITE_OK else {
            database = nil
            return
        }
        execute("PRAGMA journal_mode=WAL")
        execute("PRAGMA synchronous=NORMAL")
        execute("PRAGMA busy_timeout=8000")
    }

    private func migrate() {
        execute(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        execute(
            """
            CREATE TABLE IF NOT EXISTS kv_state (
                namespace TEXT NOT NULL,
                state_key TEXT NOT NULL,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (namespace, state_key)
            )
            """
        )
        execute(
            """
            CREATE TABLE IF NOT EXISTS reading_sessions (
                id TEXT PRIMARY KEY,
                work_id TEXT NOT NULL DEFAULT '',
                material_path TEXT NOT NULL DEFAULT '',
                started_at REAL NOT NULL,
                ended_at REAL,
                active_seconds REAL NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        execute(
            """
            INSERT INTO schema_meta(key, value) VALUES('schema_version', '1')
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """
        )
    }

    private func execute(_ sql: String) {
        guard let database else { return }
        sqlite3_exec(database, sql, nil, nil, nil)
    }

    private func stateValue(namespace: String, key: String) -> String? {
        guard let database else { return nil }
        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(
            database,
            "SELECT value FROM kv_state WHERE namespace=? AND state_key=?",
            -1,
            &statement,
            nil
        ) == SQLITE_OK else { return nil }
        sqlite3_bind_text(statement, 1, namespace, -1, transient)
        sqlite3_bind_text(statement, 2, key, -1, transient)
        guard sqlite3_step(statement) == SQLITE_ROW,
              let bytes = sqlite3_column_text(statement, 0)
        else { return nil }
        return String(cString: bytes)
    }

    private func setStateValue(namespace: String, key: String, value: String) {
        guard let database else { return }
        var statement: OpaquePointer?
        defer { sqlite3_finalize(statement) }
        guard sqlite3_prepare_v2(
            database,
            """
            INSERT INTO kv_state(namespace, state_key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, state_key)
            DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
            """,
            -1,
            &statement,
            nil
        ) == SQLITE_OK else { return }
        sqlite3_bind_text(statement, 1, namespace, -1, transient)
        sqlite3_bind_text(statement, 2, key, -1, transient)
        sqlite3_bind_text(statement, 3, value, -1, transient)
        sqlite3_bind_double(statement, 4, Date().timeIntervalSince1970)
        sqlite3_step(statement)
    }

    func preparePDFState(identifier: String) {
        guard !identifier.isEmpty else { return }
        queue.sync {
            guard let raw = stateValue(namespace: "pdf", key: identifier),
                  let data = raw.data(using: .utf8),
                  let values = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            else { return }
            let defaults = UserDefaults.standard
            let prefix = "cs-library.pdf.\(identifier)."
            values.forEach { suffix, value in
                defaults.set(value, forKey: prefix + suffix)
            }
        }
    }

    func capturePDFState(identifier: String) {
        guard !identifier.isEmpty else { return }
        let defaults = UserDefaults.standard
        let prefix = "cs-library.pdf.\(identifier)."
        let suffixes = [
            "page",
            "auto-scale",
            "scale",
            "display-mode",
            "sidebar",
            "bookmarks",
            "notes",
        ]
        var values: [String: Any] = [:]
        suffixes.forEach { suffix in
            if let value = defaults.object(forKey: prefix + suffix) {
                values[suffix] = value
            }
        }
        queue.async { [weak self] in
            guard let self,
                  JSONSerialization.isValidJSONObject(values),
                  let data = try? JSONSerialization.data(withJSONObject: values),
                  let raw = String(data: data, encoding: .utf8)
            else { return }
            self.setStateValue(namespace: "pdf", key: identifier, value: raw)
        }
    }

    func export(to destination: URL) throws {
        let payload: [String: Any] = try queue.sync {
            guard let database else {
                throw CocoaError(.fileReadUnknown)
            }
            var statement: OpaquePointer?
            defer { sqlite3_finalize(statement) }
            guard sqlite3_prepare_v2(
                database,
                "SELECT namespace, state_key, value, updated_at FROM kv_state ORDER BY namespace, state_key",
                -1,
                &statement,
                nil
            ) == SQLITE_OK else {
                throw CocoaError(.fileReadCorruptFile)
            }
            var states: [[String: Any]] = []
            while sqlite3_step(statement) == SQLITE_ROW {
                guard let namespaceBytes = sqlite3_column_text(statement, 0),
                      let keyBytes = sqlite3_column_text(statement, 1),
                      let valueBytes = sqlite3_column_text(statement, 2)
                else { continue }
                states.append([
                    "namespace": String(cString: namespaceBytes),
                    "state_key": String(cString: keyBytes),
                    "value": String(cString: valueBytes),
                    "updated_at": sqlite3_column_double(statement, 3),
                ])
            }
            return [
                "application": "CS Library",
                "schemaVersion": 1,
                "exportedAt": ISO8601DateFormatter().string(from: Date()),
                "states": states,
            ]
        }
        let data = try JSONSerialization.data(
            withJSONObject: payload,
            options: [.prettyPrinted, .sortedKeys]
        )
        try data.write(to: destination, options: .atomic)
    }

    func importData(from source: URL, replace: Bool = false) throws {
        let data = try Data(contentsOf: source)
        guard let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let states = payload["states"] as? [[String: Any]]
        else {
            throw CocoaError(.fileReadCorruptFile)
        }
        try queue.sync {
            guard let database else { throw CocoaError(.fileWriteUnknown) }
            execute("BEGIN IMMEDIATE")
            if replace { execute("DELETE FROM kv_state") }
            for record in states {
                guard let namespace = record["namespace"] as? String,
                      let key = (record["state_key"] ?? record["key"]) as? String,
                      let value = record["value"] as? String,
                      !namespace.isEmpty,
                      !key.isEmpty
                else { continue }
                setStateValue(namespace: namespace, key: key, value: value)
            }
            if sqlite3_exec(database, "COMMIT", nil, nil, nil) != SQLITE_OK {
                execute("ROLLBACK")
                throw CocoaError(.fileWriteUnknown)
            }
        }
    }
}
