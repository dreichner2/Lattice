import CryptoKit
import Foundation

enum LibraryIdentity {
    static let protocolVersion = 4
    private static let readableExtensions = Set(["pdf", "epub", "txt"])
    private static let readableRoots = Set(["books", "papers", "lectures"])
    private static let audioExtensions = Set(["mp3", "m4a", "wav", "flac"])
    private static let payloadExtensions = readableExtensions.union(audioExtensions)
    private static let payloadRoots = readableRoots.union(["audio"])

    static func canonicalRoot(_ root: URL) -> URL {
        root.standardizedFileURL.resolvingSymlinksInPath()
    }

    static func libraryID(for root: URL) -> String {
        sha256("cs-library:\(canonicalRoot(root).path)")
    }

    static func documentID(workID: String?, path: String, sha256 digest: String? = nil) -> String {
        let hash = digest?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
        // Reader state belongs to a concrete payload, not the catalog work that
        // happens to contain it. A single work can legitimately expose both a
        // PDF and an EPUB; keying by work would mix their positions and notes.
        // Prefer the digest so state follows an unchanged file when it moves.
        let identity = !hash.isEmpty ? "sha256:\(hash)" : "path:\(normalizedRelativePath(path))"
        return sha256("cs-library-document:\(identity)")
    }

    static func legacyWorkDocumentID(workID: String?) -> String? {
        let work = workID?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return work.isEmpty ? nil : sha256("cs-library-document:work:\(work)")
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
        guard isReadableRelativePath(normalized) else { return nil }

        return resolveContainedPayload(normalized, root: root, extensions: readableExtensions)
    }

    static func resolveLibraryPayload(relativePath: String, root: URL) -> URL? {
        let normalized = normalizedRelativePath(relativePath)
        guard isLibraryPayloadRelativePath(normalized) else { return nil }

        return resolveContainedPayload(normalized, root: root, extensions: payloadExtensions)
    }

    private static func resolveContainedPayload(
        _ normalized: String,
        root: URL,
        extensions: Set<String>
    ) -> URL? {

        let canonical = canonicalRoot(root)
        let candidate = canonical.appendingPathComponent(normalized).standardizedFileURL.resolvingSymlinksInPath()
        let rootPrefix = canonical.path.hasSuffix("/") ? canonical.path : canonical.path + "/"
        guard
            candidate.path.hasPrefix(rootPrefix),
            extensions.contains(candidate.pathExtension.lowercased()),
            FileManager.default.fileExists(atPath: candidate.path)
        else { return nil }
        return candidate
    }

    static func isReadableRelativePath(_ value: String) -> Bool {
        let normalized = normalizedRelativePath(value)
        return isSafeRelativePath(normalized, roots: readableRoots)
            && readableExtensions.contains(URL(fileURLWithPath: normalized).pathExtension.lowercased())
    }

    static func isLibraryPayloadRelativePath(_ value: String) -> Bool {
        let normalized = normalizedRelativePath(value)
        guard isSafeRelativePath(normalized, roots: payloadRoots) else { return false }
        let pieces = normalized.split(separator: "/", omittingEmptySubsequences: false)
        let root = String(pieces[0])
        let fileExtension = URL(fileURLWithPath: normalized).pathExtension.lowercased()
        if root == "audio" {
            return audioExtensions.contains(fileExtension)
        }
        return readableRoots.contains(root) && readableExtensions.contains(fileExtension)
    }

    static func relativePath(for file: URL, root: URL) -> String? {
        let canonical = canonicalRoot(root)
        let candidate = file.standardizedFileURL.resolvingSymlinksInPath()
        let prefix = canonical.path.hasSuffix("/") ? canonical.path : canonical.path + "/"
        guard candidate.path.hasPrefix(prefix) else { return nil }
        let relative = String(candidate.path.dropFirst(prefix.count))
        return resolveLibraryFile(relativePath: relative, root: canonical) == candidate ? relative : nil
    }

    static func relativePayloadPath(for file: URL, root: URL) -> String? {
        let canonical = canonicalRoot(root)
        let candidate = file.standardizedFileURL.resolvingSymlinksInPath()
        let prefix = canonical.path.hasSuffix("/") ? canonical.path : canonical.path + "/"
        guard candidate.path.hasPrefix(prefix) else { return nil }
        let relative = String(candidate.path.dropFirst(prefix.count))
        return resolveLibraryPayload(relativePath: relative, root: canonical) == candidate ? relative : nil
    }

    static func sameHTTPOrigin(_ first: URL?, _ second: URL?) -> Bool {
        guard
            let first,
            let second,
            let firstScheme = first.scheme?.lowercased(),
            let secondScheme = second.scheme?.lowercased(),
            let firstHost = first.host?.lowercased(),
            let secondHost = second.host?.lowercased(),
            !firstHost.isEmpty,
            ["http", "https"].contains(firstScheme),
            firstScheme == secondScheme,
            firstHost == secondHost
        else { return false }
        func effectivePort(_ url: URL, scheme: String) -> Int {
            url.port ?? (scheme == "https" ? 443 : 80)
        }
        return effectivePort(first, scheme: firstScheme)
            == effectivePort(second, scheme: secondScheme)
    }

    private static func normalizedRelativePath(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "/")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func isSafeRelativePath(_ normalized: String, roots: Set<String>) -> Bool {
        guard !normalized.isEmpty, !normalized.hasPrefix("/"), !normalized.contains("\0") else { return false }
        let pieces = normalized.split(separator: "/", omittingEmptySubsequences: false)
        return pieces.count >= 2
            && pieces.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." })
            && roots.contains(String(pieces[0]))
    }

    private static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}
