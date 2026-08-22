import Foundation
import Security

struct MacStableVersion: Comparable, CustomStringConvertible, Sendable {
    let major: Int
    let minor: Int
    let patch: Int

    init(_ value: String) throws {
        let parts = value.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 3 else { throw MacUpdateCheckError.invalidVersion(value) }

        func parse(_ part: Substring) throws -> Int {
            guard !part.isEmpty,
                  (part.count == 1 || part.first != "0"),
                  part.utf8.allSatisfy({ $0 >= 48 && $0 <= 57 }),
                  let number = Int(part), number <= Int(Int32.max)
            else { throw MacUpdateCheckError.invalidVersion(value) }
            return number
        }

        major = try parse(parts[0])
        minor = try parse(parts[1])
        patch = try parse(parts[2])
    }

    static func < (lhs: MacStableVersion, rhs: MacStableVersion) -> Bool {
        if lhs.major != rhs.major { return lhs.major < rhs.major }
        if lhs.minor != rhs.minor { return lhs.minor < rhs.minor }
        return lhs.patch < rhs.patch
    }

    var description: String { "\(major).\(minor).\(patch)" }
}

struct ValidatedMacUpdateAsset: Sendable {
    let downloadURL: URL
    let sha256: String
    let size: Int64
}

struct ValidatedMacRelease: Sendable {
    let version: MacStableVersion
    let releaseURL: URL
    let publishedAt: String
    let asset: ValidatedMacUpdateAsset?
    let signedManifest: Data
    let manifestSignature: Data
}

enum MacUpdateCheckResult: Sendable {
    case current(ValidatedMacRelease)
    case available(ValidatedMacRelease)
    case developmentBuild(installed: MacStableVersion, latest: ValidatedMacRelease)
}

enum MacUpdateChecker {
    static let repository = "dreichner2/Lattice"
    static let platform = "macos-arm64"
    static let assetName = "Lattice-macOS.zip"
    static let manifestURL = URL(
        string: "https://github.com/dreichner2/Lattice/releases/latest/download/update-manifest.json"
    )!
    static let signatureURL = URL(
        string: "https://github.com/dreichner2/Lattice/releases/latest/download/update-manifest.json.sig"
    )!
    static let maximumManifestBytes = 64 * 1024
    static let signatureBytes = 384
    static let maximumArchiveBytes: Int64 = 1_073_741_824

    // PKCS#1 DER for the same RSA-3072 public key embedded by the Windows
    // updater. The corresponding private key never enters the app or repo.
    static let productionPublicKeyPKCS1Base64 = """
    MIIBigKCAYEA1MwHuaIA2eztxZaUBox3OeJE32teqcIXLJI1yX0ZRyIqUokgRexJbPegNloVkRtiTBswTrqWGXq/0DuSfckMSqpSULxvn59QVYuPvJy6PKYrAHQXqymSiSklWt01dzqz9oWDXhR9jGHX2fWWOiEGxxJ5U/rm0p8yiVItdFyzeUtLX6myejl0R4JEGpDk4U0nT6Vww8FxBK9HmRJPzecpyPLtEOWTpKwCa8WqEtU8nyma8EiHCtr6630IoeOUfayqus5evKFgCz4zuZUtxnju4znz9OJYqgN1uykqkWE2s0sDskLkUaPbUC4A1cxI7z7hEadTVF6s2V7eQLeEk2X5VVo4kHm3pNEK282BSuYTEbweszCPSY2o4SycnK9Cd9bZLNtv6LZqoKRPMZ5pkOrW/MzK3LgME1iWeD9BPHbPoAst7BMi3apDrTd/diGANmhlrMeT5kQMvw0VVGITiPVJdYItgfI84m4cdXx9MRoZuGZqPJNSZEMaxdJpLueKYwdRAgMBAAE=
    """

    static func check(installedVersion: String) async throws -> MacUpdateCheckResult {
        let installed = try MacStableVersion(installedVersion)
        async let manifestData = downloadBoundedData(
            from: manifestURL,
            maximumBytes: maximumManifestBytes
        )
        async let signatureData = downloadBoundedData(
            from: signatureURL,
            maximumBytes: 4096
        )
        let latest = try validatedRelease(
            manifestData: await manifestData,
            signatureData: await signatureData
        )
        return try classify(installed: installed, latest: latest)
    }

    static func classify(
        installed: MacStableVersion,
        latest: ValidatedMacRelease
    ) throws -> MacUpdateCheckResult {
        if latest.version > installed {
            guard latest.asset != nil else { throw MacUpdateCheckError.missingMacRelease }
            return .available(latest)
        }
        if latest.version == installed { return .current(latest) }
        return .developmentBuild(installed: installed, latest: latest)
    }

    static func validatedRelease(
        manifestData: Data,
        signatureData: Data
    ) throws -> ValidatedMacRelease {
        try validatedRelease(
            manifestData: manifestData,
            signatureData: signatureData,
            publicKey: productionPublicKey()
        )
    }

    static func validatedRelease(
        manifestData: Data,
        signatureData: Data,
        publicKey: SecKey
    ) throws -> ValidatedMacRelease {
        guard !manifestData.isEmpty, manifestData.count <= maximumManifestBytes else {
            throw MacUpdateCheckError.metadataTooLarge
        }
        guard signatureData.count == signatureBytes,
              SecKeyGetBlockSize(publicKey) == signatureBytes,
              SecKeyIsAlgorithmSupported(
                publicKey,
                .verify,
                .rsaSignatureMessagePKCS1v15SHA256
              )
        else { throw MacUpdateCheckError.invalidSignature }

        var verificationError: Unmanaged<CFError>?
        guard SecKeyVerifySignature(
            publicKey,
            .rsaSignatureMessagePKCS1v15SHA256,
            manifestData as CFData,
            signatureData as CFData,
            &verificationError
        ) else { throw MacUpdateCheckError.invalidSignature }

        let manifest: SignedDesktopUpdateManifest
        do {
            manifest = try JSONDecoder().decode(SignedDesktopUpdateManifest.self, from: manifestData)
        } catch {
            throw MacUpdateCheckError.invalidMetadata
        }
        guard manifest.schemaVersion == 2, manifest.repository == repository else {
            throw MacUpdateCheckError.untrustedResponse
        }

        let version = try MacStableVersion(manifest.releaseVersion)
        let expectedTag = "v\(version)"
        guard manifest.releaseTag == expectedTag,
              isCanonicalUTCTimestamp(manifest.publishedAt),
              let releaseURL = URL(
                string: "https://github.com/\(repository)/releases/tag/\(expectedTag)"
              )
        else { throw MacUpdateCheckError.invalidMetadata }

        let asset: ValidatedMacUpdateAsset?
        if let candidate = manifest.assets[platform] {
            let expectedURL = "https://github.com/\(repository)/releases/download/\(expectedTag)/\(assetName)"
            guard candidate.size > 0,
                  candidate.size <= maximumArchiveBytes,
                  isLowerHexSHA256(candidate.sha256),
                  candidate.url == expectedURL,
                  let downloadURL = URL(string: candidate.url),
                  isTrustedGitHubURL(downloadURL, path: "/\(repository)/releases/download/\(expectedTag)/\(assetName)")
            else { throw MacUpdateCheckError.untrustedResponse }
            asset = ValidatedMacUpdateAsset(
                downloadURL: downloadURL,
                sha256: candidate.sha256,
                size: candidate.size
            )
        } else {
            // Releases published before direct macOS installation remain valid
            // for same-version and development-build comparisons.
            asset = nil
        }

        return ValidatedMacRelease(
            version: version,
            releaseURL: releaseURL,
            publishedAt: manifest.publishedAt,
            asset: asset,
            signedManifest: manifestData,
            manifestSignature: signatureData
        )
    }

    static func productionPublicKey() throws -> SecKey {
        guard let der = Data(base64Encoded: productionPublicKeyPKCS1Base64) else {
            throw MacUpdateCheckError.invalidPublicKey
        }
        let attributes: [CFString: Any] = [
            kSecAttrKeyType: kSecAttrKeyTypeRSA,
            kSecAttrKeyClass: kSecAttrKeyClassPublic,
            kSecAttrKeySizeInBits: 3072,
        ]
        var error: Unmanaged<CFError>?
        guard let key = SecKeyCreateWithData(
            der as CFData,
            attributes as CFDictionary,
            &error
        ), SecKeyGetBlockSize(key) == signatureBytes else {
            throw MacUpdateCheckError.invalidPublicKey
        }
        return key
    }

    private static func downloadBoundedData(
        from url: URL,
        maximumBytes: Int
    ) async throws -> Data {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 20
        configuration.timeoutIntervalForResource = 30
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }

        var request = URLRequest(url: url)
        request.setValue("Lattice-macOS-Updater", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await session.data(for: request)
        try Task.checkCancellation()
        guard let http = response as? HTTPURLResponse else {
            throw MacUpdateCheckError.invalidResponse
        }
        guard http.statusCode == 200 else {
            throw MacUpdateCheckError.httpStatus(http.statusCode)
        }
        guard http.url?.scheme?.lowercased() == "https" else {
            throw MacUpdateCheckError.untrustedResponse
        }
        guard !data.isEmpty, data.count <= maximumBytes else {
            throw MacUpdateCheckError.metadataTooLarge
        }
        return data
    }

    private static func isCanonicalUTCTimestamp(_ value: String) -> Bool {
        guard value.range(
            of: #"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"#,
            options: .regularExpression
        ) != nil else { return false }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: value) != nil
    }

    private static func isLowerHexSHA256(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy {
            ($0 >= 48 && $0 <= 57) || ($0 >= 97 && $0 <= 102)
        }
    }

    private static func isTrustedGitHubURL(_ url: URL, path: String) -> Bool {
        url.scheme == "https"
            && url.host?.lowercased() == "github.com"
            && url.user == nil
            && url.password == nil
            && url.query == nil
            && url.fragment == nil
            && url.path == path
    }
}

private struct SignedDesktopUpdateManifest: Decodable {
    let schemaVersion: Int
    let repository: String
    let releaseVersion: String
    let releaseTag: String
    let publishedAt: String
    let assets: [String: SignedDesktopUpdateAsset]
}

private struct SignedDesktopUpdateAsset: Decodable {
    let url: String
    let sha256: String
    let size: Int64
}

enum MacUpdateCheckError: LocalizedError, Sendable {
    case invalidVersion(String)
    case invalidResponse
    case httpStatus(Int)
    case metadataTooLarge
    case invalidMetadata
    case invalidPublicKey
    case invalidSignature
    case missingMacRelease
    case untrustedResponse

    var errorDescription: String? {
        switch self {
        case .invalidVersion(let value):
            return "Lattice has an invalid installed version: \(value)."
        case .invalidResponse:
            return "GitHub returned an invalid response. Check your connection and try again."
        case .httpStatus(let status):
            return "GitHub returned HTTP status \(status). Check your connection and try again."
        case .metadataTooLarge:
            return "GitHub returned update metadata outside Lattice's safety limit."
        case .invalidMetadata:
            return "The latest signed release has invalid version metadata."
        case .invalidPublicKey:
            return "Lattice's embedded update verification key is invalid."
        case .invalidSignature:
            return "The latest release could not be authenticated by Lattice."
        case .missingMacRelease:
            return "The latest signed Lattice release does not include a direct macOS update."
        case .untrustedResponse:
            return "The signed update points to an unexpected repository or download location."
        }
    }
}
