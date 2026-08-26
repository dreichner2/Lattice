import Foundation

@main
struct ReaderStoreSmoke {
    static func main() throws {
        let trustedOrigin = URL(string: "http://127.0.0.1:8766/library")!
        precondition(LibraryIdentity.sameHTTPOrigin(
            trustedOrigin,
            URL(string: "http://127.0.0.1:8766/study-lab.html")
        ))
        precondition(!LibraryIdentity.sameHTTPOrigin(
            trustedOrigin,
            URL(string: "http://127.0.0.1:8767/")
        ))
        precondition(!LibraryIdentity.sameHTTPOrigin(
            trustedOrigin,
            URL(string: "http://localhost:8766/")
        ))
        precondition(LibraryIdentity.sameHTTPOrigin(
            URL(string: "http://127.0.0.1/"),
            URL(string: "http://127.0.0.1:80/")
        ))

        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent("cs-library-store-smoke-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }

        let libraryRoot = temporary.appendingPathComponent("Library", isDirectory: true)
        let books = libraryRoot.appendingPathComponent("books", isDirectory: true)
        try FileManager.default.createDirectory(at: books, withIntermediateDirectories: true)
        let readable = books.appendingPathComponent("fixture.pdf")
        try Data("%PDF-1.1\n%%EOF\n".utf8).write(to: readable)
        precondition(LibraryIdentity.resolveLibraryFile(relativePath: "books/fixture.pdf", root: libraryRoot) == readable.resolvingSymlinksInPath())
        let lectures = libraryRoot.appendingPathComponent("lectures", isDirectory: true)
        try FileManager.default.createDirectory(at: lectures, withIntermediateDirectories: true)
        for (name, contents) in [
            ("session.pdf", "%PDF-1.1\n%%EOF\n"),
            ("session.epub", "fixture epub"),
            ("session.txt", "fixture transcript"),
        ] {
            let lecture = lectures.appendingPathComponent(name)
            try Data(contents.utf8).write(to: lecture)
            let relative = "lectures/\(name)"
            precondition(LibraryIdentity.isReadableRelativePath(relative))
            precondition(LibraryIdentity.resolveLibraryFile(relativePath: relative, root: libraryRoot) == lecture.resolvingSymlinksInPath())
            precondition(LibraryIdentity.relativePath(for: lecture, root: libraryRoot) == relative)
        }
        precondition(!LibraryIdentity.isReadableRelativePath("lectures/session.html"))
        precondition(!LibraryIdentity.isReadableRelativePath("lectures/../outside.pdf"))
        let audio = libraryRoot.appendingPathComponent("audio", isDirectory: true)
        try FileManager.default.createDirectory(at: audio, withIntermediateDirectories: true)
        for name in ["session.mp3", "session.m4a", "session.wav", "session.flac"] {
            let recording = audio.appendingPathComponent(name)
            try Data("audio fixture".utf8).write(to: recording)
            let relative = "audio/\(name)"
            precondition(!LibraryIdentity.isReadableRelativePath(relative))
            precondition(LibraryIdentity.isLibraryPayloadRelativePath(relative))
            precondition(LibraryIdentity.resolveLibraryPayload(relativePath: relative, root: libraryRoot) == recording.resolvingSymlinksInPath())
            precondition(LibraryIdentity.relativePayloadPath(for: recording, root: libraryRoot) == relative)
        }
        precondition(!LibraryIdentity.isLibraryPayloadRelativePath("books/session.mp3"))
        precondition(!LibraryIdentity.isLibraryPayloadRelativePath("audio/session.pdf"))
        let outside = temporary.appendingPathComponent("outside.pdf")
        try Data("%PDF-1.1\n%%EOF\n".utf8).write(to: outside)
        let linked = books.appendingPathComponent("linked.pdf")
        try FileManager.default.createSymbolicLink(at: linked, withDestinationURL: outside)
        precondition(LibraryIdentity.resolveLibraryFile(relativePath: "books/linked.pdf", root: libraryRoot) == nil)
        precondition(LibraryIdentity.resolveLibraryFile(relativePath: "../outside.pdf", root: libraryRoot) == nil)

        let store = try ReaderStore(dataDirectory: temporary.appendingPathComponent("ReaderData", isDirectory: true))
        let now = Date().timeIntervalSince1970
        let fixtureDigest = String(repeating: "a", count: 64)
        precondition(
            LibraryIdentity.documentID(workID: "fixture", path: "books/fixture.pdf", sha256: fixtureDigest)
                != LibraryIdentity.documentID(workID: "fixture", path: "books/fixture.epub", sha256: String(repeating: "b", count: 64))
        )
        let document = ReaderDocument(
            id: LibraryIdentity.documentID(workID: "fixture", path: "books/fixture.pdf", sha256: fixtureDigest),
            workID: "fixture", path: "books/fixture.pdf", sha256: fixtureDigest, title: "Fixture", format: "pdf", updatedAt: now
        )
        try store.upsertDocument(document)
        try store.savePosition(ReaderPosition(documentID: document.id, locator: "{\"page\":4}", page: 4, progress: 0.5, updatedAt: now))
        try store.saveBookmark(ReaderBookmark(id: "bookmark-1", documentID: document.id, locator: "{\"page\":4}", label: "Page 5", createdAt: now))
        try store.saveAnnotation(ReaderAnnotation(id: "note-1", documentID: document.id, locator: "{\"page\":4}", quote: "durable state", note: "Remember this", color: "yellow", createdAt: now, updatedAt: now))
        let session = try store.startSession(documentID: document.id, at: now - 30)
        try store.finishSession(id: session.id, pagesRead: 2, at: now)
        try store.setPreference(key: "pdf.mode.\(document.id)", value: "continuous")

        let savedPosition = try store.position(documentID: document.id)
        let savedBookmarks = try store.bookmarks(documentID: document.id)
        let savedAnnotations = try store.annotations(documentID: document.id)
        let searchResults = try store.search("remember")
        let diagnostics = try store.diagnostics()
        precondition(savedPosition?.page == 4)
        precondition(savedBookmarks.count == 1)
        precondition(savedAnnotations.count == 1)
        precondition(searchResults.first?.id == "annotation:note-1")
        precondition(diagnostics.integrity == "ok")

        let legacyPath = "books/legacy.pdf"
        let legacyWorkID = "multi-format-work"
        let legacy = ReaderDocument(
            id: LibraryIdentity.legacyWorkDocumentID(workID: legacyWorkID)!, workID: legacyWorkID, path: legacyPath, sha256: nil,
            title: "Legacy Fixture", format: "pdf", updatedAt: now - 10
        )
        try store.upsertDocument(legacy)
        try store.savePosition(ReaderPosition(
            documentID: legacy.id, locator: "{\"page\":3,\"type\":\"pdf\"}", page: 3,
            progress: 0.4, updatedAt: now - 5
        ))
        try store.saveBookmark(ReaderBookmark(
            id: "pdf-bookmark:\(legacy.id):3", documentID: legacy.id,
            locator: "{\"page\":3,\"type\":\"pdf\"}", label: "Page 4", createdAt: now - 5
        ))
        try store.saveAnnotation(ReaderAnnotation(
            id: "pdf-note:\(legacy.id):3", documentID: legacy.id,
            locator: "{\"page\":3,\"type\":\"pdf\"}", quote: "", note: "Legacy page note",
            color: "note", createdAt: now - 5, updatedAt: now - 5
        ))
        try store.saveAnnotation(ReaderAnnotation(
            id: "web-note", documentID: legacy.id,
            locator: "{\"page\":7,\"type\":\"pdf\"}", quote: "shared", note: "Already one based",
            color: "yellow", createdAt: now - 4, updatedAt: now - 4
        ))
        try store.saveBookmark(ReaderBookmark(
            id: "legacy-epub-bookmark", documentID: legacy.id,
            locator: "{\"entry\":\"chapter.xhtml\",\"ratio\":0.5,\"type\":\"epub\"}",
            label: "EPUB midpoint", createdAt: now - 3
        ))
        try store.saveAnnotation(ReaderAnnotation(
            id: "legacy-epub-note", documentID: legacy.id,
            locator: "{\"entry\":\"chapter.xhtml\",\"ratio\":0.5,\"type\":\"epub\"}",
            quote: "epub", note: "Keep with the EPUB", color: "yellow",
            createdAt: now - 3, updatedAt: now - 3
        ))
        try store.setPreference(key: "pdf.\(legacy.id).display-mode", value: "page")

        let migrated = ReaderDocument(
            id: LibraryIdentity.documentID(workID: legacy.workID, path: legacyPath, sha256: String(repeating: "c", count: 64)),
            workID: legacy.workID, path: legacyPath, sha256: String(repeating: "c", count: 64),
            title: legacy.title, format: legacy.format, updatedAt: now
        )
        try store.migrateLegacyDocuments(to: migrated)
        let migratedPosition = try store.position(documentID: migrated.id)
        let migratedBookmarks = try store.bookmarks(documentID: migrated.id)
        let migratedAnnotations = try store.annotations(documentID: migrated.id)
        let removedLegacyDocument = try store.document(id: legacy.id)
        let retainedLegacyBookmarks = try store.bookmarks(documentID: legacy.id)
        let retainedLegacyAnnotations = try store.annotations(documentID: legacy.id)
        let migratedDisplayMode = try store.preference(key: "pdf.\(migrated.id).display-mode")
        precondition(removedLegacyDocument != nil)
        precondition(migratedPosition?.page == 4)
        precondition(migratedPosition?.locator.contains("\"page\":4") == true)
        precondition(migratedPosition?.locator.contains("\"pageBase\":1") == true)
        precondition(migratedBookmarks.first?.locator.contains("\"page\":4") == true)
        precondition(migratedAnnotations.first(where: { $0.id.hasPrefix("pdf-note:") })?.locator.contains("\"page\":4") == true)
        precondition(migratedAnnotations.first(where: { $0.id == "web-note" })?.locator.contains("\"page\":7") == true)
        precondition(retainedLegacyBookmarks.map(\.id) == ["legacy-epub-bookmark"])
        precondition(retainedLegacyAnnotations.map(\.id) == ["legacy-epub-note"])
        precondition(migratedDisplayMode == "page")
        try store.migrateLegacyDocuments(to: migrated)
        let idempotentBookmarks = try store.bookmarks(documentID: migrated.id)
        precondition(idempotentBookmarks.count == migratedBookmarks.count)

        let migratedEpub = ReaderDocument(
            id: LibraryIdentity.documentID(
                workID: legacy.workID,
                path: "books/legacy.epub",
                sha256: String(repeating: "f", count: 64)
            ),
            workID: legacy.workID, path: "books/legacy.epub", sha256: String(repeating: "f", count: 64),
            title: legacy.title, format: "epub", updatedAt: now + 1
        )
        try store.migrateLegacyDocuments(to: migratedEpub)
        let migratedEpubBookmarks = try store.bookmarks(documentID: migratedEpub.id)
        let migratedEpubAnnotations = try store.annotations(documentID: migratedEpub.id)
        let fullyRemovedLegacyDocument = try store.document(id: legacy.id)
        precondition(migratedEpubBookmarks.map(\.id) == ["legacy-epub-bookmark"])
        precondition(migratedEpubAnnotations.map(\.id) == ["legacy-epub-note"])
        precondition(fullyRemovedLegacyDocument == nil)
        try store.migrateLegacyDocuments(to: migratedEpub)
        let idempotentEpubBookmarks = try store.bookmarks(documentID: migratedEpub.id)
        precondition(idempotentEpubBookmarks.count == migratedEpubBookmarks.count)

        let changedPath = "books/changed.pdf"
        let oldEdition = ReaderDocument(
            id: LibraryIdentity.documentID(workID: "changed", path: changedPath, sha256: String(repeating: "d", count: 64)),
            workID: "changed", path: changedPath, sha256: String(repeating: "d", count: 64),
            title: "Changed", format: "pdf", updatedAt: now - 2
        )
        try store.upsertDocument(oldEdition)
        try store.saveAnnotation(ReaderAnnotation(
            id: "old-edition-note", documentID: oldEdition.id,
            locator: "{\"page\":2,\"type\":\"pdf\"}", quote: "old", note: "Old edition only",
            color: "yellow", createdAt: now - 2, updatedAt: now - 2
        ))
        let newEdition = ReaderDocument(
            id: LibraryIdentity.documentID(workID: "changed", path: changedPath, sha256: String(repeating: "e", count: 64)),
            workID: "changed", path: changedPath, sha256: String(repeating: "e", count: 64),
            title: "Changed", format: "pdf", updatedAt: now
        )
        try store.migrateLegacyDocuments(to: newEdition)
        try store.upsertDocument(newEdition)
        let oldEditionAnnotations = try store.annotations(documentID: oldEdition.id)
        let newEditionAnnotations = try store.annotations(documentID: newEdition.id)
        precondition(oldEditionAnnotations.map(\.id) == ["old-edition-note"])
        precondition(newEditionAnnotations.isEmpty)

        let expectedDocumentIDs = Set(try store.documents().map(\.id))
        let exportURL = temporary.appendingPathComponent("ReaderData.json")
        try store.exportJSON(to: exportURL)
        let importDirectory = temporary.appendingPathComponent("Imported", isDirectory: true)
        let imported = try ReaderStore(dataDirectory: importDirectory)
        try imported.importJSON(from: exportURL)
        let importedDocuments = try imported.documents()
        let importedAnnotations = try imported.annotations(documentID: document.id)
        let importedSessions = try imported.sessions()
        let importedPreference = try imported.preference(key: "pdf.mode.\(document.id)")
        precondition(Set(importedDocuments.map(\.id)) == expectedDocumentIDs)
        precondition(importedAnnotations.count == 1)
        precondition(importedSessions.first?.pagesRead == 2)
        precondition(importedPreference == "continuous")

        print("ReaderStore smoke test passed")
    }
}
