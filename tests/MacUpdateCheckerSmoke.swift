import Foundation
import Security

@main
struct MacUpdateCheckerSmoke {
    static func main() throws {
        let attributes: [CFString: Any] = [
            kSecAttrKeyType: kSecAttrKeyTypeRSA,
            kSecAttrKeySizeInBits: 3072,
        ]
        var keyError: Unmanaged<CFError>?
        guard let privateKey = SecKeyCreateRandomKey(attributes as CFDictionary, &keyError),
              let publicKey = SecKeyCopyPublicKey(privateKey) else {
            fatalError("Could not create the updater smoke-test key")
        }

        let payload = manifest(includeMac: true)
        let signature = try sign(payload, with: privateKey)
        let release = try MacUpdateChecker.validatedRelease(
            manifestData: payload,
            signatureData: signature,
            publicKey: publicKey
        )
        precondition(release.version.description == "2.3.0")
        precondition(release.asset?.downloadURL.lastPathComponent == "Lattice-macOS.zip")
        precondition(release.asset?.sha256 == String(repeating: "a", count: 64))
        precondition(release.asset?.size == 4_194_304)

        switch try MacUpdateChecker.classify(
            installed: try MacStableVersion("2.2.0"),
            latest: release
        ) {
        case .available(let available):
            precondition(available.version == release.version)
        default:
            fatalError("A newer signed release was not classified as available")
        }

        switch try MacUpdateChecker.classify(
            installed: try MacStableVersion("2.3.0"),
            latest: release
        ) {
        case .current:
            break
        default:
            fatalError("An equal signed release was not classified as current")
        }

        do {
            _ = try MacStableVersion("02.3.0")
            fatalError("A leading-zero version was accepted")
        } catch MacUpdateCheckError.invalidVersion {
            // Expected.
        }

        var tampered = payload
        tampered[tampered.startIndex] ^= 1
        do {
            _ = try MacUpdateChecker.validatedRelease(
                manifestData: tampered,
                signatureData: signature,
                publicKey: publicKey
            )
            fatalError("Tampered manifest bytes passed their signature check")
        } catch MacUpdateCheckError.invalidSignature {
            // Expected.
        }

        let untrusted = Data(
            String(decoding: payload, as: UTF8.self)
                .replacingOccurrences(
                    of: "https://github.com/dreichner2/Lattice/releases/download/v2.3.0/Lattice-macOS.zip",
                    with: "https://example.com/Lattice-macOS.zip"
                )
                .utf8
        )
        do {
            _ = try MacUpdateChecker.validatedRelease(
                manifestData: untrusted,
                signatureData: try sign(untrusted, with: privateKey),
                publicKey: publicKey
            )
            fatalError("A signed but untrusted download URL was accepted")
        } catch MacUpdateCheckError.untrustedResponse {
            // Expected.
        }

        let legacyPayload = manifest(includeMac: false)
        let legacy = try MacUpdateChecker.validatedRelease(
            manifestData: legacyPayload,
            signatureData: try sign(legacyPayload, with: privateKey),
            publicKey: publicKey
        )
        precondition(legacy.asset == nil)
        if case .current = try MacUpdateChecker.classify(
            installed: try MacStableVersion("2.3.0"),
            latest: legacy
        ) {
            // Same-version manifests from before direct Mac updates remain valid.
        } else {
            fatalError("A legacy same-version manifest was rejected")
        }
        do {
            _ = try MacUpdateChecker.classify(
                installed: try MacStableVersion("2.2.0"),
                latest: legacy
            )
            fatalError("A newer release without a Mac asset was installable")
        } catch MacUpdateCheckError.missingMacRelease {
            // Expected.
        }

        let productionKey = try MacUpdateChecker.productionPublicKey()
        precondition(SecKeyGetBlockSize(productionKey) == 384)
        print("Mac signed update checker smoke test passed")
    }

    private static func manifest(includeMac: Bool) -> Data {
        let mac = includeMac ? """
        ,
            "macos-arm64": {
              "sha256": "\(String(repeating: "a", count: 64))",
              "size": 4194304,
              "url": "https://github.com/dreichner2/Lattice/releases/download/v2.3.0/Lattice-macOS.zip"
            }
        """ : ""
        return Data(
            """
            {
              "assets": {
                "windows-x64": {
                  "sha256": "\(String(repeating: "b", count: 64))",
                  "size": 100000000,
                  "url": "https://github.com/dreichner2/Lattice/releases/download/v2.3.0/Lattice-Windows-win-x64.zip"
                }\(mac)
              },
              "publishedAt": "2026-08-22T18:00:00Z",
              "releaseTag": "v2.3.0",
              "releaseVersion": "2.3.0",
              "repository": "dreichner2/Lattice",
              "schemaVersion": 2
            }
            """.utf8
        )
    }

    private static func sign(_ data: Data, with privateKey: SecKey) throws -> Data {
        var error: Unmanaged<CFError>?
        guard let signature = SecKeyCreateSignature(
            privateKey,
            .rsaSignatureMessagePKCS1v15SHA256,
            data as CFData,
            &error
        ) as Data? else {
            throw error!.takeRetainedValue()
        }
        return signature
    }
}
