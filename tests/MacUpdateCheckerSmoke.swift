import Foundation

@main
struct MacUpdateCheckerSmoke {
    static func main() throws {
        let payload = """
        {
          "tag_name": "v2.2.0",
          "html_url": "https://github.com/dreichner2/Lattice/releases/tag/v2.2.0",
          "draft": false,
          "prerelease": false,
          "assets": [
            {
              "name": "Lattice-macOS.zip",
              "browser_download_url": "https://github.com/dreichner2/Lattice/releases/download/v2.2.0/Lattice-macOS.zip"
            }
          ]
        }
        """
        let release = try MacUpdateChecker.validatedRelease(from: Data(payload.utf8))
        precondition(release.version.description == "2.2.0")
        precondition(release.downloadURL.lastPathComponent == "Lattice-macOS.zip")

        switch MacUpdateChecker.classify(
            installed: try MacStableVersion("2.1.1"),
            latest: release
        ) {
        case .available(let available):
            precondition(available.version == release.version)
        default:
            fatalError("A newer stable release was not classified as available")
        }

        switch MacUpdateChecker.classify(
            installed: try MacStableVersion("2.2.0"),
            latest: release
        ) {
        case .current:
            break
        default:
            fatalError("An equal stable release was not classified as current")
        }

        do {
            _ = try MacStableVersion("02.2.0")
            fatalError("A leading-zero version was accepted")
        } catch MacUpdateCheckError.invalidVersion {
            // Expected.
        }

        let untrusted = payload.replacingOccurrences(
            of: "https://github.com/dreichner2/Lattice/releases/download/v2.2.0/Lattice-macOS.zip",
            with: "https://example.com/Lattice-macOS.zip"
        )
        do {
            _ = try MacUpdateChecker.validatedRelease(from: Data(untrusted.utf8))
            fatalError("An untrusted download URL was accepted")
        } catch MacUpdateCheckError.untrustedResponse {
            // Expected.
        }

        print("Mac update checker smoke test passed")
    }
}
