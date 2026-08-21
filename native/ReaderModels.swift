import Foundation

struct ReaderDocument: Codable, Equatable {
    var id: String
    var workID: String?
    var path: String
    var sha256: String?
    var title: String
    var format: String
    var updatedAt: Double
}

struct ReaderPosition: Codable, Equatable {
    var documentID: String
    var locator: String
    var page: Int?
    var progress: Double
    var updatedAt: Double
}

struct ReaderBookmark: Codable, Equatable {
    var id: String
    var documentID: String
    var locator: String
    var label: String
    var createdAt: Double
}

struct ReaderAnnotation: Codable, Equatable {
    var id: String
    var documentID: String
    var locator: String
    var quote: String
    var note: String
    var color: String
    var createdAt: Double
    var updatedAt: Double
}

struct ReaderSession: Codable, Equatable {
    var id: String
    var documentID: String
    var startedAt: Double
    var endedAt: Double?
    var seconds: Int
    var pagesRead: Int
}

struct ReaderSearchItem: Codable, Equatable {
    var id: String
    var documentID: String
    var kind: String
    var title: String
    var body: String
    var updatedAt: Double
}

struct ReaderSearchResult: Codable, Equatable {
    var id: String
    var documentID: String
    var kind: String
    var title: String
    var snippet: String
    var rank: Double
}

struct ReaderDiagnostics: Codable, Equatable {
    var databasePath: String
    var integrity: String
    var schemaVersion: Int
    var documentCount: Int
    var bookmarkCount: Int
    var annotationCount: Int
    var sessionCount: Int
    var backupCount: Int
    var lastBackupAt: Double?
}

struct ReaderExportSnapshot: Codable, Equatable {
    var formatVersion: Int
    var exportedAt: Double
    var documents: [ReaderDocument]
    var positions: [ReaderPosition]
    var bookmarks: [ReaderBookmark]
    var annotations: [ReaderAnnotation]
    var sessions: [ReaderSession]
    var preferences: [String: String]
    var searchItems: [ReaderSearchItem]
}
