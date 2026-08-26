import AppKit
import Foundation
import PDFKit
import WebKit

final class ImmersiveReaderCoordinator {
    private weak var window: NSWindow?
    private weak var rootView: NSView?
    private weak var webView: WKWebView?
    private let libraryRoot: URL
    private let store: ReaderStore
    private var pdfReader: NativePDFReaderController?

    init(window: NSWindow, rootView: NSView, webView: WKWebView, libraryRoot: URL, store: ReaderStore) {
        self.window = window
        self.rootView = rootView
        self.webView = webView
        self.libraryRoot = libraryRoot
        self.store = store
    }

    static func epubUserScript(libraryRoot: URL) -> WKUserScript? {
        let scriptURL = Bundle.main.url(forResource: "ImmersiveEPUB", withExtension: "js")
            ?? libraryRoot.appendingPathComponent("native/ImmersiveEPUB.js")
        guard let source = try? String(contentsOf: scriptURL, encoding: .utf8) else { return nil }
        return WKUserScript(source: source, injectionTime: .atDocumentEnd, forMainFrameOnly: false)
    }

    var isPDFOpen: Bool {
        pdfReader != nil
    }

    @discardableResult
    func openPDFIfNeeded(for url: URL) -> Bool {
        guard
            let fileURL = localPDFURL(from: url),
            let window,
            let rootView,
            let webView
        else { return false }

        webView.evaluateJavaScript("document.querySelector('#readerTitle')?.textContent || ''") { [weak self] value, _ in
            guard let self else { return }
            let rawTitle = (value as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            let title = rawTitle.isEmpty ? fileURL.deletingPathExtension().lastPathComponent : rawTitle
            guard let relativePath = LibraryIdentity.relativePath(for: fileURL, root: self.libraryRoot) else { return }
            let previous = try? self.store.document(path: relativePath)
            let fallbackRecord = ReaderDocument(
                id: LibraryIdentity.documentID(workID: previous?.workID, path: relativePath, sha256: previous?.sha256),
                workID: previous?.workID,
                path: relativePath,
                sha256: previous?.sha256,
                title: title,
                format: "pdf",
                updatedAt: Date().timeIntervalSince1970
            )
            try? self.store.migrateLegacyDocuments(to: fallbackRecord)
            let record = (try? self.store.document(id: fallbackRecord.id)) ?? fallbackRecord
            try? self.store.upsertDocument(record)
            self.pdfReader?.close(notifyWeb: false)
            let reader = NativePDFReaderController(
                window: window,
                rootView: rootView,
                webView: webView,
                libraryRoot: self.libraryRoot,
                fileURL: fileURL,
                title: title,
                store: self.store,
                documentRecord: record
            )
            reader.onClose = { [weak self] in
                self?.pdfReader = nil
            }
            self.pdfReader = reader
            reader.present()
        }
        return true
    }

    @discardableResult
    func openDocument(relativePath: String) -> Bool {
        guard let file = LibraryIdentity.resolveLibraryFile(relativePath: relativePath, root: libraryRoot) else { return false }
        guard file.pathExtension.lowercased() == "pdf" else { return false }
        let encoded = relativePath.split(separator: "/").map {
            String($0).addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? String($0)
        }.joined(separator: "/")
        guard let url = URL(string: "http://127.0.0.1/content/\(encoded)") else { return false }
        return openPDFIfNeeded(for: url)
    }

    func closePDF(notifyWeb: Bool) {
        pdfReader?.close(notifyWeb: notifyWeb)
        pdfReader = nil
    }

    func handleKeyEvent(_ event: NSEvent) -> NSEvent? {
        pdfReader?.handleKeyEvent(event) ?? event
    }

    @discardableResult
    func previousPage() -> Bool {
        guard let pdfReader else { return false }
        pdfReader.previousPage()
        return true
    }

    @discardableResult
    func nextPage() -> Bool {
        guard let pdfReader else { return false }
        pdfReader.nextPage()
        return true
    }

    @discardableResult
    func toggleFocus() -> Bool {
        guard let pdfReader else { return false }
        pdfReader.toggleFocus()
        return true
    }

    @discardableResult
    func toggleSidebar() -> Bool {
        guard let pdfReader else { return false }
        pdfReader.toggleSidebar()
        return true
    }

    @discardableResult
    func toggleBookmark() -> Bool {
        guard let pdfReader else { return false }
        pdfReader.toggleBookmark()
        return true
    }

    @discardableResult
    func focusSearch() -> Bool {
        guard let pdfReader else { return false }
        pdfReader.focusSearch()
        return true
    }

    @discardableResult
    func addHighlight() -> Bool {
        guard let pdfReader else { return false }
        return pdfReader.addHighlight()
    }

    private func localPDFURL(from url: URL) -> URL? {
        guard isLocalLibraryURL(url), url.path.hasPrefix("/content/") else { return nil }
        let encodedRelative = String(url.path.dropFirst("/content/".count))
        let relative = encodedRelative.removingPercentEncoding ?? encodedRelative
        guard let candidate = LibraryIdentity.resolveLibraryFile(relativePath: relative, root: libraryRoot),
              candidate.pathExtension.lowercased() == "pdf" else { return nil }
        return candidate
    }

    private func isLocalLibraryURL(_ url: URL) -> Bool {
        guard let host = url.host?.lowercased() else { return false }
        return (host == "127.0.0.1" || host == "localhost" || host == "::1")
            && (url.scheme == "http" || url.scheme == "https")
    }
}
