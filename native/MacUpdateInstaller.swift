import CryptoKit
import Darwin
import Foundation
import Security

struct PreparedMacUpdate: Sendable {
    let operationID: String
    let token: String
    let operationDirectory: URL
    let targetApplication: URL
    let version: MacStableVersion
}

struct MacUpdateActivation: Sendable {
    let operationID: String
    let token: String
    let version: String
}

enum MacUpdateInstaller {
    static let installedApplicationPath = "/Applications/Lattice.app"
    static let helperFlag = "--lattice-apply-update"
    static let candidateFlag = "--lattice-update-candidate"
    static let maximumExtractedBytes: Int64 = 2_147_483_648
    static let maximumExtractedFiles = 20_000
    static let requiredApplicationFiles = [
        "Contents/Resources/ui/index.html",
        "Contents/Resources/ui/app.js",
        "Contents/Resources/ui/tutor.js",
        "Contents/Resources/ui/tutor-styles.css",
        "Contents/Resources/ui/study-lab.html",
        "Contents/Resources/ui/study-lab.css",
        "Contents/Resources/ui/study-lab.js",
        "Contents/Resources/ui/vendor/katex/LICENSE",
        "Contents/Resources/ui/vendor/katex/README-LATTICE.md",
        "Contents/Resources/ui/vendor/katex/katex.min.css",
        "Contents/Resources/ui/vendor/katex/katex.min.js",
        "Contents/Resources/ui/vendor/katex/fonts/KaTeX_Main-Regular.woff2",
        "Contents/Resources/ui/pdf-reader.html",
        "Contents/Resources/ui/pdf-reader.js",
        "Contents/Resources/ui/pdf-reader-lifecycle.mjs",
        "Contents/Resources/ui/vendor/pdfjs/build/pdf.min.mjs",
        "Contents/Resources/server/library_ui.py",
        "Contents/Resources/server/lattice_tutor.py",
        "Contents/Resources/server/library_vault.py",
        "Contents/Resources/server/study_lab.py",
        "Contents/Resources/server/vendor/pypdf/__init__.py",
        "Contents/Resources/server/vendor/pypdf-LICENSE",
        "Contents/Resources/server/move_library.py",
        "Contents/Resources/ImmersiveEPUB.js",
        "Contents/Resources/LibraryWorkspace.js",
        "Contents/Resources/THIRD_PARTY_NOTICES.md",
    ]

    static func isAutomaticUpdateSupported(
        bundleURL: URL = Bundle.main.bundleURL
    ) -> Bool {
        (try? automaticUpdateTarget(bundleURL: bundleURL)) != nil
    }

    static func prepare(
        release: ValidatedMacRelease,
        bundleURL: URL = Bundle.main.bundleURL
    ) async throws -> PreparedMacUpdate {
        guard let asset = release.asset else {
            throw MacUpdateInstallerError.missingAsset
        }
        let target = try automaticUpdateTarget(bundleURL: bundleURL)
        let operationID = UUID().uuidString.lowercased()
        let token = randomToken()
        let root = try updatesRoot()
        let operation = root.appendingPathComponent(operationID, isDirectory: true)
        try createPrivateDirectory(operation)

        do {
            let manifest = operation.appendingPathComponent("update-manifest.json")
            let signature = operation.appendingPathComponent("update-manifest.json.sig")
            try writePrivate(release.signedManifest, to: manifest)
            try writePrivate(release.manifestSignature, to: signature)

            let archive = operation.appendingPathComponent(MacUpdateChecker.assetName)
            try await download(asset: asset, to: archive)
            try validateArchive(archive, asset: asset)

            // Validate once before the current app exits. The helper deletes
            // this extraction and repeats the signed validation after exit so
            // changed staging bytes cannot win the replacement race.
            _ = try await extractAndValidate(
                operationDirectory: operation,
                expectedVersion: release.version
            )
            return PreparedMacUpdate(
                operationID: operationID,
                token: token,
                operationDirectory: operation,
                targetApplication: target,
                version: release.version
            )
        } catch {
            try? FileManager.default.removeItem(at: operation)
            throw error
        }
    }

    static func launchHelper(
        for prepared: PreparedMacUpdate,
        parentProcessID: Int32 = ProcessInfo.processInfo.processIdentifier
    ) throws {
        guard let executable = Bundle.main.executableURL else {
            throw MacUpdateInstallerError.missingExecutable
        }
        let process = Process()
        process.executableURL = executable
        let plan = HelperPlanRecord(
            schemaVersion: 1,
            operationID: prepared.operationID,
            parentProcessID: parentProcessID,
            targetApplication: prepared.targetApplication.path,
            version: prepared.version.description,
            token: prepared.token
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try writePrivate(
            encoder.encode(plan),
            to: helperPlan(in: prepared.operationDirectory)
        )
        process.arguments = [helperFlag, prepared.operationID]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        let deadline = Date().addingTimeInterval(5)
        let marker = helperMarker(in: prepared.operationDirectory)
        while Date() < deadline {
            if let data = try? boundedData(from: marker, maximumBytes: 16 * 1024),
               helperMarkerIsValid(
                data,
                operationID: prepared.operationID,
                token: prepared.token,
                parentProcessID: parentProcessID,
                helperProcessID: process.processIdentifier
               ) {
                return
            }
            if !process.isRunning { break }
            Thread.sleep(forTimeInterval: 0.05)
        }
        if process.isRunning { process.terminate() }
        throw MacUpdateInstallerError.helperDidNotStart
    }

    static func runHelperIfRequested(arguments: [String] = CommandLine.arguments) -> Int32? {
        guard arguments.contains(helperFlag) else { return nil }
        var target: URL?
        do {
            let plan = try parseHelperPlan(arguments)
            target = plan.targetApplication
            try apply(plan)
            return 0
        } catch {
            recordHelperFailure(error)
            let previousAppIsStillRunning: Bool
            if let installerError = error as? MacUpdateInstallerError,
               case .parentDidNotExit = installerError {
                previousAppIsStillRunning = true
            } else {
                previousAppIsStillRunning = false
            }
            if let target, !previousAppIsStillRunning {
                _ = try? launchApplication(at: target, arguments: [])
            }
            return 1
        }
    }

    static func activation(
        from arguments: [String] = CommandLine.arguments
    ) -> MacUpdateActivation? {
        guard arguments.count == 3,
              arguments[1] == candidateFlag,
              isOperationID(arguments[2]),
              let operation = try? operationDirectory(for: arguments[2]),
              (try? isDirectoryWithoutSymlink(operation)) == true,
              let data = try? boundedData(
                from: candidateActivation(in: operation),
                maximumBytes: 16 * 1024
              )
        else { return nil }
        return activationRecord(from: data, operationID: arguments[2])
    }

    static func activationRecord(
        from data: Data,
        operationID: String
    ) -> MacUpdateActivation? {
        guard data.count <= 16 * 1024,
              let record = try? JSONDecoder().decode(CandidateActivationRecord.self, from: data),
              record.schemaVersion == 1,
              record.operationID == operationID,
              isOperationID(record.operationID),
              isLowerHexToken(record.token),
              (try? MacStableVersion(record.version)) != nil
        else { return nil }
        return MacUpdateActivation(
            operationID: record.operationID,
            token: record.token,
            version: record.version
        )
    }

    static func markCandidateHealthy(
        _ activation: MacUpdateActivation,
        version: String,
        processID: Int32 = ProcessInfo.processInfo.processIdentifier
    ) throws {
        _ = try MacStableVersion(version)
        guard version == activation.version else {
            throw MacUpdateInstallerError.versionMismatch
        }
        let operation = try operationDirectory(for: activation.operationID)
        guard try isDirectoryWithoutSymlink(operation) else {
            throw MacUpdateInstallerError.unsafeOperationDirectory
        }
        let marker = candidateMarker(in: operation)
        let payload = CandidateReadyRecord(
            schemaVersion: 1,
            operationID: activation.operationID,
            token: activation.token,
            version: version,
            processID: processID
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try writePrivate(encoder.encode(payload), to: marker, atomically: true)
    }

    static func candidateMarkerIsValid(
        _ data: Data,
        operationID: String,
        token: String,
        version: String,
        processID: Int32
    ) -> Bool {
        guard data.count <= 16 * 1024,
              let ready = try? JSONDecoder().decode(CandidateReadyRecord.self, from: data)
        else { return false }
        return ready.schemaVersion == 1
            && ready.operationID == operationID
            && ready.token == token
            && ready.version == version
            && ready.processID == processID
    }

    static func helperMarkerIsValid(
        _ data: Data,
        operationID: String,
        token: String,
        parentProcessID: Int32,
        helperProcessID: Int32
    ) -> Bool {
        guard data.count <= 16 * 1024,
              let ready = try? JSONDecoder().decode(HelperReadyRecord.self, from: data)
        else { return false }
        return ready.schemaVersion == 1
            && ready.operationID == operationID
            && ready.token == token
            && ready.parentProcessID == parentProcessID
            && ready.helperProcessID == helperProcessID
    }

    static func validateApplicationBundle(
        _ application: URL,
        expectedVersion: MacStableVersion? = nil
    ) throws -> MacStableVersion {
        let manager = FileManager.default
        guard application.lastPathComponent == "Lattice.app",
              try isDirectoryWithoutSymlink(application)
        else { throw MacUpdateInstallerError.invalidApplication }

        var fileCount = 0
        var extractedBytes: Int64 = 0
        let keys: [URLResourceKey] = [
            .isDirectoryKey,
            .isRegularFileKey,
            .isSymbolicLinkKey,
            .fileSizeKey,
        ]
        var enumerationFailed = false
        guard let enumerator = manager.enumerator(
            at: application,
            includingPropertiesForKeys: keys,
            options: [],
            errorHandler: { _, _ in
                enumerationFailed = true
                return false
            }
        ) else { throw MacUpdateInstallerError.invalidApplication }
        for case let entry as URL in enumerator {
            let values = try entry.resourceValues(forKeys: Set(keys))
            if values.isSymbolicLink == true {
                throw MacUpdateInstallerError.unsafeExtractedFile
            }
            if values.isDirectory == true { continue }
            guard values.isRegularFile == true else {
                throw MacUpdateInstallerError.unsafeExtractedFile
            }
            guard let fileSize = values.fileSize,
                  fileSize >= 0,
                  Int64(fileSize) <= maximumExtractedBytes - extractedBytes else {
                throw MacUpdateInstallerError.extractedApplicationTooLarge
            }
            fileCount += 1
            extractedBytes += Int64(fileSize)
            guard fileCount <= maximumExtractedFiles else {
                throw MacUpdateInstallerError.extractedApplicationTooLarge
            }
        }
        guard !enumerationFailed else {
            throw MacUpdateInstallerError.invalidApplication
        }

        let infoURL = application.appendingPathComponent("Contents/Info.plist")
        let infoData = try Data(contentsOf: infoURL, options: [.mappedIfSafe])
        guard infoData.count <= 256 * 1024,
              let info = try PropertyListSerialization.propertyList(
                from: infoData,
                options: [],
                format: nil
              ) as? [String: Any],
              info["CFBundleIdentifier"] as? String == "com.danny.cslibrary",
              info["CFBundlePackageType"] as? String == "APPL",
              info["CFBundleExecutable"] as? String == "Lattice",
              let versionText = info["CFBundleShortVersionString"] as? String
        else { throw MacUpdateInstallerError.invalidApplication }
        let version = try MacStableVersion(versionText)
        if let expectedVersion, version != expectedVersion {
            throw MacUpdateInstallerError.versionMismatch
        }

        let executable = application.appendingPathComponent("Contents/MacOS/Lattice")
        guard manager.isExecutableFile(atPath: executable.path),
              try executable.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey]).isRegularFile == true,
              try executable.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey]).isSymbolicLink != true
        else { throw MacUpdateInstallerError.invalidApplication }
        for relative in requiredApplicationFiles {
            let required = application.appendingPathComponent(relative)
            let values = try required.resourceValues(
                forKeys: [.isRegularFileKey, .isSymbolicLinkKey]
            )
            guard values.isRegularFile == true, values.isSymbolicLink != true else {
                throw MacUpdateInstallerError.invalidApplication
            }
        }
        guard try executableContainsSupportedArchitecture(executable) else {
            throw MacUpdateInstallerError.invalidApplication
        }
        guard applicationCodeSignatureIsValid(application) else {
            throw MacUpdateInstallerError.invalidApplication
        }
        return version
    }

    static func executableContainsSupportedArchitecture(
        _ executable: URL
    ) throws -> Bool {
        let handle = try FileHandle(forReadingFrom: executable)
        defer { try? handle.close() }
        guard let header = try handle.read(upToCount: 8), header.count == 8 else {
            return false
        }

        let magic = Array(header.prefix(4))
        let littleEndian: Bool
        let isFat64: Bool
        switch magic {
        case [0xcf, 0xfa, 0xed, 0xfe]:
            guard let remainder = try handle.read(upToCount: 4), remainder.count == 4 else {
                return false
            }
            return machArchitectureIsSupported(
                cpuType: uint32(Array(header[4..<8]), littleEndian: true),
                cpuSubtype: uint32(Array(remainder), littleEndian: true)
            )
        case [0xfe, 0xed, 0xfa, 0xcf]:
            guard let remainder = try handle.read(upToCount: 4), remainder.count == 4 else {
                return false
            }
            return machArchitectureIsSupported(
                cpuType: uint32(Array(header[4..<8]), littleEndian: false),
                cpuSubtype: uint32(Array(remainder), littleEndian: false)
            )
        case [0xca, 0xfe, 0xba, 0xbe]:
            littleEndian = false
            isFat64 = false
        case [0xbe, 0xba, 0xfe, 0xca]:
            littleEndian = true
            isFat64 = false
        case [0xca, 0xfe, 0xba, 0xbf]:
            littleEndian = false
            isFat64 = true
        case [0xbf, 0xba, 0xfe, 0xca]:
            littleEndian = true
            isFat64 = true
        default:
            return false
        }

        let architectureCount = Int(uint32(Array(header[4..<8]), littleEndian: littleEndian))
        guard architectureCount > 0, architectureCount <= 64 else { return false }
        let entrySize = isFat64 ? 32 : 20
        guard let table = try handle.read(upToCount: architectureCount * entrySize),
              table.count == architectureCount * entrySize else { return false }
        for index in 0..<architectureCount {
            let offset = index * entrySize
            let cpuType = uint32(Array(table[offset..<(offset + 4)]), littleEndian: littleEndian)
            let cpuSubtype = uint32(
                Array(table[(offset + 4)..<(offset + 8)]),
                littleEndian: littleEndian
            )
            if machArchitectureIsSupported(cpuType: cpuType, cpuSubtype: cpuSubtype) {
                return true
            }
        }
        return false
    }

    private static func uint32(_ bytes: [UInt8], littleEndian: Bool) -> UInt32 {
        precondition(bytes.count == 4)
        if littleEndian {
            return UInt32(bytes[0])
                | UInt32(bytes[1]) << 8
                | UInt32(bytes[2]) << 16
                | UInt32(bytes[3]) << 24
        }
        return UInt32(bytes[0]) << 24
            | UInt32(bytes[1]) << 16
            | UInt32(bytes[2]) << 8
            | UInt32(bytes[3])
    }

    private static func machArchitectureIsSupported(
        cpuType: UInt32,
        cpuSubtype: UInt32
    ) -> Bool {
        // CPU_TYPE_ARM64 with CPU_SUBTYPE_ARM64_ALL. The upper subtype byte
        // contains capability flags and does not change the base subtype.
        cpuType == 0x0100_000c && (cpuSubtype & 0x00ff_ffff) == 0
    }

    private static func applicationCodeSignatureIsValid(_ application: URL) -> Bool {
        var code: SecStaticCode?
        let createStatus = SecStaticCodeCreateWithPath(
            application as CFURL,
            SecCSFlags(rawValue: 0),
            &code
        )
        guard createStatus == errSecSuccess, let code else { return false }
        let flags = SecCSFlags(
            rawValue: kSecCSCheckAllArchitectures
                | kSecCSStrictValidate
                | kSecCSCheckNestedCode
        )
        return SecStaticCodeCheckValidity(code, flags, nil) == errSecSuccess
    }

    // MARK: Preparation

    private static func automaticUpdateTarget(bundleURL: URL) throws -> URL {
        let standardized = bundleURL.standardizedFileURL
        guard standardized.path == installedApplicationPath,
              try isDirectoryWithoutSymlink(standardized),
              FileManager.default.isWritableFile(
                atPath: standardized.deletingLastPathComponent().path
              )
        else { throw MacUpdateInstallerError.notInstalledInApplications }
        return standardized
    }

    private static func updatesRoot() throws -> URL {
        guard let base = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        ).first else { throw MacUpdateInstallerError.unsafeOperationDirectory }
        let root = base.appendingPathComponent("Lattice/Updates", isDirectory: true)
        if FileManager.default.fileExists(atPath: root.path) {
            guard try isDirectoryWithoutSymlink(root) else {
                throw MacUpdateInstallerError.unsafeOperationDirectory
            }
        } else {
            try createPrivateDirectory(root)
        }
        guard root.standardizedFileURL.path == root.resolvingSymlinksInPath().path else {
            throw MacUpdateInstallerError.unsafeOperationDirectory
        }
        return root
    }

    private static func operationDirectory(for operationID: String) throws -> URL {
        guard isOperationID(operationID) else {
            throw MacUpdateInstallerError.invalidHelperArguments
        }
        return try updatesRoot().appendingPathComponent(operationID, isDirectory: true)
    }

    private static func createPrivateDirectory(_ url: URL) throws {
        try FileManager.default.createDirectory(
            at: url,
            withIntermediateDirectories: true,
            attributes: [.posixPermissions: 0o700]
        )
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o700],
            ofItemAtPath: url.path
        )
        guard try isDirectoryWithoutSymlink(url) else {
            throw MacUpdateInstallerError.unsafeOperationDirectory
        }
    }

    private static func writePrivate(
        _ data: Data,
        to url: URL,
        atomically: Bool = false
    ) throws {
        try data.write(to: url, options: atomically ? [.atomic] : [.withoutOverwriting])
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: url.path
        )
    }

    private static func download(
        asset: ValidatedMacUpdateAsset,
        to destination: URL
    ) async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 600
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }

        var request = URLRequest(url: asset.downloadURL)
        request.setValue("Lattice-macOS-Updater", forHTTPHeaderField: "User-Agent")
        let (temporary, response) = try await session.download(for: request)
        try Task.checkCancellation()
        guard let http = response as? HTTPURLResponse else {
            throw MacUpdateInstallerError.invalidDownload
        }
        guard http.statusCode == 200,
              http.url?.scheme?.lowercased() == "https" else {
            throw MacUpdateInstallerError.invalidDownload
        }
        if response.expectedContentLength > 0,
           response.expectedContentLength != asset.size {
            throw MacUpdateInstallerError.downloadSizeMismatch
        }
        let size = try temporary.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? -1
        guard Int64(size) == asset.size else {
            throw MacUpdateInstallerError.downloadSizeMismatch
        }
        try FileManager.default.moveItem(at: temporary, to: destination)
        try FileManager.default.setAttributes(
            [.posixPermissions: 0o600],
            ofItemAtPath: destination.path
        )
    }

    private static func validateArchive(
        _ archive: URL,
        asset: ValidatedMacUpdateAsset
    ) throws {
        let values = try archive.resourceValues(
            forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey]
        )
        guard values.isRegularFile == true,
              values.isSymbolicLink != true,
              let size = values.fileSize,
              Int64(size) == asset.size,
              try sha256(of: archive) == asset.sha256 else {
            throw MacUpdateInstallerError.archiveDigestMismatch
        }
    }

    private static func sha256(of url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var digest = SHA256()
        while true {
            let data = try handle.read(upToCount: 1024 * 1024) ?? Data()
            if data.isEmpty { break }
            digest.update(data: data)
        }
        return digest.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private static func extractAndValidate(
        operationDirectory: URL,
        expectedVersion: MacStableVersion
    ) async throws -> URL {
        let archive = operationDirectory.appendingPathComponent(MacUpdateChecker.assetName)
        let extracted = operationDirectory.appendingPathComponent("Extracted", isDirectory: true)
        if FileManager.default.fileExists(atPath: extracted.path) {
            try FileManager.default.removeItem(at: extracted)
        }
        try createPrivateDirectory(extracted)
        try await runProcess(
            executable: URL(fileURLWithPath: "/usr/bin/ditto"),
            arguments: ["-x", "-k", archive.path, extracted.path]
        )
        return try validateExtractedApplication(
            in: extracted,
            expectedVersion: expectedVersion
        )
    }

    private static func extractAndValidateSynchronously(
        operationDirectory: URL,
        expectedVersion: MacStableVersion
    ) throws -> URL {
        let archive = operationDirectory.appendingPathComponent(MacUpdateChecker.assetName)
        let extracted = operationDirectory.appendingPathComponent("Extracted", isDirectory: true)
        if FileManager.default.fileExists(atPath: extracted.path) {
            try FileManager.default.removeItem(at: extracted)
        }
        try createPrivateDirectory(extracted)
        try runProcessSynchronously(
            executable: URL(fileURLWithPath: "/usr/bin/ditto"),
            arguments: ["-x", "-k", archive.path, extracted.path]
        )
        return try validateExtractedApplication(
            in: extracted,
            expectedVersion: expectedVersion
        )
    }

    private static func validateExtractedApplication(
        in extracted: URL,
        expectedVersion: MacStableVersion
    ) throws -> URL {
        let children = try FileManager.default.contentsOfDirectory(
            at: extracted,
            includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey],
            options: []
        )
        guard children.count == 1,
              children[0].lastPathComponent == "Lattice.app" else {
            throw MacUpdateInstallerError.invalidApplication
        }
        _ = try validateApplicationBundle(children[0], expectedVersion: expectedVersion)
        return children[0]
    }

    // MARK: Helper replacement and transient recovery

    private struct HelperPlan {
        let operationID: String
        let parentProcessID: Int32
        let targetApplication: URL
        let version: MacStableVersion
        let token: String
    }

    private static func parseHelperPlan(_ arguments: [String]) throws -> HelperPlan {
        guard arguments.count == 3,
              arguments[1] == helperFlag,
              isOperationID(arguments[2]) else {
            throw MacUpdateInstallerError.invalidHelperArguments
        }
        let operationID = arguments[2]
        let operation = try operationDirectory(for: operationID)
        guard try isDirectoryWithoutSymlink(operation) else {
            throw MacUpdateInstallerError.unsafeOperationDirectory
        }
        let data = try boundedData(from: helperPlan(in: operation), maximumBytes: 16 * 1024)
        let record = try JSONDecoder().decode(HelperPlanRecord.self, from: data)
        guard record.schemaVersion == 1,
              record.operationID == operationID,
              record.parentProcessID > 1,
              record.targetApplication == installedApplicationPath,
              isLowerHexToken(record.token)
        else { throw MacUpdateInstallerError.invalidHelperArguments }
        return HelperPlan(
            operationID: operationID,
            parentProcessID: record.parentProcessID,
            targetApplication: URL(fileURLWithPath: record.targetApplication, isDirectory: true),
            version: try MacStableVersion(record.version),
            token: record.token
        )
    }

    private static func apply(_ plan: HelperPlan) throws {
        let expectedParentExecutable = plan.targetApplication
            .appendingPathComponent("Contents/MacOS/Lattice")
            .standardizedFileURL.path
        guard processExecutablePath(processID: plan.parentProcessID) == expectedParentExecutable else {
            throw MacUpdateInstallerError.invalidHelperArguments
        }
        let operation = try operationDirectory(for: plan.operationID)
        guard try isDirectoryWithoutSymlink(operation) else {
            throw MacUpdateInstallerError.unsafeOperationDirectory
        }
        let ready = HelperReadyRecord(
            schemaVersion: 1,
            operationID: plan.operationID,
            token: plan.token,
            parentProcessID: plan.parentProcessID,
            helperProcessID: ProcessInfo.processInfo.processIdentifier
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        try writePrivate(
            encoder.encode(ready),
            to: helperMarker(in: operation),
            atomically: true
        )
        guard waitForExit(processID: plan.parentProcessID, timeout: 45) else {
            throw MacUpdateInstallerError.parentDidNotExit
        }
        let manifestURL = operation.appendingPathComponent("update-manifest.json")
        let signatureURL = operation.appendingPathComponent("update-manifest.json.sig")
        let manifest = try boundedData(from: manifestURL, maximumBytes: MacUpdateChecker.maximumManifestBytes)
        let signature = try boundedData(from: signatureURL, maximumBytes: 4096)
        let release = try MacUpdateChecker.validatedRelease(
            manifestData: manifest,
            signatureData: signature
        )
        guard release.version == plan.version,
              let asset = release.asset else {
            throw MacUpdateInstallerError.manifestMismatch
        }
        let archive = operation.appendingPathComponent(MacUpdateChecker.assetName)
        try validateArchive(archive, asset: asset)
        let staged = try extractAndValidateSynchronously(
            operationDirectory: operation,
            expectedVersion: plan.version
        )

        let currentVersion = try validateApplicationBundle(plan.targetApplication)
        guard plan.version > currentVersion else {
            throw MacUpdateInstallerError.manifestMismatch
        }
        let parent = plan.targetApplication.deletingLastPathComponent()
        let shortID = String(plan.operationID.prefix(8))
        let backup = parent.appendingPathComponent(
            ".Lattice.previous-\(currentVersion)-\(shortID).app",
            isDirectory: true
        )
        guard !FileManager.default.fileExists(atPath: backup.path) else {
            throw MacUpdateInstallerError.backupCollision
        }

        var oldApplicationMoved = false
        var candidate: Process?
        do {
            try FileManager.default.moveItem(at: plan.targetApplication, to: backup)
            oldApplicationMoved = true
            try FileManager.default.moveItem(at: staged, to: plan.targetApplication)
            _ = try validateApplicationBundle(
                plan.targetApplication,
                expectedVersion: plan.version
            )

            let marker = candidateMarker(in: operation)
            if FileManager.default.fileExists(atPath: marker.path) {
                try FileManager.default.removeItem(at: marker)
            }
            let activation = CandidateActivationRecord(
                schemaVersion: 1,
                operationID: plan.operationID,
                token: plan.token,
                version: plan.version.description
            )
            let activationEncoder = JSONEncoder()
            activationEncoder.outputFormatting = [.sortedKeys]
            try writePrivate(
                activationEncoder.encode(activation),
                to: candidateActivation(in: operation)
            )
            candidate = try launchApplication(
                at: plan.targetApplication,
                arguments: [candidateFlag, plan.operationID]
            )
            guard waitForCandidate(
                candidate!,
                operationDirectory: operation,
                operationID: plan.operationID,
                token: plan.token,
                version: plan.version.description,
                timeout: 90
            ) else { throw MacUpdateInstallerError.candidateDidNotBecomeHealthy }

            // The previous bundle exists only to make this replacement
            // transaction recoverable until the candidate proves healthy. A
            // successful update must not retain versioned application copies;
            // published releases remain available from GitHub if an older
            // version is wanted later.
            try FileManager.default.removeItem(at: backup)
            oldApplicationMoved = false
            try? FileManager.default.removeItem(at: operation)
        } catch {
            if let candidate, candidate.isRunning {
                candidate.terminate()
                if !waitForExit(processID: candidate.processIdentifier, timeout: 5) {
                    _ = Darwin.kill(candidate.processIdentifier, SIGKILL)
                    _ = waitForExit(processID: candidate.processIdentifier, timeout: 5)
                }
            }
            var failedCandidate: URL?
            if oldApplicationMoved {
                if FileManager.default.fileExists(atPath: plan.targetApplication.path) {
                    let failed = parent.appendingPathComponent(
                        ".Lattice.failed-\(plan.version)-\(shortID).app",
                        isDirectory: true
                    )
                    if !FileManager.default.fileExists(atPath: failed.path) {
                        try? FileManager.default.moveItem(at: plan.targetApplication, to: failed)
                        if FileManager.default.fileExists(atPath: failed.path) {
                            failedCandidate = failed
                        }
                    }
                }
                if !FileManager.default.fileExists(atPath: plan.targetApplication.path),
                   FileManager.default.fileExists(atPath: backup.path) {
                    try FileManager.default.moveItem(at: backup, to: plan.targetApplication)
                }
                if let failedCandidate,
                   FileManager.default.fileExists(atPath: plan.targetApplication.path) {
                    try? FileManager.default.removeItem(at: failedCandidate)
                }
            }
            throw error
        }
    }

    @discardableResult
    private static func launchApplication(
        at application: URL,
        arguments: [String]
    ) throws -> Process {
        let executable = application.appendingPathComponent("Contents/MacOS/Lattice")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else {
            throw MacUpdateInstallerError.missingExecutable
        }
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        return process
    }

    private static func waitForCandidate(
        _ candidate: Process,
        operationDirectory: URL,
        operationID: String,
        token: String,
        version: String,
        timeout: TimeInterval
    ) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        let marker = candidateMarker(in: operationDirectory)
        while Date() < deadline {
            if let data = try? boundedData(from: marker, maximumBytes: 16 * 1024),
               candidateMarkerIsValid(
                data,
                operationID: operationID,
                token: token,
                version: version,
                processID: candidate.processIdentifier
               ) {
                return true
            }
            if !candidate.isRunning { return false }
            Thread.sleep(forTimeInterval: 0.25)
        }
        return false
    }

    private static func candidateMarker(in operation: URL) -> URL {
        operation.appendingPathComponent("candidate-ready.json")
    }

    private static func helperMarker(in operation: URL) -> URL {
        operation.appendingPathComponent("helper-ready.json")
    }

    private static func helperPlan(in operation: URL) -> URL {
        operation.appendingPathComponent("helper-plan.json")
    }

    private static func candidateActivation(in operation: URL) -> URL {
        operation.appendingPathComponent("candidate-activation.json")
    }

    // MARK: Bounded helpers

    private static func boundedData(from url: URL, maximumBytes: Int) throws -> Data {
        let values = try url.resourceValues(
            forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey]
        )
        guard values.isRegularFile == true,
              values.isSymbolicLink != true,
              let size = values.fileSize,
              size > 0,
              size <= maximumBytes else {
            throw MacUpdateInstallerError.unsafeMetadata
        }
        return try Data(contentsOf: url, options: [.mappedIfSafe])
    }

    private static func isDirectoryWithoutSymlink(_ url: URL) throws -> Bool {
        let values = try url.resourceValues(forKeys: [.isDirectoryKey, .isSymbolicLinkKey])
        return values.isDirectory == true && values.isSymbolicLink != true
    }

    private static func randomToken() -> String {
        (UUID().uuidString + UUID().uuidString)
            .replacingOccurrences(of: "-", with: "")
            .lowercased()
    }

    private static func isOperationID(_ value: String) -> Bool {
        value == value.lowercased()
            && value.count == 36
            && UUID(uuidString: value) != nil
    }

    private static func isLowerHexToken(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy {
            ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 102)
        }
    }

    private static func waitForExit(processID: Int32, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if Darwin.kill(processID, 0) != 0 && errno == ESRCH { return true }
            Thread.sleep(forTimeInterval: 0.2)
        }
        return Darwin.kill(processID, 0) != 0 && errno == ESRCH
    }

    private static func processExecutablePath(processID: Int32) -> String? {
        var buffer = [CChar](repeating: 0, count: 4096)
        let length = proc_pidpath(processID, &buffer, UInt32(buffer.count))
        guard length > 0 else { return nil }
        return URL(fileURLWithPath: String(cString: buffer)).standardizedFileURL.path
    }

    private static func runProcess(
        executable: URL,
        arguments: [String]
    ) async throws {
        try await withCheckedThrowingContinuation { continuation in
            let process = Process()
            process.executableURL = executable
            process.arguments = arguments
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            process.terminationHandler = { completed in
                if completed.terminationStatus == 0 {
                    continuation.resume()
                } else {
                    continuation.resume(throwing: MacUpdateInstallerError.toolFailed)
                }
            }
            do {
                try process.run()
            } catch {
                process.terminationHandler = nil
                continuation.resume(throwing: error)
            }
        }
    }

    private static func runProcessSynchronously(
        executable: URL,
        arguments: [String]
    ) throws {
        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else {
            throw MacUpdateInstallerError.toolFailed
        }
    }

    private static func recordHelperFailure(_ error: Error) {
        do {
            guard let logs = FileManager.default.urls(
                for: .libraryDirectory,
                in: .userDomainMask
            ).first?.appendingPathComponent("Logs/Lattice", isDirectory: true) else { return }
            try FileManager.default.createDirectory(
                at: logs,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
            let log = logs.appendingPathComponent("update.log")
            let line = "\(ISO8601DateFormatter().string(from: Date())) update failed: \(error.localizedDescription)\n"
            let data = Data(line.utf8)
            if !FileManager.default.fileExists(atPath: log.path) {
                try data.write(to: log, options: [.withoutOverwriting])
            } else {
                let handle = try FileHandle(forWritingTo: log)
                defer { try? handle.close() }
                try handle.seekToEnd()
                try handle.write(contentsOf: data)
            }
        } catch {
            // Logging must never replace the updater's real result.
        }
    }
}

private struct CandidateReadyRecord: Codable {
    let schemaVersion: Int
    let operationID: String
    let token: String
    let version: String
    let processID: Int32
}

private struct HelperPlanRecord: Codable {
    let schemaVersion: Int
    let operationID: String
    let parentProcessID: Int32
    let targetApplication: String
    let version: String
    let token: String
}

private struct CandidateActivationRecord: Codable {
    let schemaVersion: Int
    let operationID: String
    let token: String
    let version: String
}

private struct HelperReadyRecord: Codable {
    let schemaVersion: Int
    let operationID: String
    let token: String
    let parentProcessID: Int32
    let helperProcessID: Int32
}

enum MacUpdateInstallerError: LocalizedError, Sendable {
    case notInstalledInApplications
    case missingAsset
    case missingExecutable
    case unsafeOperationDirectory
    case unsafeMetadata
    case invalidDownload
    case downloadSizeMismatch
    case archiveDigestMismatch
    case invalidApplication
    case unsafeExtractedFile
    case extractedApplicationTooLarge
    case versionMismatch
    case invalidHelperArguments
    case helperDidNotStart
    case parentDidNotExit
    case manifestMismatch
    case backupCollision
    case candidateDidNotBecomeHealthy
    case toolFailed

    var errorDescription: String? {
        switch self {
        case .notInstalledInApplications:
            return "Direct updates require Lattice.app at /Applications/Lattice.app with permission to replace it."
        case .missingAsset:
            return "This signed release does not include a direct macOS update."
        case .missingExecutable:
            return "The Lattice update helper executable is missing."
        case .unsafeOperationDirectory:
            return "Lattice refused an unsafe update staging directory."
        case .unsafeMetadata:
            return "The staged update metadata is outside Lattice's safety limit."
        case .invalidDownload:
            return "The update download returned an invalid or insecure response."
        case .downloadSizeMismatch:
            return "The update download size does not match the signed manifest."
        case .archiveDigestMismatch:
            return "The update ZIP does not match the signed SHA-256 digest."
        case .invalidApplication:
            return "The update ZIP does not contain one complete Lattice application."
        case .unsafeExtractedFile:
            return "The update contains a symbolic link or unsupported file type."
        case .extractedApplicationTooLarge:
            return "The extracted update is outside Lattice's safety limits."
        case .versionMismatch:
            return "The application inside the update has the wrong version."
        case .invalidHelperArguments:
            return "The update helper received an invalid replacement plan."
        case .helperDidNotStart:
            return "The update helper did not confirm that it was ready, so Lattice stayed open."
        case .parentDidNotExit:
            return "The previous Lattice process did not exit, so nothing was replaced."
        case .manifestMismatch:
            return "The staged update no longer matches its signed manifest."
        case .backupCollision:
            return "Lattice refused to overwrite an existing application backup."
        case .candidateDidNotBecomeHealthy:
            return "The updated app did not become healthy, so Lattice restored the previous version."
        case .toolFailed:
            return "macOS could not validate or extract the downloaded update."
        }
    }
}
