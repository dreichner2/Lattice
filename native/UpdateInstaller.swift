import AppKit
import Darwin
import Foundation

@main
struct LatticeUpdateInstaller {
    static func main() {
        do {
            let arguments = try InstallerArguments(CommandLine.arguments)
            let logger = InstallerLogger(path: arguments.logPath)
            logger.write("Waiting for Lattice process \(arguments.parentPID) to exit")
            try waitForExit(pid: arguments.parentPID)
            try install(arguments, logger: logger)
            logger.write("Update installed successfully")
        } catch {
            let message = "Lattice update failed: \(error.localizedDescription)"
            FileHandle.standardError.write(Data((message + "\n").utf8))
            exit(1)
        }
    }

    private static func waitForExit(pid: Int32) throws {
        let deadline = Date().addingTimeInterval(60)
        while kill(pid, 0) == 0 || errno == EPERM {
            guard Date() < deadline else { throw InstallerError.parentDidNotExit }
            usleep(100_000)
        }
    }

    private static func install(_ arguments: InstallerArguments, logger: InstallerLogger) throws {
        let manager = FileManager.default
        let pending = URL(fileURLWithPath: arguments.pendingApp).standardizedFileURL
        let target = URL(fileURLWithPath: arguments.targetApp).standardizedFileURL
        guard target.lastPathComponent == "Lattice.app",
              pending.lastPathComponent == ".Lattice.pending-update.app",
              pending.deletingLastPathComponent() == target.deletingLastPathComponent()
        else { throw InstallerError.unsafePath }

        try validateApp(pending, expectedCommit: arguments.expectedCommit)
        guard let current = Bundle(url: target), current.bundleIdentifier == "com.danny.cslibrary" else {
            throw InstallerError.invalidCurrentApp
        }

        let backup = target.deletingLastPathComponent()
            .appendingPathComponent(".Lattice.previous-update.app", isDirectory: true)
        if manager.fileExists(atPath: backup.path) { try manager.removeItem(at: backup) }

        logger.write("Moving current app to rollback location")
        try manager.moveItem(at: target, to: backup)
        do {
            try manager.moveItem(at: pending, to: target)
            try validateApp(target, expectedCommit: arguments.expectedCommit)
        } catch {
            logger.write("Installation failed; restoring previous app")
            if manager.fileExists(atPath: target.path) { try? manager.removeItem(at: target) }
            if manager.fileExists(atPath: backup.path) { try? manager.moveItem(at: backup, to: target) }
            throw error
        }

        let opener = Process()
        opener.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        opener.arguments = ["-n", target.path]
        do {
            try opener.run()
            opener.waitUntilExit()
            guard opener.terminationStatus == 0 else { throw InstallerError.relaunchFailed }
        } catch {
            logger.write("Relaunch failed; restoring previous app")
            try? manager.removeItem(at: target)
            try? manager.moveItem(at: backup, to: target)
            throw error
        }
    }

    private static func validateApp(_ app: URL, expectedCommit: String) throws {
        guard let bundle = Bundle(url: app),
              bundle.bundleIdentifier == "com.danny.cslibrary",
              bundle.object(forInfoDictionaryKey: "LatticeCommit") as? String == expectedCommit,
              FileManager.default.isExecutableFile(
                atPath: app.appendingPathComponent("Contents/MacOS/Lattice").path
              )
        else { throw InstallerError.invalidPendingApp }

        let verifier = Process()
        verifier.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
        verifier.arguments = ["--verify", "--deep", "--strict", app.path]
        try verifier.run()
        verifier.waitUntilExit()
        guard verifier.terminationStatus == 0 else { throw InstallerError.invalidPendingApp }
    }
}

private struct InstallerArguments {
    let parentPID: Int32
    let pendingApp: String
    let targetApp: String
    let expectedCommit: String
    let logPath: String

    init(_ arguments: [String]) throws {
        var values: [String: String] = [:]
        var index = 1
        while index + 1 < arguments.count {
            let key = arguments[index]
            guard key.hasPrefix("--"), values[key] == nil else { throw InstallerError.invalidArguments }
            values[key] = arguments[index + 1]
            index += 2
        }
        guard index == arguments.count,
              let pidText = values["--parent-pid"],
              let pid = Int32(pidText), pid > 1,
              let pending = values["--pending-app"],
              let target = values["--target-app"],
              let commit = values["--expected-commit"], DesktopUpdateManifest.isFullCommit(commit),
              let log = values["--log"]
        else { throw InstallerError.invalidArguments }
        parentPID = pid
        pendingApp = pending
        targetApp = target
        expectedCommit = commit
        logPath = log
    }
}

private final class InstallerLogger {
    private let path: String

    init(path: String) {
        self.path = path
    }

    func write(_ message: String) {
        let line = "[\(ISO8601DateFormatter().string(from: Date()))] \(message)\n"
        let data = Data(line.utf8)
        if !FileManager.default.fileExists(atPath: path) {
            FileManager.default.createFile(atPath: path, contents: data)
            return
        }
        guard let handle = try? FileHandle(forWritingTo: URL(fileURLWithPath: path)) else { return }
        defer { try? handle.close() }
        _ = try? handle.seekToEnd()
        try? handle.write(contentsOf: data)
    }
}

private enum InstallerError: LocalizedError {
    case invalidArguments
    case parentDidNotExit
    case unsafePath
    case invalidCurrentApp
    case invalidPendingApp
    case relaunchFailed

    var errorDescription: String? {
        switch self {
        case .invalidArguments: return "The installer received invalid arguments."
        case .parentDidNotExit: return "The running Lattice app did not exit in time."
        case .unsafePath: return "The requested application paths are unsafe."
        case .invalidCurrentApp: return "The installed Lattice app could not be identified."
        case .invalidPendingApp: return "The replacement Lattice app failed validation."
        case .relaunchFailed: return "The updated Lattice app could not be reopened."
        }
    }
}
