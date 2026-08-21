import AppKit
import Foundation
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    private let preferredPort = 8766
    private let candidatePorts = [8766, 8765] + Array(8767...8785)
    private var libraryRoot: URL!
    private var window: NSWindow!
    private var rootView: NSView!
    private var webView: WKWebView!
    private var serverProcess: Process?
    private var serverLog: FileHandle?
    private var healthSession: URLSession!
    private var readerKeyMonitor: Any?
    private var immersiveReader: ImmersiveReaderCoordinator!

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        configureMenu()

        guard let root = locateLibraryRoot() else {
            showFatalError(
                title: "CS Library could not find its shelf",
                message: "Keep CS Library.app in the cs-library folder, beside scripts and books."
            )
            return
        }
        libraryRoot = root

        let sessionConfiguration = URLSessionConfiguration.ephemeral
        sessionConfiguration.timeoutIntervalForRequest = 0.45
        sessionConfiguration.timeoutIntervalForResource = 0.75
        healthSession = URLSession(configuration: sessionConfiguration)

        buildWindow()
        installReaderKeyMonitor()
        connectToLibrary()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationWillTerminate(_ notification: Notification) {
        immersiveReader?.closePDF(notifyWeb: false)
        if let readerKeyMonitor {
            NSEvent.removeMonitor(readerKeyMonitor)
        }
        healthSession?.invalidateAndCancel()
        if let process = serverProcess, process.isRunning {
            process.terminate()
        }
        try? serverLog?.close()
    }

    private func locateLibraryRoot() -> URL? {
        let fileManager = FileManager.default
        let appParent = Bundle.main.bundleURL.deletingLastPathComponent()
        let configuredRoot = Bundle.main.object(forInfoDictionaryKey: "CSLibraryRoot") as? String
        let candidates = [
            appParent,
            appParent.deletingLastPathComponent(),
            configuredRoot.map { URL(fileURLWithPath: $0, isDirectory: true) }
        ].compactMap { $0 }

        return candidates.first { candidate in
            fileManager.fileExists(atPath: candidate.appendingPathComponent("scripts/library_ui.py").path)
                && fileManager.fileExists(atPath: candidate.appendingPathComponent("ui/index.html").path)
        }
    }

    private func buildWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.preferences.isElementFullscreenEnabled = true
        if let script = ImmersiveReaderCoordinator.epubUserScript(libraryRoot: libraryRoot) {
            configuration.userContentController.addUserScript(script)
        }

        webView = WKWebView(frame: .zero, configuration: configuration)
        webView.translatesAutoresizingMaskIntoConstraints = false
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsMagnification = true
        webView.setValue(false, forKey: "drawsBackground")

        rootView = NSView(frame: .zero)
        rootView.wantsLayer = true
        rootView.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        rootView.addSubview(webView)
        NSLayoutConstraint.activate([
            webView.leadingAnchor.constraint(equalTo: rootView.leadingAnchor),
            webView.trailingAnchor.constraint(equalTo: rootView.trailingAnchor),
            webView.topAnchor.constraint(equalTo: rootView.topAnchor),
            webView.bottomAnchor.constraint(equalTo: rootView.bottomAnchor)
        ])

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1380, height: 880),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "CS Library"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.minSize = NSSize(width: 980, height: 640)
        window.contentView = rootView
        window.backgroundColor = NSColor.windowBackgroundColor
        window.setFrameAutosaveName("CSLibraryMainWindow")
        if !window.setFrameUsingName("CSLibraryMainWindow") {
            window.center()
        }

        immersiveReader = ImmersiveReaderCoordinator(
            window: window,
            rootView: rootView,
            webView: webView,
            libraryRoot: libraryRoot
        )

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func installReaderKeyMonitor() {
        readerKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self, self.window?.isKeyWindow == true else { return event }

            if self.immersiveReader?.isPDFOpen == true {
                return self.immersiveReader.handleKeyEvent(event)
            }

            guard event.modifierFlags.intersection([.command, .control, .option, .shift]).isEmpty else {
                return event
            }

            let direction: Int
            switch event.keyCode {
            case 123:
                direction = -1
            case 124:
                direction = 1
            default:
                return event
            }

            self.webView?.evaluateJavaScript("window.csLibraryHandleNativeArrow?.(\(direction))")
            return event
        }
    }

    private func connectToLibrary() {
        locateRunningLibrary { [weak self] url in
            guard let self else { return }
            if let url {
                self.loadLibrary(at: url)
            } else {
                self.startLibraryServer()
            }
        }
    }

    private func locateRunningLibrary(completion: @escaping (URL?) -> Void) {
        let group = DispatchGroup()
        let lock = NSLock()
        var available = Set<Int>()

        for port in candidatePorts {
            group.enter()
            let url = URL(string: "http://127.0.0.1:\(port)/api/health")!
            healthSession.dataTask(with: url) { data, response, _ in
                defer { group.leave() }
                guard
                    let http = response as? HTTPURLResponse,
                    http.statusCode == 200,
                    let data,
                    let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                    json["app"] as? String == "cs-library"
                else { return }
                lock.lock()
                available.insert(port)
                lock.unlock()
            }.resume()
        }

        group.notify(queue: .main) { [candidatePorts] in
            let port = candidatePorts.first(where: { available.contains($0) })
            completion(port.flatMap { URL(string: "http://127.0.0.1:\($0)/?app=1") })
        }
    }

    private func startLibraryServer() {
        let fileManager = FileManager.default
        let pythonCandidates = [
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3"
        ]
        guard let python = pythonCandidates.first(where: { fileManager.isExecutableFile(atPath: $0) }) else {
            showFatalError(title: "Python 3 is required", message: "Install Python 3, then reopen CS Library.app.")
            return
        }

        do {
            let logDirectory = fileManager.urls(for: .libraryDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("Logs/CS Library", isDirectory: true)
            try fileManager.createDirectory(at: logDirectory, withIntermediateDirectories: true)
            let logURL = logDirectory.appendingPathComponent("server.log")
            if !fileManager.fileExists(atPath: logURL.path) {
                fileManager.createFile(atPath: logURL.path, contents: nil)
            }
            let log = try FileHandle(forWritingTo: logURL)
            try log.seekToEnd()
            serverLog = log

            let process = Process()
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = [
                libraryRoot.appendingPathComponent("scripts/library_ui.py").path,
                "--port", String(preferredPort),
                "--no-browser"
            ]
            process.currentDirectoryURL = libraryRoot
            process.standardOutput = log
            process.standardError = log
            try process.run()
            serverProcess = process
            waitForStartedServer(attempt: 0)
        } catch {
            showFatalError(title: "The local library could not start", message: error.localizedDescription)
        }
    }

    private func waitForStartedServer(attempt: Int) {
        locateRunningLibrary { [weak self] url in
            guard let self else { return }
            if let url {
                self.loadLibrary(at: url)
                return
            }
            guard attempt < 24 else {
                self.showFatalError(
                    title: "The local library did not become ready",
                    message: "See ~/Library/Logs/CS Library/server.log for details."
                )
                return
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                self.waitForStartedServer(attempt: attempt + 1)
            }
        }
    }

    private func loadLibrary(at url: URL) {
        webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10))
    }

    private func isLocalLibraryURL(_ url: URL) -> Bool {
        guard let host = url.host?.lowercased() else { return false }
        return (host == "127.0.0.1" || host == "localhost" || host == "::1")
            && (url.scheme == "http" || url.scheme == "https")
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }

        if immersiveReader?.openPDFIfNeeded(for: url) == true {
            decisionHandler(.cancel)
            return
        }

        if isLocalLibraryURL(url) || url.scheme == "about" {
            decisionHandler(.allow)
        } else if navigationAction.navigationType == .linkActivated || navigationAction.targetFrame == nil {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        } else {
            decisionHandler(.allow)
        }
    }

    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        guard navigationAction.targetFrame == nil, let url = navigationAction.request.url else { return nil }
        if isLocalLibraryURL(url) {
            webView.load(navigationAction.request)
        } else {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        showFatalError(title: "CS Library could not load", message: error.localizedDescription, terminate: false)
    }

    @objc private func reloadLibrary(_ sender: Any?) {
        immersiveReader?.closePDF(notifyWeb: false)
        webView?.reloadFromOrigin()
    }

    @objc private func openLibraryFolder(_ sender: Any?) {
        if let libraryRoot {
            NSWorkspace.shared.open(libraryRoot)
        }
    }

    @objc private func readerPrevious(_ sender: Any?) {
        if immersiveReader?.previousPage() != true {
            webView.evaluateJavaScript("window.csLibraryHandleNativeArrow?.(-1)")
        }
    }

    @objc private func readerNext(_ sender: Any?) {
        if immersiveReader?.nextPage() != true {
            webView.evaluateJavaScript("window.csLibraryHandleNativeArrow?.(1)")
        }
    }

    @objc private func readerFocus(_ sender: Any?) {
        if immersiveReader?.toggleFocus() != true {
            webView.evaluateJavaScript("document.querySelector('#readerFocusButton:not([hidden])')?.click()")
        }
    }

    @objc private func readerSidebar(_ sender: Any?) {
        if immersiveReader?.toggleSidebar() != true {
            webView.evaluateJavaScript("document.querySelector('#readerTocButton:not([hidden])')?.click()")
        }
    }

    @objc private func readerBookmark(_ sender: Any?) {
        if immersiveReader?.toggleBookmark() != true {
            webView.evaluateJavaScript("document.querySelector('#readerBookmarkButton:not([hidden])')?.click()")
        }
    }

    @objc private func readerFind(_ sender: Any?) {
        if immersiveReader?.focusSearch() != true {
            webView.evaluateJavaScript("document.querySelector('#readerTocButton:not([hidden])')?.click(); setTimeout(() => document.querySelector('#epubTocSearch')?.focus(), 180)")
        }
    }

    private func configureMenu() {
        let mainMenu = NSMenu()

        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About CS Library", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide CS Library", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit CS Library", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        mainMenu.addItem(appItem)

        let fileItem = NSMenuItem()
        let fileMenu = NSMenu(title: "File")
        let openFolderItem = fileMenu.addItem(withTitle: "Open Library Folder", action: #selector(openLibraryFolder(_:)), keyEquivalent: "o")
        openFolderItem.target = self
        fileItem.submenu = fileMenu
        mainMenu.addItem(fileItem)

        let readerItem = NSMenuItem()
        let readerMenu = NSMenu(title: "Reader")
        let previous = readerMenu.addItem(withTitle: "Previous Page", action: #selector(readerPrevious(_:)), keyEquivalent: "[")
        previous.keyEquivalentModifierMask = [.command]
        previous.target = self
        let next = readerMenu.addItem(withTitle: "Next Page", action: #selector(readerNext(_:)), keyEquivalent: "]")
        next.keyEquivalentModifierMask = [.command]
        next.target = self
        readerMenu.addItem(.separator())
        let find = readerMenu.addItem(withTitle: "Find in Book", action: #selector(readerFind(_:)), keyEquivalent: "f")
        find.keyEquivalentModifierMask = [.command]
        find.target = self
        let bookmark = readerMenu.addItem(withTitle: "Bookmark Page", action: #selector(readerBookmark(_:)), keyEquivalent: "d")
        bookmark.keyEquivalentModifierMask = [.command]
        bookmark.target = self
        let sidebar = readerMenu.addItem(withTitle: "Toggle Contents", action: #selector(readerSidebar(_:)), keyEquivalent: "s")
        sidebar.keyEquivalentModifierMask = [.command, .shift]
        sidebar.target = self
        let focus = readerMenu.addItem(withTitle: "Toggle Focus Mode", action: #selector(readerFocus(_:)), keyEquivalent: "f")
        focus.keyEquivalentModifierMask = [.command, .shift]
        focus.target = self
        readerItem.submenu = readerMenu
        mainMenu.addItem(readerItem)

        let viewItem = NSMenuItem()
        let viewMenu = NSMenu(title: "View")
        let reloadItem = viewMenu.addItem(withTitle: "Reload Library", action: #selector(reloadLibrary(_:)), keyEquivalent: "r")
        reloadItem.target = self
        viewMenu.addItem(.separator())
        let fullScreenItem = viewMenu.addItem(withTitle: "Enter Full Screen", action: #selector(NSWindow.toggleFullScreen(_:)), keyEquivalent: "f")
        fullScreenItem.keyEquivalentModifierMask = [.command, .control]
        viewItem.submenu = viewMenu
        mainMenu.addItem(viewItem)

        NSApp.mainMenu = mainMenu
    }

    private func showFatalError(title: String, message: String, terminate: Bool = true) {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
        if terminate {
            NSApp.terminate(nil)
        }
    }
}

@main
struct CSLibraryApplication {
    static func main() {
        let application = NSApplication.shared
        let delegate = AppDelegate()
        application.delegate = delegate
        application.run()
    }
}
