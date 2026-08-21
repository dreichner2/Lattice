import AppKit
import Foundation
import PDFKit
import WebKit

final class ImmersiveReaderCoordinator {
    private weak var window: NSWindow?
    private weak var rootView: NSView?
    private weak var webView: WKWebView?
    private let libraryRoot: URL
    private var pdfReader: NativePDFReaderController?

    init(window: NSWindow, rootView: NSView, webView: WKWebView, libraryRoot: URL) {
        self.window = window
        self.rootView = rootView
        self.webView = webView
        self.libraryRoot = libraryRoot
    }

    static func userScripts(libraryRoot: URL) -> [WKUserScript] {
        let specifications: [(String, WKUserScriptInjectionTime)] = [
            ("SharedReaderState.js", .atDocumentStart),
            ("ImmersiveEPUB.js", .atDocumentEnd),
        ]
        return specifications.compactMap { filename, injectionTime in
            let scriptURL = libraryRoot.appendingPathComponent("native/\(filename)")
            guard let source = try? String(contentsOf: scriptURL, encoding: .utf8) else {
                return nil
            }
            return WKUserScript(
                source: source,
                injectionTime: injectionTime,
                forMainFrameOnly: false
            )
        }
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
            self.pdfReader?.close(notifyWeb: false)
            let reader = NativePDFReaderController(
                window: window,
                rootView: rootView,
                webView: webView,
                libraryRoot: self.libraryRoot,
                fileURL: fileURL,
                title: title
            )
            reader.onClose = { [weak self] in
                self?.pdfReader = nil
            }
            self.pdfReader = reader
            reader.present()
        }
        return true
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

    private func localPDFURL(from url: URL) -> URL? {
        guard isLocalLibraryURL(url), url.path.hasPrefix("/content/") else { return nil }
        let encodedRelative = String(url.path.dropFirst("/content/".count))
        let relative = encodedRelative.removingPercentEncoding ?? encodedRelative
        let root = libraryRoot.resolvingSymlinksInPath().standardizedFileURL
        let candidate = root
            .appendingPathComponent(relative)
            .resolvingSymlinksInPath()
            .standardizedFileURL
        let rootPath = root.path.hasSuffix("/") ? root.path : root.path + "/"
        guard
            candidate.path.hasPrefix(rootPath),
            candidate.pathExtension.lowercased() == "pdf",
            FileManager.default.fileExists(atPath: candidate.path)
        else { return nil }
        return candidate
    }

    private func isLocalLibraryURL(_ url: URL) -> Bool {
        guard let host = url.host?.lowercased() else { return false }
        return (host == "127.0.0.1" || host == "localhost" || host == "::1")
            && (url.scheme == "http" || url.scheme == "https")
    }
}
