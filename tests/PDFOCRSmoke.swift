import AppKit
import Foundation
import PDFKit

@main
struct PDFOCRSmoke {
    static func main() throws {
        let manager = FileManager.default
        let root = manager.temporaryDirectory.appendingPathComponent("lattice-ocr-\(UUID().uuidString)", isDirectory: true)
        let books = root.appendingPathComponent("books", isDirectory: true)
        try manager.createDirectory(at: books, withIntermediateDirectories: true)
        defer { try? manager.removeItem(at: root) }

        let image = NSImage(size: NSSize(width: 1_400, height: 900))
        image.lockFocus()
        NSColor.white.setFill()
        NSRect(origin: .zero, size: image.size).fill()
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = .center
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 112, weight: .bold),
            .foregroundColor: NSColor.black,
            .paragraphStyle: paragraph,
        ]
        NSString(string: "LATTICE OCR 8472").draw(
            in: NSRect(x: 80, y: 350, width: 1_240, height: 180),
            withAttributes: attributes
        )
        image.unlockFocus()

        guard let page = PDFPage(image: image) else { throw SmokeError("could not create raster PDF page") }
        let document = PDFDocument()
        document.insert(page, at: 0)
        guard (page.string ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw SmokeError("fixture unexpectedly contains an embedded text layer")
        }
        let relativePath = "books/ocr-smoke.pdf"
        let pdfURL = root.appendingPathComponent(relativePath)
        guard document.write(to: pdfURL) else { throw SmokeError("could not write OCR fixture") }

        var recognition: Result<[String: Any], Error>?
        PDFOCRService(libraryRoot: root).recognize(relativePath: relativePath, pageNumber: 1) { result in
            DispatchQueue.main.async { recognition = result }
        }
        let deadline = Date().addingTimeInterval(30)
        while recognition == nil, Date() < deadline {
            RunLoop.current.run(until: Date().addingTimeInterval(0.05))
        }
        guard recognition != nil else {
            throw SmokeError("on-device OCR timed out")
        }
        let payload = try recognition?.get() ?? { throw SmokeError("on-device OCR returned no result") }()
        let lines = payload["lines"] as? [[String: Any]] ?? []
        let recognized = lines.compactMap { $0["text"] as? String }.joined(separator: " ").uppercased()
        guard recognized.contains("LATTICE"), recognized.contains("8472") else {
            throw SmokeError("unexpected OCR output: \(recognized)")
        }
        print("PDF OCR smoke test passed: \(recognized)")
    }
}

private struct SmokeError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}
