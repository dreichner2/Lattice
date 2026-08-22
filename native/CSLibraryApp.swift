import AppKit
import Foundation
import UniformTypeIdentifiers
import WebKit

final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    private let preferredPort = 8766
    private let candidatePorts = [8766, 8765] + Array(8767...8785)
    private let savedRootKey = "CSLibraryRootPath"

    private var libraryRoot: URL!
    private var expectedLibraryID = ""
    private var window: NSWindow!
    private var rootView: NSView!
    private var webView: WKWebView!
    private var serverProcess: Process?
    private var serverLog: FileHandle?
    private var healthSession: URLSession!
    private var readerKeyMonitor: Any?
    private var immersiveReader: ImmersiveReaderCoordinator!
    private var readerStore: ReaderStore!
    private var readerBridge: ReaderBridge!
    private var appUpdater: AppUpdater!
    private var currentServerURL: URL?
    private var pendingOpenURLs: [URL] = []
    private var webInterfaceReady = false
    private var pendingAddMaterials = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        configureMenu()

        guard let root = locateLibraryRoot(interactively: true) else {
            NSApp.terminate(nil)
            return
        }
        libraryRoot = LibraryIdentity.canonicalRoot(root)
        expectedLibraryID = LibraryIdentity.libraryID(for: libraryRoot)
        UserDefaults.standard.set(libraryRoot.path, forKey: savedRootKey)

        do {
            readerStore = try ReaderStore()
        } catch {
            showFatalError(title: "The reading database could not start", message: error.localizedDescription)
            return
        }

        let sessionConfiguration = URLSessionConfiguration.ephemeral
        sessionConfiguration.timeoutIntervalForRequest = 0.65
        sessionConfiguration.timeoutIntervalForResource = 1.2
        healthSession = URLSession(configuration: sessionConfiguration)

        buildWindow()
        appUpdater = AppUpdater(window: window)
        appUpdater.startAutomaticCheck()
        installReaderKeyMonitor()
        connectToLibrary()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        readerBridge?.finishWebSession()
        immersiveReader?.closePDF(notifyWeb: false)
        if let readerKeyMonitor { NSEvent.removeMonitor(readerKeyMonitor) }
        webView?.configuration.userContentController.removeScriptMessageHandler(forName: ReaderBridge.handlerName, contentWorld: .page)
        healthSession?.invalidateAndCancel()
        if let process = serverProcess, process.isRunning { process.terminate() }
        try? serverLog?.close()
        try? readerStore?.createBackupIfNeeded(force: true)
    }

    func application(_ application: NSApplication, open urls: [URL]) {
        guard libraryRoot != nil, currentServerURL != nil else {
            pendingOpenURLs.append(contentsOf: urls)
            return
        }
        importFiles(urls)
    }

    // MARK: Library location

    private func locateLibraryRoot(interactively: Bool) -> URL? {
        let manager = FileManager.default
        let appParent = Bundle.main.bundleURL.deletingLastPathComponent()
        let configuredRoot = Bundle.main.object(forInfoDictionaryKey: "CSLibraryRoot") as? String
        let savedRoot = UserDefaults.standard.string(forKey: savedRootKey)
        let candidates = [
            savedRoot.map { URL(fileURLWithPath: $0, isDirectory: true) },
            appParent,
            appParent.deletingLastPathComponent(),
            configuredRoot.map { URL(fileURLWithPath: $0, isDirectory: true) }
        ].compactMap { $0 }

        if let match = candidates.first(where: isLibraryRoot) { return match }
        guard interactively else { return nil }

        let panel = NSOpenPanel()
        panel.title = "Choose your Lattice folder"
        panel.message = "Select the folder containing CATALOG.md, library-taxonomy.json, metadata, and the synchronized content folders."
        panel.prompt = "Use Library"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.directoryURL = manager.homeDirectoryForCurrentUser
        guard panel.runModal() == .OK, let url = panel.url else { return nil }
        guard isLibraryRoot(url) else {
            showNonfatalError(
                title: "That folder is not a Lattice library",
                message: "The selected folder must contain CATALOG.md, library-taxonomy.json, and a metadata folder."
            )
            return locateLibraryRoot(interactively: true)
        }
        return url
    }

    private func isLibraryRoot(_ url: URL) -> Bool {
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(atPath: url.appendingPathComponent("CATALOG.md").path)
            && FileManager.default.fileExists(atPath: url.appendingPathComponent("library-taxonomy.json").path)
            && FileManager.default.fileExists(atPath: url.appendingPathComponent("metadata").path, isDirectory: &isDirectory)
            && isDirectory.boolValue
    }

    // MARK: Window and bridge

    private func buildWindow() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        configuration.preferences.isElementFullscreenEnabled = true
        configuration.userContentController.addUserScript(ReaderBridge.bootstrapUserScript)
        if let workspace = ReaderBridge.workspaceUserScript(libraryRoot: libraryRoot) {
            configuration.userContentController.addUserScript(workspace)
        }
        if let script = ImmersiveReaderCoordinator.epubUserScript(libraryRoot: libraryRoot) {
            configuration.userContentController.addUserScript(script)
        }

        let bridge = ReaderBridge(store: readerStore)
        readerBridge = bridge
        configuration.userContentController.addScriptMessageHandler(bridge, contentWorld: .page, name: ReaderBridge.handlerName)

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
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "Lattice"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.minSize = NSSize(width: 880, height: 600)
        window.contentView = rootView
        window.backgroundColor = NSColor.windowBackgroundColor
        window.tabbingMode = .preferred
        window.setFrameAutosaveName("CSLibraryMainWindow")
        if !window.setFrameUsingName("CSLibraryMainWindow") { window.center() }

        immersiveReader = ImmersiveReaderCoordinator(
            window: window,
            rootView: rootView,
            webView: webView,
            libraryRoot: libraryRoot,
            store: readerStore
        )
        readerBridge.coordinator = immersiveReader
        readerBridge.webView = webView

        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    private func installReaderKeyMonitor() {
        readerKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self, self.window?.isKeyWindow == true else { return event }
            if self.immersiveReader?.isPDFOpen == true { return self.immersiveReader.handleKeyEvent(event) }
            guard event.modifierFlags.intersection([.command, .control, .option, .shift]).isEmpty else { return event }
            switch event.keyCode {
            case 123:
                self.webView?.evaluateJavaScript("window.csLibraryHandleNativeArrow?.(-1)")
                return nil
            case 124:
                self.webView?.evaluateJavaScript("window.csLibraryHandleNativeArrow?.(1)")
                return nil
            default:
                return event
            }
        }
    }

    // MARK: Server lifecycle

    private func connectToLibrary() {
        locateRunningLibrary { [weak self] url in
            guard let self else { return }
            if let url { self.loadLibrary(at: url) }
            else { self.startLibraryServer() }
        }
    }

    private func locateRunningLibrary(completion: @escaping (URL?) -> Void) {
        let group = DispatchGroup()
        let lock = NSLock()
        var available = Set<Int>()

        for port in candidatePorts {
            group.enter()
            let healthURL = URL(string: "http://127.0.0.1:\(port)/api/health")!
            healthSession.dataTask(with: healthURL) { [expectedLibraryID] data, response, _ in
                defer { group.leave() }
                guard let http = response as? HTTPURLResponse,
                      http.statusCode == 200,
                      let data,
                      let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                      json["app"] as? String == "cs-library",
                      json["protocolVersion"] as? Int == LibraryIdentity.protocolVersion,
                      json["libraryId"] as? String == expectedLibraryID else { return }
                lock.lock(); available.insert(port); lock.unlock()
            }.resume()
        }

        group.notify(queue: .main) { [candidatePorts, expectedLibraryID] in
            guard let port = candidatePorts.first(where: { available.contains($0) }) else {
                completion(nil); return
            }
            completion(URL(string: "http://127.0.0.1:\(port)/?app=1&library=\(expectedLibraryID.prefix(12))"))
        }
    }

    private func startLibraryServer() {
        let manager = FileManager.default
        let pythonCandidates = [
            "/opt/homebrew/bin/python3",
            "/opt/homebrew/opt/python@3.13/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3"
        ]
        guard let python = pythonCandidates.first(where: manager.isExecutableFile(atPath:)) else {
            showFatalError(
                title: "Python 3 is required",
                message: "Install Python 3 from python.org or Homebrew, then reopen Lattice. The library and reading database remain untouched."
            )
            return
        }

        guard let serverScript = bundledServerScript() else {
            showFatalError(title: "The local library server is missing", message: "Rebuild Lattice.app from the repository.")
            return
        }
        let uiRoot = bundledUIRoot() ?? libraryRoot.appendingPathComponent("ui", isDirectory: true)

        do {
            let logDirectory = manager.urls(for: .libraryDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("Logs/CS Library", isDirectory: true)
            try manager.createDirectory(at: logDirectory, withIntermediateDirectories: true)
            let logURL = logDirectory.appendingPathComponent("server.log")
            if !manager.fileExists(atPath: logURL.path) { manager.createFile(atPath: logURL.path, contents: nil) }
            let log = try FileHandle(forWritingTo: logURL)
            try log.seekToEnd()
            serverLog = log

            let process = Process()
            process.executableURL = URL(fileURLWithPath: python)
            process.arguments = [
                serverScript.path,
                "--root", libraryRoot.path,
                "--ui-root", uiRoot.path,
                "--parent-pid", String(ProcessInfo.processInfo.processIdentifier),
                "--port", String(preferredPort),
                "--no-browser"
            ]
            process.currentDirectoryURL = libraryRoot
            process.standardOutput = log
            process.standardError = log
            process.terminationHandler = { [weak self] process in
                guard process.terminationStatus != 0 else { return }
                DispatchQueue.main.async {
                    self?.showNonfatalError(
                        title: "The local library server stopped",
                        message: "See ~/Library/Logs/CS Library/server.log for details."
                    )
                }
            }
            try process.run()
            serverProcess = process
            waitForStartedServer(attempt: 0)
        } catch {
            showFatalError(title: "The local library could not start", message: error.localizedDescription)
        }
    }

    private func bundledServerScript() -> URL? {
        Bundle.main.url(forResource: "library_ui", withExtension: "py", subdirectory: "server")
            ?? (isLibraryRoot(libraryRoot) ? libraryRoot.appendingPathComponent("scripts/library_ui.py") : nil)
    }

    private func bundledUIRoot() -> URL? {
        Bundle.main.resourceURL?.appendingPathComponent("ui", isDirectory: true)
    }

    private func waitForStartedServer(attempt: Int) {
        locateRunningLibrary { [weak self] url in
            guard let self else { return }
            if let url { self.loadLibrary(at: url); return }
            guard attempt < 32 else {
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
        currentServerURL = url
        webInterfaceReady = false
        webView.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 12))
        if !pendingOpenURLs.isEmpty {
            let pending = pendingOpenURLs
            pendingOpenURLs.removeAll()
            importFiles(pending)
        }
    }

    // MARK: Web navigation

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
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if immersiveReader?.openPDFIfNeeded(for: url) == true { decisionHandler(.cancel); return }
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
        if isLocalLibraryURL(url) { webView.load(navigationAction.request) }
        else { NSWorkspace.shared.open(url) }
        return nil
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        webInterfaceReady = false
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        webInterfaceReady = true
        if pendingAddMaterials {
            pendingAddMaterials = false
            showAddMaterialsDialog()
        }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        showNonfatalError(title: "Lattice could not load", message: error.localizedDescription)
    }

    // MARK: File import/export and diagnostics

    @objc private func chooseLibraryFolder(_ sender: Any?) {
        guard let root = locateLibraryRoot(interactively: true) else { return }
        let canonical = LibraryIdentity.canonicalRoot(root)
        guard canonical != libraryRoot else { return }
        UserDefaults.standard.set(canonical.path, forKey: savedRootKey)
        let alert = NSAlert()
        alert.messageText = "Library folder changed"
        alert.informativeText = "Reopen Lattice to use \(canonical.path)."
        alert.addButton(withTitle: "Quit and Reopen Later")
        alert.runModal()
        NSApp.terminate(nil)
    }

    @objc private func addBooks(_ sender: Any?) {
        guard webInterfaceReady else {
            pendingAddMaterials = true
            return
        }
        showAddMaterialsDialog()
    }

    private func showAddMaterialsDialog() {
        webView?.evaluateJavaScript(
            "typeof window.sharedLibraryChooseFiles === 'function' && (window.sharedLibraryChooseFiles(), true)"
        ) { [weak self] value, error in
            if error != nil || (value as? Bool) != true {
                self?.showNonfatalError(
                    title: "Add materials is unavailable",
                    message: "Reload Lattice and try again."
                )
            }
        }
    }

    private func chooseMaterialKind() -> String? {
        let picker = NSPopUpButton(frame: NSRect(x: 0, y: 0, width: 260, height: 28))
        picker.addItems(withTitles: ["Book", "Paper", "Lecture notes"])
        let alert = NSAlert()
        alert.messageText = "What kind of material are you adding?"
        alert.informativeText = "The selection controls which synchronized shelf receives these files."
        alert.accessoryView = picker
        alert.addButton(withTitle: "Add")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return nil }
        return ["book", "paper", "lecture"][picker.indexOfSelectedItem]
    }

    private func importFiles(_ urls: [URL]) {
        guard !urls.isEmpty else { return }
        guard let endpoint = serverEndpoint("/api/library") else {
            pendingOpenURLs.append(contentsOf: urls)
            return
        }
        guard let kind = chooseMaterialKind() else { return }
        URLSession.shared.dataTask(with: endpoint) { [weak self] data, response, error in
            guard let self else { return }
            guard error == nil,
                  let http = response as? HTTPURLResponse,
                  http.statusCode == 200,
                  let data,
                  let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let token = payload["actionToken"] as? String else {
                DispatchQueue.main.async {
                    self.showNonfatalError(
                        title: "Lattice is not ready to import",
                        message: error?.localizedDescription ?? "Reload the library and try again."
                    )
                }
                return
            }
            self.uploadFiles(
                urls,
                token: token,
                kind: kind,
                index: 0,
                imported: [],
                duplicates: [],
                failures: []
            )
        }.resume()
    }

    private func serverEndpoint(_ path: String) -> URL? {
        guard let currentServerURL,
              var components = URLComponents(url: currentServerURL, resolvingAgainstBaseURL: false) else { return nil }
        components.path = path
        components.query = nil
        components.fragment = nil
        return components.url
    }

    private func uploadFiles(
        _ urls: [URL],
        token: String,
        kind: String,
        index: Int,
        imported: [String],
        duplicates: [String],
        failures: [String]
    ) {
        guard index < urls.count else {
            DispatchQueue.main.async {
                let alert = NSAlert()
                if imported.isEmpty, !duplicates.isEmpty, failures.isEmpty {
                    alert.messageText = "Everything is already on the shelf"
                } else if imported.isEmpty {
                    alert.messageText = "No new files were added"
                } else {
                    alert.messageText = "Added \(imported.count) new file\(imported.count == 1 ? "" : "s")"
                }
                var details: [String] = []
                if !imported.isEmpty {
                    details.append("The new files are on the synchronized shelf; Lattice is filling their details now.")
                }
                if !duplicates.isEmpty {
                    details.append("\(duplicates.count) file\(duplicates.count == 1 ? " was" : "s were") already on the shelf.")
                }
                if !failures.isEmpty {
                    details.append("Some files could not be added:\n\(failures.joined(separator: "\n"))")
                }
                alert.informativeText = details.joined(separator: "\n\n")
                alert.addButton(withTitle: "OK")
                alert.runModal()
            }
            return
        }

        let source = urls[index]
        let ext = source.pathExtension.lowercased()
        guard ["pdf", "epub", "txt"].contains(ext), let endpoint = serverEndpoint("/api/import") else {
            uploadFiles(
                urls,
                token: token,
                kind: kind,
                index: index + 1,
                imported: imported,
                duplicates: duplicates,
                failures: failures + ["\(source.lastPathComponent): unsupported file type"]
            )
            return
        }
        let size = (try? source.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
        let filenameCharacters = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: ".-_"))
        let encodedName = source.lastPathComponent.addingPercentEncoding(withAllowedCharacters: filenameCharacters) ?? ""
        var request = URLRequest(url: endpoint, timeoutInterval: 600)
        request.httpMethod = "POST"
        request.setValue(token, forHTTPHeaderField: "X-Library-Token")
        request.setValue(encodedName, forHTTPHeaderField: "X-Library-Filename")
        request.setValue(kind, forHTTPHeaderField: "X-Library-Kind")
        request.setValue("application/octet-stream", forHTTPHeaderField: "Content-Type")
        request.setValue(String(size), forHTTPHeaderField: "Content-Length")
        URLSession.shared.uploadTask(with: request, fromFile: source) { [weak self] data, response, error in
            guard let self else { return }
            let http = response as? HTTPURLResponse
            let payload = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            if error == nil, http?.statusCode == 201, let path = payload?["path"] as? String {
                let duplicate = payload?["duplicate"] as? Bool == true
                self.uploadFiles(
                    urls,
                    token: token,
                    kind: kind,
                    index: index + 1,
                    imported: duplicate ? imported : imported + [path],
                    duplicates: duplicate ? duplicates + [path] : duplicates,
                    failures: failures
                )
            } else {
                let message = (payload?["error"] as? String) ?? error?.localizedDescription ?? "Import failed"
                self.uploadFiles(
                    urls,
                    token: token,
                    kind: kind,
                    index: index + 1,
                    imported: imported,
                    duplicates: duplicates,
                    failures: failures + ["\(source.lastPathComponent): \(message)"]
                )
            }
        }.resume()
    }

    @objc private func openLibraryFolder(_ sender: Any?) { NSWorkspace.shared.open(libraryRoot) }
    @objc private func openReaderDataFolder(_ sender: Any?) { NSWorkspace.shared.open(readerStore.dataDirectory) }

    @objc private func exportReaderJSON(_ sender: Any?) { exportReaderData(extension: "json", format: "JSON") }
    @objc private func exportReaderMarkdown(_ sender: Any?) { exportReaderData(extension: "md", format: "Markdown") }

    private func exportReaderData(extension ext: String, format: String) {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "Lattice-Reading-Data.\(ext)"
        panel.allowedContentTypes = ext == "json" ? [.json] : [.plainText]
        panel.prompt = "Export"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            if ext == "json" { try readerStore.exportJSON(to: url) }
            else { try readerStore.exportMarkdown(to: url) }
        } catch {
            showNonfatalError(title: "\(format) export failed", message: error.localizedDescription)
        }
    }

    @objc private func importReaderData(_ sender: Any?) {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.json]
        panel.allowsMultipleSelection = false
        panel.prompt = "Import"
        guard panel.runModal() == .OK, let url = panel.url else { return }

        let confirmation = NSAlert()
        confirmation.alertStyle = .warning
        confirmation.messageText = "Import reading data?"
        confirmation.informativeText = "The import will merge documents, progress, bookmarks, notes, highlights, and preferences. A backup is created first."
        confirmation.addButton(withTitle: "Import")
        confirmation.addButton(withTitle: "Cancel")
        guard confirmation.runModal() == .alertFirstButtonReturn else { return }
        do {
            try readerStore.createBackupIfNeeded(force: true)
            try readerStore.importJSON(from: url)
        } catch {
            showNonfatalError(title: "Reading data import failed", message: error.localizedDescription)
        }
    }

    @objc private func showDiagnostics(_ sender: Any?) {
        do {
            let diagnostics = try readerStore.diagnostics()
            let backupText = diagnostics.lastBackupAt.map {
                ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: $0))
            } ?? "Never"
            let alert = NSAlert()
            alert.messageText = diagnostics.integrity == "ok" ? "Lattice is healthy" : "Lattice needs attention"
            alert.informativeText = """
            Library: \(libraryRoot.path)
            Library ID: \(expectedLibraryID.prefix(16))…
            Reader database: \(diagnostics.databasePath)
            Database integrity: \(diagnostics.integrity)
            Schema: \(diagnostics.schemaVersion)
            Documents: \(diagnostics.documentCount)
            Bookmarks: \(diagnostics.bookmarkCount)
            Annotations: \(diagnostics.annotationCount)
            Reading sessions: \(diagnostics.sessionCount)
            Backups: \(diagnostics.backupCount) (latest: \(backupText))
            Server: \(currentServerURL?.absoluteString ?? "Not connected")
            """
            alert.addButton(withTitle: "OK")
            alert.addButton(withTitle: "Open Data Folder")
            if alert.runModal() == .alertSecondButtonReturn { NSWorkspace.shared.open(readerStore.dataDirectory) }
        } catch {
            showNonfatalError(title: "Diagnostics failed", message: error.localizedDescription)
        }
    }

    // MARK: Reader menu actions

    @objc private func reloadLibrary(_ sender: Any?) {
        immersiveReader?.closePDF(notifyWeb: false)
        webView?.reloadFromOrigin()
    }

    @objc private func readerPrevious(_ sender: Any?) {
        if immersiveReader?.previousPage() != true { webView.evaluateJavaScript("window.csLibraryHandleNativeArrow?.(-1)") }
    }
    @objc private func readerNext(_ sender: Any?) {
        if immersiveReader?.nextPage() != true { webView.evaluateJavaScript("window.csLibraryHandleNativeArrow?.(1)") }
    }
    @objc private func readerFocus(_ sender: Any?) {
        if immersiveReader?.toggleFocus() != true { webView.evaluateJavaScript("document.querySelector('#readerFocusButton:not([hidden])')?.click()") }
    }
    @objc private func readerSidebar(_ sender: Any?) {
        if immersiveReader?.toggleSidebar() != true { webView.evaluateJavaScript("document.querySelector('#readerTocButton:not([hidden])')?.click()") }
    }
    @objc private func readerBookmark(_ sender: Any?) {
        if immersiveReader?.toggleBookmark() != true { webView.evaluateJavaScript("document.querySelector('#readerBookmarkButton:not([hidden])')?.click()") }
    }
    @objc private func readerHighlight(_ sender: Any?) {
        if immersiveReader?.addHighlight() != true { webView.evaluateJavaScript("window.csLibraryHighlightSelection?.('yellow')") }
    }
    @objc private func readerFind(_ sender: Any?) {
        if immersiveReader?.focusSearch() != true { webView.evaluateJavaScript("window.csLibraryFocusEpubSearch?.()") }
    }

    // MARK: Menus and alerts

    private func configureMenu() {
        let mainMenu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Lattice", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        addMenuItem(appMenu, "Check for Updates…", #selector(checkForUpdates(_:)))
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Hide Lattice", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit Lattice", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        mainMenu.addItem(appItem)

        let fileItem = NSMenuItem()
        let fileMenu = NSMenu(title: "File")
        addMenuItem(fileMenu, "Add Materials…", #selector(addBooks(_:)), "o", [.command, .shift])
        addMenuItem(fileMenu, "Choose Library Folder…", #selector(chooseLibraryFolder(_:)))
        fileMenu.addItem(.separator())
        addMenuItem(fileMenu, "Open Library Folder", #selector(openLibraryFolder(_:)), "o")
        addMenuItem(fileMenu, "Open Reader Data Folder", #selector(openReaderDataFolder(_:)))
        fileMenu.addItem(.separator())
        addMenuItem(fileMenu, "Export Reading Data as JSON…", #selector(exportReaderJSON(_:)))
        addMenuItem(fileMenu, "Export Reading Notebook as Markdown…", #selector(exportReaderMarkdown(_:)))
        addMenuItem(fileMenu, "Import Reading Data…", #selector(importReaderData(_:)))
        fileItem.submenu = fileMenu
        mainMenu.addItem(fileItem)

        let readerItem = NSMenuItem()
        let readerMenu = NSMenu(title: "Reader")
        addMenuItem(readerMenu, "Previous Page", #selector(readerPrevious(_:)), "[", [.command])
        addMenuItem(readerMenu, "Next Page", #selector(readerNext(_:)), "]", [.command])
        readerMenu.addItem(.separator())
        addMenuItem(readerMenu, "Find in Book", #selector(readerFind(_:)), "f", [.command])
        addMenuItem(readerMenu, "Bookmark Position", #selector(readerBookmark(_:)), "d", [.command])
        addMenuItem(readerMenu, "Highlight Selection", #selector(readerHighlight(_:)), "h", [.command, .shift])
        addMenuItem(readerMenu, "Toggle Contents", #selector(readerSidebar(_:)), "s", [.command, .shift])
        addMenuItem(readerMenu, "Toggle Focus Mode", #selector(readerFocus(_:)), "f", [.command, .shift])
        readerItem.submenu = readerMenu
        mainMenu.addItem(readerItem)

        let viewItem = NSMenuItem()
        let viewMenu = NSMenu(title: "View")
        addMenuItem(viewMenu, "Reload Library", #selector(reloadLibrary(_:)), "r")
        viewMenu.addItem(.separator())
        addMenuItem(viewMenu, "Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control])
        viewItem.submenu = viewMenu
        mainMenu.addItem(viewItem)

        let helpItem = NSMenuItem()
        let helpMenu = NSMenu(title: "Help")
        addMenuItem(helpMenu, "Library Diagnostics…", #selector(showDiagnostics(_:)))
        helpItem.submenu = helpMenu
        mainMenu.addItem(helpItem)
        NSApp.mainMenu = mainMenu
    }

    @objc private func checkForUpdates(_ sender: Any?) {
        appUpdater?.checkForUpdates(presentResult: true)
    }

    private func addMenuItem(
        _ menu: NSMenu,
        _ title: String,
        _ action: Selector,
        _ key: String = "",
        _ modifiers: NSEvent.ModifierFlags = [.command]
    ) {
        let item = menu.addItem(withTitle: title, action: action, keyEquivalent: key)
        item.target = self
        item.keyEquivalentModifierMask = key.isEmpty ? [] : modifiers
    }

    private func showFatalError(title: String, message: String) {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: "Quit")
        alert.runModal()
        NSApp.terminate(nil)
    }

    private func showNonfatalError(title: String, message: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = title
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
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
