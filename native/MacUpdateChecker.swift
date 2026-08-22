import Foundation

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

struct ValidatedMacRelease: Sendable {
    let version: MacStableVersion
    let releaseURL: URL
    let downloadURL: URL
}

enum MacUpdateCheckResult: Sendable {
    case current(ValidatedMacRelease)
    case available(ValidatedMacRelease)
    case developmentBuild(installed: MacStableVersion, latest: ValidatedMacRelease)
}

enum MacUpdateChecker {
    static let repository = "dreichner2/Lattice"
    static let assetName = "Lattice-macOS.zip"
    static let latestReleaseURL = URL(
        string: "https://api.github.com/repos/dreichner2/Lattice/releases/latest"
    )!
    static let maximumMetadataBytes = 512 * 1024

    static func check(installedVersion: String) async throws -> MacUpdateCheckResult {
        let installed = try MacStableVersion(installedVersion)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 20
        configuration.timeoutIntervalForResource = 30
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }

        var request = URLRequest(url: latestReleaseURL)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("Lattice-macOS-Update-Check", forHTTPHeaderField: "User-Agent")
        let (data, response) = try await session.data(for: request)
        try Task.checkCancellation()
        guard let http = response as? HTTPURLResponse else {
            throw MacUpdateCheckError.invalidResponse
        }
        guard http.statusCode == 200 else {
            throw MacUpdateCheckError.httpStatus(http.statusCode)
        }
        guard http.url?.scheme == "https",
              http.url?.host?.lowercased() == "api.github.com",
              http.url?.path == latestReleaseURL.path
        else { throw MacUpdateCheckError.untrustedResponse }
        guard !data.isEmpty, data.count <= maximumMetadataBytes else {
            throw MacUpdateCheckError.metadataTooLarge
        }

        let latest = try validatedRelease(from: data)
        return classify(installed: installed, latest: latest)
    }

    static func classify(
        installed: MacStableVersion,
        latest: ValidatedMacRelease
    ) -> MacUpdateCheckResult {
        if latest.version > installed { return .available(latest) }
        if latest.version == installed { return .current(latest) }
        return .developmentBuild(installed: installed, latest: latest)
    }

    static func validatedRelease(from data: Data) throws -> ValidatedMacRelease {
        let release: GitHubRelease
        do {
            release = try JSONDecoder().decode(GitHubRelease.self, from: data)
        } catch {
            throw MacUpdateCheckError.invalidMetadata
        }
        guard !release.draft, !release.prerelease, release.tagName.hasPrefix("v") else {
            throw MacUpdateCheckError.invalidMetadata
        }
        let version = try MacStableVersion(String(release.tagName.dropFirst()))
        guard release.tagName == "v\(version)",
              isTrustedGitHubURL(
                release.htmlURL,
                path: "/\(repository)/releases/tag/\(release.tagName)"
              )
        else { throw MacUpdateCheckError.untrustedResponse }

        let matchingAssets = release.assets.filter { $0.name == assetName }
        guard matchingAssets.count == 1 else { throw MacUpdateCheckError.missingMacRelease }
        let downloadURL = matchingAssets[0].browserDownloadURL
        guard isTrustedGitHubURL(
            downloadURL,
            path: "/\(repository)/releases/download/\(release.tagName)/\(assetName)"
        ) else { throw MacUpdateCheckError.untrustedResponse }
        return ValidatedMacRelease(
            version: version,
            releaseURL: release.htmlURL,
            downloadURL: downloadURL
        )
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

private struct GitHubRelease: Decodable {
    let tagName: String
    let htmlURL: URL
    let draft: Bool
    let prerelease: Bool
    let assets: [GitHubReleaseAsset]

    enum CodingKeys: String, CodingKey {
        case tagName = "tag_name"
        case htmlURL = "html_url"
        case draft
        case prerelease
        case assets
    }
}

private struct GitHubReleaseAsset: Decodable {
    let name: String
    let browserDownloadURL: URL

    enum CodingKeys: String, CodingKey {
        case name
        case browserDownloadURL = "browser_download_url"
    }
}

enum MacUpdateCheckError: LocalizedError, Sendable {
    case invalidVersion(String)
    case invalidResponse
    case httpStatus(Int)
    case metadataTooLarge
    case invalidMetadata
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
            return "GitHub returned unexpectedly large release metadata."
        case .invalidMetadata:
            return "The latest GitHub release has invalid version metadata."
        case .missingMacRelease:
            return "The latest Lattice release does not include the macOS application yet."
        case .untrustedResponse:
            return "The update check returned an unexpected GitHub location."
        }
    }
}
