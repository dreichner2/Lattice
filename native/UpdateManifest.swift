import Foundation

struct DesktopUpdateAsset: Codable, Equatable, Sendable {
    let url: URL
    let sha256: String
    let size: Int64
}

struct DesktopUpdateManifest: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let repository: String
    let channel: String
    let commit: String
    let publishedAt: String
    let assets: [String: DesktopUpdateAsset]

    func validatedAsset(
        platform: String,
        expectedRepository: String,
        expectedChannel: String
    ) throws -> DesktopUpdateAsset {
        guard schemaVersion == 1 else { throw UpdateManifestError.unsupportedSchema(schemaVersion) }
        guard repository == expectedRepository else { throw UpdateManifestError.unexpectedRepository }
        guard channel == expectedChannel else { throw UpdateManifestError.unexpectedChannel }
        guard Self.isFullCommit(commit) else { throw UpdateManifestError.invalidCommit }
        guard ISO8601DateFormatter().date(from: publishedAt) != nil else {
            throw UpdateManifestError.invalidPublishedDate
        }
        guard let asset = assets[platform] else { throw UpdateManifestError.missingPlatform(platform) }
        guard asset.size > 0, asset.size <= 1_073_741_824 else { throw UpdateManifestError.invalidAssetSize }
        guard Self.isSHA256(asset.sha256) else { throw UpdateManifestError.invalidDigest }
        guard
            asset.url.scheme == "https",
            asset.url.host?.lowercased() == "github.com",
            asset.url.user == nil,
            asset.url.password == nil,
            asset.url.query == nil,
            asset.url.fragment == nil,
            asset.url.path.hasPrefix("/\(expectedRepository)/releases/download/latest-main/")
        else { throw UpdateManifestError.untrustedAssetURL }
        return asset
    }

    static func isFullCommit(_ value: String) -> Bool {
        value.count == 40 && value.allSatisfy { $0.isHexDigit && !$0.isUppercase }
    }

    static func isSHA256(_ value: String) -> Bool {
        value.count == 64 && value.allSatisfy { $0.isHexDigit && !$0.isUppercase }
    }
}

struct GitHubBranchCommit: Codable, Equatable, Sendable {
    let sha: String
}

enum UpdateManifestError: LocalizedError, Equatable, Sendable {
    case unsupportedSchema(Int)
    case unexpectedRepository
    case unexpectedChannel
    case invalidCommit
    case invalidPublishedDate
    case missingPlatform(String)
    case invalidAssetSize
    case invalidDigest
    case untrustedAssetURL

    var errorDescription: String? {
        switch self {
        case .unsupportedSchema(let version):
            return "The update metadata uses unsupported schema \(version)."
        case .unexpectedRepository:
            return "The update metadata belongs to a different repository."
        case .unexpectedChannel:
            return "The update metadata belongs to a different update channel."
        case .invalidCommit:
            return "The update metadata does not contain a full Git commit."
        case .invalidPublishedDate:
            return "The update metadata has an invalid publication time."
        case .missingPlatform(let platform):
            return "The update does not include the required \(platform) application."
        case .invalidAssetSize:
            return "The update archive has an invalid size."
        case .invalidDigest:
            return "The update archive has an invalid SHA-256 digest."
        case .untrustedAssetURL:
            return "The update archive is not hosted at the expected GitHub release location."
        }
    }
}
