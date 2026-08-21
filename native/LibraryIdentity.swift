import CryptoKit
import Foundation

enum LibraryIdentity {
    static let protocolVersion = 2

    static func id(for root: URL) -> String {
        let canonical = root
            .resolvingSymlinksInPath()
            .standardizedFileURL
            .path
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let digest = SHA256.hash(data: Data(("/" + canonical).utf8))
        return digest.map { String(format: "%02x", $0) }.joined()
    }
}
