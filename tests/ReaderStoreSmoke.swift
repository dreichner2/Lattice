import Foundation

@main
struct ReaderStoreSmoke {
    static func main() throws {
        let temporary = FileManager.default.temporaryDirectory
            .appendingPathComponent("cs-library-store-smoke-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: temporary) }

        let libraryRoot = temporary.appendingPathComponent("Library", isDirectory: true)
        let books = libraryRoot.appendingPathComponent("books", isDirectory: true)
        try FileManager.default.createDirectory(at: books, withIntermediateDirectories: true)
        let readable = books.appendingPathComponent("fixture.pdf")
        try Data("%PDF-1.1\n%%EOF\n".utf8).write(to: readable)
        precondition(LibraryIdentity.resolveLibraryFile(relativePath: "books/fixture.pdf", root: libraryRoot) == readable.resolvingSymlinksInPath())
        let outside = temporary.appendingPathComponent("outside.pdf")
        try Data("%PDF-1.1\n%%EOF\n".utf8).write(to: outside)
        let linked = books.appendingPathComponent("linked.pdf")
        try FileManager.default.createSymbolicLink(at: linked, withDestinationURL: outside)
        precondition(LibraryIdentity.resolveLibraryFile(relativePath: "books/linked.pdf", root: libraryRoot) == nil)
        precondition(LibraryIdentity.resolveLibraryFile(relativePath: "../outside.pdf", root: libraryRoot) == nil)

        let store = try ReaderStore(dataDirectory: temporary.appendingPathComponent("ReaderData", isDirectory: true))
        let now = Date().timeIntervalSince1970
        let document = ReaderDocument(
            id: LibraryIdentity.documentID(workID: "fixture", path: "books/fixture.pdf", sha256: "abc"),
            workID: "fixture", path: "books/fixture.pdf", sha256: "abc", title: "Fixture", format: "pdf", updatedAt: now
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

        let exportURL = temporary.appendingPathComponent("ReaderData.json")
        try store.exportJSON(to: exportURL)
        let importDirectory = temporary.appendingPathComponent("Imported", isDirectory: true)
        let imported = try ReaderStore(dataDirectory: importDirectory)
        try imported.importJSON(from: exportURL)
        let importedDocuments = try imported.documents()
        let importedAnnotations = try imported.annotations(documentID: document.id)
        let importedSessions = try imported.sessions()
        let importedPreference = try imported.preference(key: "pdf.mode.\(document.id)")
        precondition(importedDocuments == [document])
        precondition(importedAnnotations.count == 1)
        precondition(importedSessions.first?.pagesRead == 2)
        precondition(importedPreference == "continuous")

        print("ReaderStore smoke test passed")
    }
}
