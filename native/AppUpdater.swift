import AppKit
import CryptoKit
import Foundation

private struct AvailableDesktopUpdate {
    let commit: String
    let asset: DesktopUpdateAsset
}

@MainActor
final class AppUpdater: NSObject {
    private static let repository = "dreichner2/cs-library"
    private static let channel = "main"
    private static let platform = "macos-universal"
    private static let latestCommitURL = URL(
        string: "https://api.github.com/repos/dreichner2/cs-library/commits/main"
    )!

    private enum State {
        case idle
        case checking
        case current(String)
        case available(AvailableDesktopUpdate)
        case preparing(String)
        case downloading
        case installing
        case failed(String)
    }

    private weak var window: NSWindow?
    private let statusButton = NSButton()
    private let accessoryController = NSTitlebarAccessoryViewController()
    private let session: URLSession
    private let currentCommit: String
    private var state: State = .idle
    private var checkTask: Task<Void, Never>?
    private var installTask: Task<Void, Never>?

    init(window: NSWindow) {
        self.window = window
        let configuredCommit = Bundle.main.object(forInfoDictionaryKey: "LatticeCommit") as? String
        currentCommit = configuredCommit.flatMap(DesktopUpdateManifest.isFullCommit) == true
            ? configuredCommit!
            : "development"

        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 20
        configuration.timeoutIntervalForResource = 300
        configuration.httpAdditionalHeaders = [
            "Accept": "application/vnd.github+json",
            "User-Agent": "Lattice-Updater"
        ]
        session = URLSession(configuration: configuration)
        super.init()
        configureStatusButton(in: window)
        cleanupCompletedUpdate()
        render()
    }

    deinit {
        checkTask?.cancel()
        installTask?.cancel()
        session.invalidateAndCancel()
    }

    func startAutomaticCheck() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            self?.checkForUpdates(presentResult: false)
        }
    }

    func checkForUpdates(presentResult: Bool) {
        guard installTask == nil else { return }
        checkTask?.cancel()
        state = .checking
        render()

        checkTask = Task { [weak self] in
            guard let self else { return }
            do {
                let latest: GitHubBranchCommit = try await requestJSON(Self.latestCommitURL)
                guard DesktopUpdateManifest.isFullCommit(latest.sha) else {
                    throw UpdateManifestError.invalidCommit
                }
                try Task.checkCancellation()

                if currentCommit == latest.sha {
                    state = .current(latest.sha)
                    render()
                    if presentResult { presentCurrentAlert(commit: latest.sha) }
                    checkTask = nil
                    return
                }

                let manifest: DesktopUpdateManifest
                do {
                    manifest = try await requestJSON(manifestURL())
                } catch AppUpdateError.httpStatus(404) {
                    state = .preparing(latest.sha)
                    render()
                    if presentResult { presentPreparingAlert(commit: latest.sha) }
                    checkTask = nil
                    return
                }
                let asset = try manifest.validatedAsset(
                    platform: Self.platform,
                    expectedRepository: Self.repository,
                    expectedChannel: Self.channel
                )
                try Task.checkCancellation()

                if manifest.commit == latest.sha {
                    let update = AvailableDesktopUpdate(commit: latest.sha, asset: asset)
                    state = .available(update)
                    render()
                    if presentResult { presentAvailableAlert(update) }
                } else {
                    state = .preparing(latest.sha)
                    render()
                    if presentResult { presentPreparingAlert(commit: latest.sha) }
                }
            } catch is CancellationError {
                // A newer manual check replaced this one.
            } catch {
                let message = error.localizedDescription
                state = .failed(message)
                render()
                if presentResult { presentFailureAlert(message) }
            }
            checkTask = nil
        }
    }

    private func configureStatusButton(in window: NSWindow) {
        statusButton.bezelStyle = .texturedRounded
        statusButton.controlSize = .small
        statusButton.font = .systemFont(ofSize: 11, weight: .medium)
        statusButton.target = self
        statusButton.action = #selector(statusButtonPressed(_:))
        statusButton.translatesAutoresizingMaskIntoConstraints = false

        let container = NSView(frame: NSRect(x: 0, y: 0, width: 168, height: 28))
        container.addSubview(statusButton)
        NSLayoutConstraint.activate([
            statusButton.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            statusButton.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            statusButton.centerYAnchor.constraint(equalTo: container.centerYAnchor),
            statusButton.heightAnchor.constraint(equalToConstant: 23)
        ])
        accessoryController.view = container
        accessoryController.layoutAttribute = .right
        window.addTitlebarAccessoryViewController(accessoryController)
    }

    @objc private func statusButtonPressed(_ sender: Any?) {
        switch state {
        case .available(let update):
            presentAvailableAlert(update)
        case .checking, .downloading, .installing:
            break
        default:
            checkForUpdates(presentResult: true)
        }
    }

    private func render() {
        switch state {
        case .idle:
            statusButton.title = "Check for updates"
            statusButton.isEnabled = true
        case .checking:
            statusButton.title = "Checking for updates…"
            statusButton.isEnabled = false
        case .current:
            statusButton.title = "Up to date"
            statusButton.isEnabled = true
        case .available:
            statusButton.title = "Update available"
            statusButton.isEnabled = true
            statusButton.contentTintColor = .systemBlue
        case .preparing:
            statusButton.title = "Update preparing…"
            statusButton.isEnabled = true
        case .downloading:
            statusButton.title = "Downloading update…"
            statusButton.isEnabled = false
        case .installing:
            statusButton.title = "Installing update…"
            statusButton.isEnabled = false
        case .failed:
            statusButton.title = "Update check failed"
            statusButton.isEnabled = true
        }
        if case .available = state {} else { statusButton.contentTintColor = nil }
    }

    private func presentAvailableAlert(_ update: AvailableDesktopUpdate) {
        let alert = NSAlert()
        alert.messageText = "A Lattice update is available"
        alert.informativeText = """
        Installed: \(shortCommit(currentCommit))
        Latest main: \(shortCommit(update.commit))

        The app will verify the download, quit, replace only Lattice.app, and reopen. Books, papers, lectures, and reading data are not changed.
        """
        alert.addButton(withTitle: "Update & Relaunch")
        alert.addButton(withTitle: "Later")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        downloadAndInstall(update)
    }

    private func presentCurrentAlert(commit: String) {
        let alert = NSAlert()
        alert.messageText = "Lattice is up to date"
        alert.informativeText = "This app was built from the latest main commit, \(shortCommit(commit))."
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private func presentPreparingAlert(commit: String) {
        let alert = NSAlert()
        alert.messageText = "The latest update is still being prepared"
        alert.informativeText = "GitHub main is at \(shortCommit(commit)), but its verified macOS and Windows packages are not both published yet. Try again after the build finishes."
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private func presentFailureAlert(_ message: String) {
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Lattice could not check for updates"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private func downloadAndInstall(_ update: AvailableDesktopUpdate) {
        guard installTask == nil else { return }
        state = .downloading
        render()

        installTask = Task { [weak self] in
            guard let self else { return }
            do {
                let (temporaryURL, response) = try await session.download(from: update.asset.url)
                guard let http = response as? HTTPURLResponse else { throw AppUpdateError.badHTTPResponse }
                guard http.statusCode == 200 else { throw AppUpdateError.httpStatus(http.statusCode) }

                let updatesRoot = try Self.updatesRoot()
                let archive = updatesRoot.appendingPathComponent("Lattice-macOS-\(update.commit).zip")
                try Self.removeIfPresent(archive)
                try FileManager.default.moveItem(at: temporaryURL, to: archive)

                let targetApp = Bundle.main.bundleURL.standardizedFileURL
                let pendingApp = try await Task.detached(priority: .userInitiated) {
                    try Self.prepareUpdate(
                        archive: archive,
                        asset: update.asset,
                        expectedCommit: update.commit,
                        targetApp: targetApp,
                        updatesRoot: updatesRoot
                    )
                }.value

                state = .installing
                render()
                try launchInstaller(pendingApp: pendingApp, expectedCommit: update.commit)
                NSApp.terminate(nil)
            } catch {
                state = .failed(error.localizedDescription)
                render()
                presentFailureAlert(error.localizedDescription)
                installTask = nil
            }
        }
    }

    private func requestJSON<T: Decodable>(_ url: URL) async throws -> T {
        var request = URLRequest(url: url)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("Lattice-Updater", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw AppUpdateError.badHTTPResponse }
        guard http.statusCode == 200 else { throw AppUpdateError.httpStatus(http.statusCode) }
        guard data.count <= 1_048_576 else { throw AppUpdateError.metadataTooLarge }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func manifestURL() throws -> URL {
        let configured = Bundle.main.object(forInfoDictionaryKey: "LatticeUpdateManifestURL") as? String
        guard let value = configured,
              let url = URL(string: value),
              url.scheme == "https",
              url.host?.lowercased() == "github.com",
              url.path == "/\(Self.repository)/releases/download/latest-main/update-manifest.json"
        else { throw AppUpdateError.invalidConfiguration }
        return url
    }

    private nonisolated static func prepareUpdate(
        archive: URL,
        asset: DesktopUpdateAsset,
        expectedCommit: String,
        targetApp: URL,
        updatesRoot: URL
    ) throws -> URL {
        let values = try archive.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
        guard values.isRegularFile == true, Int64(values.fileSize ?? -1) == asset.size else {
            throw AppUpdateError.sizeMismatch
        }
        guard try sha256(archive) == asset.sha256 else { throw AppUpdateError.digestMismatch }

        let extractionRoot = updatesRoot.appendingPathComponent("staged-\(expectedCommit)", isDirectory: true)
        try removeIfPresent(extractionRoot)
        try FileManager.default.createDirectory(at: extractionRoot, withIntermediateDirectories: true)
        try run("/usr/bin/ditto", arguments: ["-x", "-k", archive.path, extractionRoot.path])

        let stagedApp = extractionRoot.appendingPathComponent("Lattice.app", isDirectory: true)
        try validateApp(stagedApp, expectedCommit: expectedCommit)

        let targetParent = targetApp.deletingLastPathComponent()
        guard targetApp.lastPathComponent == "Lattice.app" else { throw AppUpdateError.unsafeInstallPath }
        let pendingApp = targetParent.appendingPathComponent(".Lattice.pending-update.app", isDirectory: true)
        try removeIfPresent(pendingApp)
        try FileManager.default.copyItem(at: stagedApp, to: pendingApp)
        try validateApp(pendingApp, expectedCommit: expectedCommit)
        return pendingApp
    }

    private func launchInstaller(pendingApp: URL, expectedCommit: String) throws {
        guard let bundledHelper = Bundle.main.url(forResource: "LatticeUpdateInstaller", withExtension: nil) else {
            throw AppUpdateError.missingInstaller
        }
        let updatesRoot = try Self.updatesRoot()
        let helper = updatesRoot.appendingPathComponent("LatticeUpdateInstaller-\(expectedCommit)")
        try Self.removeIfPresent(helper)
        try FileManager.default.copyItem(at: bundledHelper, to: helper)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: helper.path)

        let process = Process()
        process.executableURL = helper
        process.arguments = [
            "--parent-pid", String(ProcessInfo.processInfo.processIdentifier),
            "--pending-app", pendingApp.path,
            "--target-app", Bundle.main.bundleURL.standardizedFileURL.path,
            "--expected-commit", expectedCommit,
            "--log", updatesRoot.appendingPathComponent("installer.log").path
        ]
        try process.run()
    }

    private nonisolated static func validateApp(_ app: URL, expectedCommit: String) throws {
        let values = try app.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        guard values.isDirectory == true, values.isSymbolicLink != true,
              let bundle = Bundle(url: app),
              bundle.bundleIdentifier == "com.danny.cslibrary",
              bundle.object(forInfoDictionaryKey: "LatticeCommit") as? String == expectedCommit,
              FileManager.default.isExecutableFile(
                atPath: app.appendingPathComponent("Contents/MacOS/Lattice").path
              ),
              FileManager.default.isExecutableFile(
                atPath: app.appendingPathComponent("Contents/Resources/LatticeUpdateInstaller").path
              )
        else { throw AppUpdateError.invalidApplication }

        if let enumerator = FileManager.default.enumerator(
            at: app,
            includingPropertiesForKeys: [.isSymbolicLinkKey],
            options: [.skipsHiddenFiles]
        ) {
            for case let item as URL in enumerator {
                if try item.resourceValues(forKeys: [.isSymbolicLinkKey]).isSymbolicLink == true {
                    throw AppUpdateError.invalidApplication
                }
            }
        }
        try run("/usr/bin/codesign", arguments: ["--verify", "--deep", "--strict", app.path])
    }

    private nonisolated static func sha256(_ file: URL) throws -> String {
        let stream = try FileHandle(forReadingFrom: file)
        defer { try? stream.close() }
        var digest = SHA256()
        while let chunk = try stream.read(upToCount: 1024 * 1024), !chunk.isEmpty {
            digest.update(data: chunk)
        }
        return digest.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private nonisolated static func run(_ executable: String, arguments: [String]) throws {
        let process = Process()
        let errors = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = errors
        process.standardError = errors
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            let detail = String(data: errors.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
            throw AppUpdateError.commandFailed(detail.trimmingCharacters(in: .whitespacesAndNewlines))
        }
    }

    private static func updatesRoot() throws -> URL {
        let root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("CS Library/Updates", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        return root
    }

    private nonisolated static func removeIfPresent(_ url: URL) throws {
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        try FileManager.default.removeItem(at: url)
    }

    private func cleanupCompletedUpdate() {
        let app = Bundle.main.bundleURL.standardizedFileURL
        guard app.lastPathComponent == "Lattice.app" else { return }
        let previous = app.deletingLastPathComponent()
            .appendingPathComponent(".Lattice.previous-update.app", isDirectory: true)
        guard let bundle = Bundle(url: previous), bundle.bundleIdentifier == "com.danny.cslibrary" else { return }
        try? FileManager.default.removeItem(at: previous)
    }

    private func shortCommit(_ commit: String) -> String {
        commit == "development" ? "development build" : String(commit.prefix(12))
    }
}

private enum AppUpdateError: LocalizedError, Sendable {
    case badHTTPResponse
    case httpStatus(Int)
    case metadataTooLarge
    case invalidConfiguration
    case sizeMismatch
    case digestMismatch
    case unsafeInstallPath
    case invalidApplication
    case missingInstaller
    case commandFailed(String)

    var errorDescription: String? {
        switch self {
        case .badHTTPResponse:
            return "GitHub returned an unsuccessful response. Check your connection and try again."
        case .httpStatus(let status):
            return "GitHub returned HTTP status \(status). Check your connection and try again."
        case .metadataTooLarge:
            return "GitHub returned unexpectedly large update metadata."
        case .invalidConfiguration:
            return "This build has an invalid update-channel configuration."
        case .sizeMismatch:
            return "The downloaded update size does not match the published build."
        case .digestMismatch:
            return "The downloaded update failed SHA-256 verification. Nothing was installed."
        case .unsafeInstallPath:
            return "Lattice cannot safely replace the application at its current location."
        case .invalidApplication:
            return "The downloaded archive is not a valid Lattice application."
        case .missingInstaller:
            return "This build is missing its external update installer."
        case .commandFailed(let detail):
            return detail.isEmpty ? "A required update verification command failed." : detail
        }
    }
}
