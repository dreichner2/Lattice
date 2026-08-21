import CryptoKit
import Foundation

enum LibraryIdentity {
    static let protocolVersion = 2
    private static let readableExtensions = Set(["pdf", "epub", "txt"])
    private static let readableRoots = Set(["books", "papers"])

    static func canonicalRoot(_ root: URL) -> URL {
        root.standardizedFileURL.resolvingSymlinksInPath()
    }

    static func libraryID(for root: URL) -> String {
        sha256("cs-library:\(canonicalRoot(root).path)")
    }

    static func documentID(workID: String?, path: String, sha256 digest: String? = nil) -> String {
        let work = workID?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let hash = digest?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
        let identity = !work.isEmpty ? "work:\(work)" : (!hash.isEmpty ? "sha256:\(hash)" : "path:\(normalizedRelativePath(path))")
        return sha256("cs-library-document:\(identity)")
    }

    static func fileSHA256(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while true {
            let chunk = try handle.read(upToCount: 1_048_576) ?? Data()
            if chunk.isEmpty { break }
            hasher.update(data: chunk)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    static func resolveLibraryFile(relativePath: String, root: URL) -> URL? {
        let normalized = normalizedRelativePath(relativePath)
        guard !normalized.isEmpty, !normalized.hasPrefix("/"), !normalized.contains("\0") else { return nil }
        let pieces = normalized.split(separator: "/", omittingEmptySubsequences: false)
        guard
            pieces.count >= 2,
            pieces.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }),
            readableRoots.contains(String(pieces[0]))
        else { return nil }

        let canonical = canonicalRoot(root)
        let candidate = canonical.appendingPathComponent(normalized).standardizedFileURL.resolvingSymlinksInPath()
        let rootPrefix = canonical.path.hasSuffix("/") ? canonical.path : canonical.path + "/"
        guard
            candidate.path.hasPrefix(rootPrefix),
            readableExtensions.contains(candidate.pathExtension.lowercased()),
            FileManager.default.fileExists(atPath: candidate.path)
        else { return nil }
        return candidate
    }

    static func relativePath(for file: URL, root: URL) -> String? {
        let canonical = canonicalRoot(root)
        let candidate = file.standardizedFileURL.resolvingSymlinksInPath()
        let prefix = canonical.path.hasSuffix("/") ? canonical.path : canonical.path + "/"
        guard candidate.path.hasPrefix(prefix) else { return nil }
        let relative = String(candidate.path.dropFirst(prefix.count))
        return resolveLibraryFile(relativePath: relative, root: canonical) == candidate ? relative : nil
    }

    private static func normalizedRelativePath(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "/")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
