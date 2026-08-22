import Foundation
import WebKit

final class ReaderBridge: NSObject, WKScriptMessageHandlerWithReply {
    static let handlerName = "csLibraryReader"

    static let bootstrapUserScript = WKUserScript(
        source: """
        (() => {
          if (window.top !== window || window.csLibraryNativeCall) return;
          window.csLibraryNativeCall = (action, payload = {}) => {
            const handler = window.webkit?.messageHandlers?.\(handlerName);
            if (!handler) return Promise.reject(new Error('Lattice native bridge is unavailable'));
            return handler.postMessage({ action, payload });
          };
          window.dispatchEvent(new CustomEvent('cs-library-native-ready'));
        })();
        """,
        injectionTime: .atDocumentStart,
        forMainFrameOnly: true
    )

    static func workspaceUserScript(libraryRoot: URL) -> WKUserScript? {
        let sourceURL = Bundle.main.url(forResource: "LibraryWorkspace", withExtension: "js")
            ?? libraryRoot.appendingPathComponent("native/LibraryWorkspace.js")
        guard let source = try? String(contentsOf: sourceURL, encoding: .utf8) else { return nil }
        return WKUserScript(source: source, injectionTime: .atDocumentEnd, forMainFrameOnly: true)
    }

    private let store: ReaderStore
    private var activeSessionID: String?
    private var activeDocumentID: String?
    var appInfoProvider: (() -> [String: Any])?
    var appActionHandler: ((String) -> Void)?
    weak var coordinator: ImmersiveReaderCoordinator?
    weak var webView: WKWebView?

    init(store: ReaderStore) {
        self.store = store
        super.init()
    }

    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage,
        replyHandler: @escaping (Any?, String?) -> Void
    ) {
        guard message.frameInfo.isMainFrame, isLocalLibraryURL(message.frameInfo.request.url) else {
            replyHandler(nil, "Reader bridge requests are accepted only from the main library page")
            return
        }
        guard
            let request = message.body as? [String: Any],
            let action = request["action"] as? String,
            let payload = request["payload"] as? [String: Any]
        else {
            replyHandler(nil, "Malformed reader bridge request")
            return
        }

        do {
            replyHandler(try handle(action: action, payload: payload), nil)
        } catch {
            replyHandler(nil, error.localizedDescription)
        }
    }

    func finishWebSession() {
        guard let id = activeSessionID else { return }
        try? store.finishSession(id: id)
        activeSessionID = nil
        activeDocumentID = nil
    }

    private func handle(action: String, payload: [String: Any]) throws -> Any {
        switch action {
        case "ping":
            return ["ok": true, "protocolVersion": LibraryIdentity.protocolVersion]

        case "app.info":
            guard let appInfoProvider else { throw BridgeError.unavailable("app.info") }
            return appInfoProvider()

        case "app.checkForUpdates", "app.moveLibrary":
            guard let appActionHandler else { throw BridgeError.unavailable(action) }
            appActionHandler(action)
            return ["started": true]

        case "document.upsert":
            let document = try document(from: payload)
            try store.upsertDocument(document)
            try activate(documentID: document.id)
            return try object(document)

        case "document.open":
            guard let path = string(payload, "path") else { throw BridgeError.missing("path") }
            return ["opened": coordinator?.openDocument(relativePath: path) == true]

        case "position.get":
            guard let documentID = string(payload, "documentId") else { throw BridgeError.missing("documentId") }
            return try store.position(documentID: documentID).map(object) ?? NSNull()

        case "position.save":
            let documentID = try requiredString(payload, "documentId")
            let position = ReaderPosition(
                documentID: documentID,
                locator: try locatorString(payload["locator"]),
                page: integer(payload, "page"),
                progress: min(max(number(payload, "progress") ?? 0, 0), 1),
                updatedAt: number(payload, "updatedAt") ?? Date().timeIntervalSince1970
            )
            try store.savePosition(position)
            return try object(position)

        case "bookmark.list":
            return try object(store.bookmarks(documentID: string(payload, "documentId")))

        case "bookmark.save":
            let documentID = try requiredString(payload, "documentId")
            let locator = try locatorString(payload["locator"])
            let bookmark = ReaderBookmark(
                id: string(payload, "id") ?? stableID(prefix: "bookmark", documentID: documentID, locator: locator),
                documentID: documentID,
                locator: locator,
                label: string(payload, "label") ?? "Saved position",
                createdAt: number(payload, "createdAt") ?? Date().timeIntervalSince1970
            )
            try store.saveBookmark(bookmark)
            return try object(bookmark)

        case "bookmark.delete":
            try store.deleteBookmark(id: requiredString(payload, "id"))
            return ["ok": true]

        case "annotation.list":
            return try object(store.annotations(documentID: string(payload, "documentId")))

        case "annotation.save":
            let now = Date().timeIntervalSince1970
            let documentID = try requiredString(payload, "documentId")
            let locator = try locatorString(payload["locator"])
            let annotation = ReaderAnnotation(
                id: string(payload, "id") ?? UUID().uuidString.lowercased(),
                documentID: documentID,
                locator: locator,
                quote: (string(payload, "quote") ?? "").prefixString(20_000),
                note: (string(payload, "note") ?? "").prefixString(100_000),
                color: string(payload, "color") ?? "yellow",
                createdAt: number(payload, "createdAt") ?? now,
                updatedAt: now
            )
            try store.saveAnnotation(annotation)
            return try object(annotation)

        case "annotation.delete":
            try store.deleteAnnotation(id: requiredString(payload, "id"))
            return ["ok": true]

        case "session.start":
            let documentID = try requiredString(payload, "documentId")
            try activate(documentID: documentID)
            return ["id": activeSessionID ?? ""]

        case "session.finish":
            let id = string(payload, "id") ?? activeSessionID
            if let id { try store.finishSession(id: id, pagesRead: integer(payload, "pagesRead") ?? 0) }
            if id == activeSessionID { activeSessionID = nil; activeDocumentID = nil }
            return ["ok": true]

        case "preference.get":
            let key = try requiredString(payload, "key")
            let value: Any = try store.preference(key: key) ?? NSNull()
            return ["key": key, "value": value] as [String: Any]

        case "preference.set":
            let key = try requiredString(payload, "key")
            let value = try requiredString(payload, "value")
            try store.setPreference(key: key, value: value)
            return ["ok": true]

        case "search.index":
            let documentID = try requiredString(payload, "documentId")
            let rawItems = payload["items"] as? [[String: Any]] ?? []
            let now = Date().timeIntervalSince1970
            let items = rawItems.prefix(10_000).compactMap { item -> ReaderSearchItem? in
                guard let id = string(item, "id") else { return nil }
                return ReaderSearchItem(
                    id: "content:\(documentID):\(id)", documentID: documentID, kind: string(item, "kind") ?? "content",
                    title: (string(item, "title") ?? "").prefixString(2_000),
                    body: (string(item, "body") ?? "").prefixString(200_000), updatedAt: now
                )
            }
            try store.indexSearchItems(items)
            return ["indexed": items.count]

        case "search.query":
            return try object(store.search(try requiredString(payload, "query"), limit: integer(payload, "limit") ?? 50))

        case "diagnostics":
            return try object(store.diagnostics())

        default:
            throw BridgeError.unknown(action)
        }
    }

    private func document(from payload: [String: Any]) throws -> ReaderDocument {
        let path = try requiredString(payload, "path")
        guard isSafeReaderPath(path) else { throw BridgeError.invalid("path") }
        let workID = string(payload, "workId")
        let digest = string(payload, "sha256")
        return ReaderDocument(
            id: string(payload, "id") ?? LibraryIdentity.documentID(workID: workID, path: path, sha256: digest),
            workID: workID, path: path, sha256: digest,
            title: string(payload, "title") ?? URL(fileURLWithPath: path).deletingPathExtension().lastPathComponent,
            format: string(payload, "format") ?? URL(fileURLWithPath: path).pathExtension.lowercased(),
            updatedAt: Date().timeIntervalSince1970
        )
    }

    private func activate(documentID: String) throws {
        guard activeDocumentID != documentID || activeSessionID == nil else { return }
        finishWebSession()
        activeSessionID = try store.startSession(documentID: documentID).id
        activeDocumentID = documentID
    }

    private func locatorString(_ value: Any?) throws -> String {
        if let value = value as? String { return value.prefixString(20_000) }
        let object = value ?? [:]
        guard JSONSerialization.isValidJSONObject(object) else { throw BridgeError.invalid("locator") }
        return String(data: try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]), encoding: .utf8) ?? "{}"
    }

    private func object<T: Encodable>(_ value: T) throws -> Any {
        let data = try JSONEncoder().encode(value)
        return try JSONSerialization.jsonObject(with: data)
    }

    private func requiredString(_ payload: [String: Any], _ key: String) throws -> String {
        guard let value = string(payload, key), !value.isEmpty else { throw BridgeError.missing(key) }
        return value
    }

    private func string(_ payload: [String: Any], _ key: String) -> String? {
        (payload[key] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func integer(_ payload: [String: Any], _ key: String) -> Int? {
        (payload[key] as? NSNumber)?.intValue
    }

    private func number(_ payload: [String: Any], _ key: String) -> Double? {
        (payload[key] as? NSNumber)?.doubleValue
    }

    private func stableID(prefix: String, documentID: String, locator: String) -> String {
        LibraryIdentity.documentID(workID: "\(prefix):\(documentID):\(locator)", path: locator)
    }

    private func isLocalLibraryURL(_ url: URL?) -> Bool {
        guard let url, let host = url.host?.lowercased() else { return false }
        return (url.scheme == "http" || url.scheme == "https")
            && ["127.0.0.1", "localhost", "::1"].contains(host)
    }

    private func isSafeReaderPath(_ path: String) -> Bool {
        LibraryIdentity.isReadableRelativePath(path)
    }
}

private enum BridgeError: LocalizedError {
    case missing(String)
    case invalid(String)
    case unavailable(String)
    case unknown(String)

    var errorDescription: String? {
        switch self {
        case .missing(let key): return "Missing bridge value: \(key)"
        case .invalid(let key): return "Invalid bridge value: \(key)"
        case .unavailable(let action): return "Native app action is unavailable: \(action)"
        case .unknown(let action): return "Unknown reader bridge action: \(action)"
        }
    }
}

private extension String {
    func prefixString(_ length: Int) -> String { String(prefix(length)) }
}
