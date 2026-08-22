import Foundation

@main
struct UpdateManifestSmoke {
    static func main() throws {
        let commit = "0123456789abcdef0123456789abcdef01234567"
        let digest = String(repeating: "a", count: 64)
        let json = """
        {
          "schemaVersion": 1,
          "repository": "dreichner2/cs-library",
          "channel": "main",
          "commit": "\(commit)",
          "publishedAt": "2026-08-21T12:00:00Z",
          "assets": {
            "macos-universal": {
              "url": "https://github.com/dreichner2/cs-library/releases/download/latest-main/Lattice-macOS.zip",
              "sha256": "\(digest)",
              "size": 42
            }
          }
        }
        """

        let manifest = try JSONDecoder().decode(DesktopUpdateManifest.self, from: Data(json.utf8))
        let asset = try manifest.validatedAsset(
            platform: "macos-universal",
            expectedRepository: "dreichner2/cs-library",
            expectedChannel: "main"
        )
        precondition(manifest.commit == commit)
        precondition(asset.size == 42)
        precondition(DesktopUpdateManifest.isFullCommit(commit))
        precondition(!DesktopUpdateManifest.isFullCommit("abc123"))

        let untrusted = DesktopUpdateManifest(
            schemaVersion: 1,
            repository: manifest.repository,
            channel: manifest.channel,
            commit: manifest.commit,
            publishedAt: manifest.publishedAt,
            assets: [
                "macos-universal": DesktopUpdateAsset(
                    url: URL(string: "https://example.com/fake.zip")!,
                    sha256: digest,
                    size: 42
                )
            ]
        )
        do {
            _ = try untrusted.validatedAsset(
                platform: "macos-universal",
                expectedRepository: "dreichner2/cs-library",
                expectedChannel: "main"
            )
            fatalError("Untrusted update URL was accepted")
        } catch UpdateManifestError.untrustedAssetURL {
            // Expected.
        }
    }
}
