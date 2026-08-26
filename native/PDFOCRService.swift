import AppKit
import Foundation
import PDFKit
import Vision

/// Produces a selectable-text overlay for image-only PDF pages without
/// modifying the source publication. Recognition stays entirely on-device.
final class PDFOCRService {
    private struct CacheKey: Hashable {
        let path: String
        let page: Int
        let modifiedAt: TimeInterval
        let fileSize: Int
    }

    private let libraryRoot: URL
    private let workQueue = DispatchQueue(label: "app.lattice.pdf-ocr", qos: .userInitiated)
    private let cacheLock = NSLock()
    private var cache: [CacheKey: [[String: Any]]] = [:]
    private var cacheOrder: [CacheKey] = []
    private let maximumCachedPages = 96

    init(libraryRoot: URL) {
        self.libraryRoot = LibraryIdentity.canonicalRoot(libraryRoot).resolvingSymlinksInPath()
    }

    func recognize(
        relativePath: String,
        pageNumber: Int,
        completion: @escaping (Result<[String: Any], Error>) -> Void
    ) {
        do {
            let (url, key) = try validatedPDF(relativePath: relativePath, pageNumber: pageNumber)
            if let lines = cachedLines(for: key) {
                completion(.success(["page": pageNumber, "lines": lines, "cached": true]))
                return
            }

            workQueue.async { [self] in
                do {
                    let lines = try self.recognizePage(at: url, pageNumber: pageNumber)
                    self.cache(lines, for: key)
                    completion(.success(["page": pageNumber, "lines": lines, "cached": false]))
                } catch {
                    completion(.failure(error))
                }
            }
        } catch {
            completion(.failure(error))
        }
    }

    private func validatedPDF(relativePath: String, pageNumber: Int) throws -> (URL, CacheKey) {
        guard pageNumber >= 1 else { throw PDFOCRError.invalidPage }
        guard LibraryIdentity.isReadableRelativePath(relativePath), relativePath.lowercased().hasSuffix(".pdf") else {
            throw PDFOCRError.invalidPath
        }

        let url = libraryRoot.appendingPathComponent(relativePath).standardizedFileURL.resolvingSymlinksInPath()
        let rootPath = libraryRoot.path.hasSuffix("/") ? libraryRoot.path : libraryRoot.path + "/"
        guard url.path.hasPrefix(rootPath) else { throw PDFOCRError.invalidPath }

        let values = try url.resourceValues(forKeys: [.isRegularFileKey, .contentModificationDateKey, .fileSizeKey])
        guard values.isRegularFile == true else { throw PDFOCRError.missingFile }
        return (
            url,
            CacheKey(
                path: relativePath,
                page: pageNumber,
                modifiedAt: values.contentModificationDate?.timeIntervalSince1970 ?? 0,
                fileSize: values.fileSize ?? 0
            )
        )
    }

    private func recognizePage(at url: URL, pageNumber: Int) throws -> [[String: Any]] {
        guard let document = PDFDocument(url: url) else { throw PDFOCRError.unreadablePDF }
        guard pageNumber <= document.pageCount, let page = document.page(at: pageNumber - 1) else {
            throw PDFOCRError.invalidPage
        }

        let bounds = page.bounds(for: .mediaBox)
        guard bounds.width > 0, bounds.height > 0 else { throw PDFOCRError.unreadablePage }
        let longestSide: CGFloat = 2_800
        let scale = min(longestSide / max(bounds.width, bounds.height), 4)
        let imageSize = NSSize(
            width: max(1, floor(bounds.width * scale)),
            height: max(1, floor(bounds.height * scale))
        )
        let image = page.thumbnail(of: imageSize, for: .mediaBox)
        var proposedRect = NSRect(origin: .zero, size: image.size)
        guard let cgImage = image.cgImage(forProposedRect: &proposedRect, context: nil, hints: nil) else {
            throw PDFOCRError.unreadablePage
        }

        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = true
        request.minimumTextHeight = 0.006
        if let supported = try? request.supportedRecognitionLanguages() {
            let preferred = ["zh-Hans", "zh-Hant", "en-US"]
            let selected = preferred.filter { supported.contains($0) }
            if !selected.isEmpty { request.recognitionLanguages = selected }
        }

        let handler = VNImageRequestHandler(cgImage: cgImage, orientation: .up)
        try handler.perform([request])
        let observations = request.results ?? []
        let ordered = observations.sorted { left, right in
            let verticalDifference = abs(left.boundingBox.maxY - right.boundingBox.maxY)
            if verticalDifference > 0.012 { return left.boundingBox.maxY > right.boundingBox.maxY }
            return left.boundingBox.minX < right.boundingBox.minX
        }

        return ordered.prefix(2_000).compactMap { observation in
            guard let candidate = observation.topCandidates(1).first else { return nil }
            let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
            let box = observation.boundingBox
            guard !text.isEmpty, box.width > 0, box.height > 0 else { return nil }
            return [
                "text": String(text.prefix(2_000)),
                "confidence": Double(candidate.confidence),
                "x": Double(box.minX),
                "y": Double(box.minY),
                "width": Double(box.width),
                "height": Double(box.height)
            ]
        }
    }

    private func cachedLines(for key: CacheKey) -> [[String: Any]]? {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        return cache[key]
    }

    private func cache(_ lines: [[String: Any]], for key: CacheKey) {
        cacheLock.lock()
        defer { cacheLock.unlock() }
        cache[key] = lines
        cacheOrder.removeAll { $0 == key }
        cacheOrder.append(key)
        while cacheOrder.count > maximumCachedPages {
            cache.removeValue(forKey: cacheOrder.removeFirst())
        }
    }
}

private enum PDFOCRError: LocalizedError {
    case invalidPath
    case invalidPage
    case missingFile
    case unreadablePDF
    case unreadablePage

    var errorDescription: String? {
        switch self {
        case .invalidPath: return "OCR is available only for PDF files in this Lattice library"
        case .invalidPage: return "That PDF page is not available"
        case .missingFile: return "The PDF is no longer available in this Lattice library"
        case .unreadablePDF: return "Lattice could not open this PDF for text recognition"
        case .unreadablePage: return "Lattice could not render this page for text recognition"
        }
    }
}
