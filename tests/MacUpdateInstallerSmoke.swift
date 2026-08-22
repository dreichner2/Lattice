import Foundation

@main
struct MacUpdateInstallerSmoke {
    static func main() throws {
        let manager = FileManager.default
        let root = manager.temporaryDirectory.appendingPathComponent(
            "lattice-update-installer-smoke-\(UUID().uuidString)",
            isDirectory: true
        )
        defer { try? manager.removeItem(at: root) }
        let application = root.appendingPathComponent("Lattice.app", isDirectory: true)
        try buildTestApplication(application, version: "2.3.0")

        let version = try MacUpdateInstaller.validateApplicationBundle(
            application,
            expectedVersion: try MacStableVersion("2.3.0")
        )
        precondition(version.description == "2.3.0")
        precondition(!MacUpdateInstaller.isAutomaticUpdateSupported(bundleURL: application))

        let operationID = "12345678-1234-1234-1234-1234567890ab"
        let token = String(repeating: "a", count: 64)
        let activationRecord = Data(
            """
            {"operationID":"\(operationID)","schemaVersion":1,"token":"\(token)","version":"2.3.0"}
            """.utf8
        )
        let activation = MacUpdateInstaller.activationRecord(
            from: activationRecord,
            operationID: operationID
        )
        precondition(activation?.operationID == operationID)
        precondition(activation?.token == token)
        precondition(activation?.version == "2.3.0")
        precondition(MacUpdateInstaller.activationRecord(
            from: activationRecord,
            operationID: "87654321-4321-4321-4321-ba0987654321"
        ) == nil)

        let marker = Data(
            """
            {"operationID":"\(operationID)","processID":4321,"schemaVersion":1,"token":"\(token)","version":"2.3.0"}
            """.utf8
        )
        precondition(MacUpdateInstaller.candidateMarkerIsValid(
            marker,
            operationID: operationID,
            token: token,
            version: "2.3.0",
            processID: 4321
        ))
        precondition(!MacUpdateInstaller.candidateMarkerIsValid(
            marker,
            operationID: operationID,
            token: String(repeating: "b", count: 64),
            version: "2.3.0",
            processID: 4321
        ))
        let helperMarker = Data(
            """
            {"helperProcessID":8765,"operationID":"\(operationID)","parentProcessID":4321,"schemaVersion":1,"token":"\(token)"}
            """.utf8
        )
        precondition(MacUpdateInstaller.helperMarkerIsValid(
            helperMarker,
            operationID: operationID,
            token: token,
            parentProcessID: 4321,
            helperProcessID: 8765
        ))
        precondition(!MacUpdateInstaller.helperMarkerIsValid(
            helperMarker,
            operationID: operationID,
            token: token,
            parentProcessID: 9999,
            helperProcessID: 8765
        ))

        let unsafeLink = application.appendingPathComponent("Contents/Resources/escape")
        try manager.createSymbolicLink(at: unsafeLink, withDestinationURL: URL(fileURLWithPath: "/tmp"))
        do {
            _ = try MacUpdateInstaller.validateApplicationBundle(application)
            fatalError("A symbolic link inside the update application was accepted")
        } catch MacUpdateInstallerError.unsafeExtractedFile {
            // Expected.
        }
        try manager.removeItem(at: unsafeLink)

        try writeInfoPlist(application, version: "9.9.9")
        try sign(application)
        do {
            _ = try MacUpdateInstaller.validateApplicationBundle(
                application,
                expectedVersion: try MacStableVersion("2.3.0")
            )
            fatalError("An update bundle with the wrong version was accepted")
        } catch MacUpdateInstallerError.versionMismatch {
            // Expected.
        }

        print("Mac direct update installer smoke test passed")
    }

    private static func buildTestApplication(_ application: URL, version: String) throws {
        let manager = FileManager.default
        let executableDirectory = application.appendingPathComponent("Contents/MacOS", isDirectory: true)
        let resources = application.appendingPathComponent("Contents/Resources", isDirectory: true)
        try manager.createDirectory(at: executableDirectory, withIntermediateDirectories: true)
        try manager.createDirectory(at: resources, withIntermediateDirectories: true)
        let source = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL
        let executable = executableDirectory.appendingPathComponent("Lattice")
        try manager.copyItem(at: source, to: executable)
        try manager.setAttributes([.posixPermissions: 0o755], ofItemAtPath: executable.path)
        for relative in MacUpdateInstaller.requiredApplicationFiles {
            let required = application.appendingPathComponent(relative)
            try manager.createDirectory(
                at: required.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try Data("updater smoke resource".utf8).write(to: required)
        }
        try writeInfoPlist(application, version: version)
        try sign(application)
    }

    private static func writeInfoPlist(_ application: URL, version: String) throws {
        let info: [String: Any] = [
            "CFBundleIdentifier": "com.danny.cslibrary",
            "CFBundlePackageType": "APPL",
            "CFBundleExecutable": "Lattice",
            "CFBundleShortVersionString": version,
            "CFBundleVersion": "1",
        ]
        let data = try PropertyListSerialization.data(
            fromPropertyList: info,
            format: .xml,
            options: 0
        )
        try data.write(to: application.appendingPathComponent("Contents/Info.plist"))
    }

    private static func sign(_ application: URL) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
        process.arguments = ["--force", "--deep", "--sign", "-", application.path]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
        precondition(process.terminationStatus == 0)
    }
}
