import AppKit
import Foundation
import PDFKit
import WebKit

extension NativePDFReaderController {
    func installObservers(for reader: PDFView) {
        removeObservers()
        pageObserver = NotificationCenter.default.addObserver(
            forName: .PDFViewPageChanged,
            object: reader,
            queue: .main
        ) { [weak self] _ in
            self?.saveCurrentPageNote()
            self?.refreshToolbar()
            self?.loadCurrentPageNote()
            self?.persistState()
        }
        scaleObserver = NotificationCenter.default.addObserver(
            forName: .PDFViewScaleChanged,
            object: reader,
            queue: .main
        ) { [weak self] _ in
            self?.persistState()
        }
        if let document = reader.document {
            findMatchObserver = NotificationCenter.default.addObserver(
                forName: .PDFDocumentDidFindMatch,
                object: document,
                queue: .main
            ) { [weak self] notification in
                guard
                    let self,
                    let selection = notification.userInfo?["PDFDocumentFoundSelection"] as? PDFSelection
                else { return }
                self.searchResults.append(selection)
                self.pdfView?.highlightedSelections = self.searchResults
                if self.searchIndex < 0 {
                    self.searchIndex = 0
                    self.showCurrentSearchResult()
                } else {
                    self.searchSummary?.stringValue = "\(self.searchIndex + 1)/\(self.searchResults.count)"
                }
            }
            findEndObserver = NotificationCenter.default.addObserver(
                forName: .PDFDocumentDidEndFind,
                object: document,
                queue: .main
            ) { [weak self] _ in
                guard let self else { return }
                if self.searchResults.isEmpty {
                    self.searchSummary?.stringValue = "0"
                } else {
                    self.showCurrentSearchResult()
                }
            }
        }
    }

    func removeObservers() {
        [pageObserver, scaleObserver, findMatchObserver, findEndObserver].compactMap { $0 }.forEach {
            NotificationCenter.default.removeObserver($0)
        }
        document?.cancelFindString()
        pageObserver = nil
        scaleObserver = nil
        findMatchObserver = nil
        findEndObserver = nil
    }

    func restoreState() {
        guard let document, let reader = pdfView else { return }
        let defaults = UserDefaults.standard
        let savedMode = (try? store.preference(key: stateKey("display-mode")))
            ?? defaults.string(forKey: legacyStateKey("display-mode"))
            ?? "continuous"
        switch savedMode {
        case "page": reader.displayMode = .singlePage; displayModeControl?.selectedSegment = 1
        case "spread": reader.displayMode = .twoUpContinuous; displayModeControl?.selectedSegment = 2
        default: reader.displayMode = .singlePageContinuous; displayModeControl?.selectedSegment = 0
        }

        let durablePage = (try? store.position(documentID: documentRecord.id))?.page
        let legacyPage = defaults.integer(forKey: legacyStateKey("page"))
        let pageIndex = min(max(durablePage ?? legacyPage, 0), max(document.pageCount - 1, 0))
        if let page = document.page(at: pageIndex) {
            reader.go(to: page)
        }

        let useAutoScale = (try? store.preference(key: stateKey("auto-scale"))).flatMap(Bool.init)
            ?? defaults.object(forKey: legacyStateKey("auto-scale")) as? Bool
            ?? true
        if useAutoScale {
            reader.autoScales = true
        } else {
            let savedScale = (try? store.preference(key: stateKey("scale"))).flatMap(Double.init)
                ?? defaults.double(forKey: legacyStateKey("scale"))
            reader.autoScales = false
            if savedScale > 0 {
                reader.scaleFactor = min(max(savedScale, reader.minScaleFactor), reader.maxScaleFactor)
            }
        }
        DispatchQueue.main.async { [weak self] in
            self?.pdfView?.layoutDocumentView()
            self?.refreshToolbar()
            self?.loadCurrentPageNote()
        }
    }

    func persistState() {
        guard let document, let reader = pdfView, !stateIdentifier.isEmpty else { return }
        let pageIndex: Int
        if let page = reader.currentPage {
            pageIndex = document.index(for: page)
        } else { pageIndex = 0 }
        let progress = document.pageCount > 1 ? Double(pageIndex) / Double(document.pageCount - 1) : 0
        try? store.savePosition(ReaderPosition(
            documentID: documentRecord.id, locator: pdfLocator(page: pageIndex), page: pageIndex,
            progress: progress, updatedAt: Date().timeIntervalSince1970
        ))
        let mode = reader.displayMode == .singlePage ? "page" : (reader.displayMode == .twoUpContinuous ? "spread" : "continuous")
        try? store.setPreference(key: stateKey("auto-scale"), value: String(reader.autoScales))
        try? store.setPreference(key: stateKey("scale"), value: String(Double(reader.scaleFactor)))
        try? store.setPreference(key: stateKey("display-mode"), value: mode)
        try? store.setPreference(key: stateKey("sidebar"), value: String(sidebarVisible))
    }

    func refreshToolbar() {
        guard let document, let reader = pdfView else { return }
        let pageIndex = reader.currentPage.map { document.index(for: $0) } ?? 0
        let pageNumber = min(max(pageIndex + 1, 1), max(document.pageCount, 1))
        pageField?.stringValue = String(pageNumber)
        pageSummary?.stringValue = "/ \(max(document.pageCount, 1))"
        let percentage = document.pageCount > 0 ? Int(round(Double(pageNumber) / Double(document.pageCount) * 100)) : 0
        pageSummary?.toolTip = "Page \(pageNumber) of \(document.pageCount) · \(percentage)%"
        let pageLabel = reader.currentPage?.label ?? "Page \(pageNumber)"
        notesPageLabel?.stringValue = pageLabel
        bookmarkButton?.image = NSImage(
            systemSymbolName: bookmarks.contains(pageIndex) ? "bookmark.fill" : "bookmark",
            accessibilityDescription: "Bookmark this page"
        )
        sidebarButton?.contentTintColor = sidebarVisible ? .controlAccentColor : .secondaryLabelColor
    }

    func refreshBookmarks() {
        guard let popup = bookmarkPopup else { return }
        popup.removeAllItems()
        popup.addItem(withTitle: bookmarks.isEmpty ? "No bookmarks" : "Bookmarks")
        popup.item(at: 0)?.isEnabled = false
        for pageIndex in bookmarks {
            popup.addItem(withTitle: "Page \(pageIndex + 1)")
            popup.lastItem?.representedObject = pageIndex
        }
        popup.isEnabled = !bookmarks.isEmpty
    }

    func currentPageIndex() -> Int {
        guard let document, let page = pdfView?.currentPage else { return 0 }
        return document.index(for: page)
    }

    func saveCurrentPageNote() {
        guard loadedNotePage >= 0, let notesTextView else { return }
        let text = notesTextView.string.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = String(loadedNotePage)
        if text.isEmpty {
            pageNotes.removeValue(forKey: key)
            try? store.deleteAnnotation(id: noteIdentifier(page: loadedNotePage))
        } else {
            pageNotes[key] = text
            let identifier = noteIdentifier(page: loadedNotePage)
            let existing = durableAnnotations.first(where: { $0.id == identifier })
            let now = Date().timeIntervalSince1970
            let annotation = ReaderAnnotation(
                id: identifier, documentID: documentRecord.id, locator: pdfLocator(page: loadedNotePage),
                quote: "", note: text, color: "note", createdAt: existing?.createdAt ?? now, updatedAt: now
            )
            try? store.saveAnnotation(annotation)
            durableAnnotations.removeAll { $0.id == identifier }
            durableAnnotations.append(annotation)
        }
    }

    func loadCurrentPageNote() {
        saveCurrentPageNote()
        loadedNotePage = currentPageIndex()
        notesTextView?.string = pageNotes[String(loadedNotePage)] ?? ""
        notesPageLabel?.stringValue = "Page \(loadedNotePage + 1)"
    }

    func appendSelectionToNote() {
        guard let text = pdfView?.currentSelection?.string?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else {
            NSSound.beep()
            return
        }
        guard let notesTextView else { return }
        let quote = "“\(String(text.prefix(4000)))”"
        let separator = notesTextView.string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "" : "\n\n"
        notesTextView.string += separator + quote
        window?.makeFirstResponder(notesTextView)
        saveCurrentPageNote()
        persistState()
    }

    @discardableResult
    func addHighlight() -> Bool {
        guard
            let document,
            let selection = pdfView?.currentSelection,
            let quote = selection.string?.trimmingCharacters(in: .whitespacesAndNewlines),
            !quote.isEmpty
        else {
            NSSound.beep()
            return false
        }
        let now = Date().timeIntervalSince1970
        var saved = false
        for page in selection.pages {
            let pageIndex = document.index(for: page)
            let bounds = selection.bounds(for: page)
            guard !bounds.isEmpty else { continue }
            let identifier = "pdf-highlight:\(UUID().uuidString.lowercased())"
            let annotation = PDFAnnotation(bounds: bounds, forType: .highlight, withProperties: nil)
            annotation.color = NSColor.systemYellow.withAlphaComponent(0.34)
            annotation.userName = identifier
            page.addAnnotation(annotation)
            let stored = ReaderAnnotation(
                id: identifier,
                documentID: documentRecord.id,
                locator: pdfLocator(page: pageIndex, bounds: bounds),
                quote: String(quote.prefix(20_000)),
                note: "",
                color: "yellow",
                createdAt: now,
                updatedAt: now
            )
            try? store.saveAnnotation(stored)
            durableAnnotations.append(stored)
            saved = true
        }
        return saved
    }

    func restoreHighlights() {
        guard let document else { return }
        for stored in durableAnnotations where stored.color != "note" {
            guard
                let locator = locatorObject(stored.locator),
                let pageIndex = locator["page"] as? Int,
                let page = document.page(at: pageIndex),
                let rawBounds = locator["bounds"] as? [String: Any],
                let x = (rawBounds["x"] as? NSNumber)?.doubleValue,
                let y = (rawBounds["y"] as? NSNumber)?.doubleValue,
                let width = (rawBounds["width"] as? NSNumber)?.doubleValue,
                let height = (rawBounds["height"] as? NSNumber)?.doubleValue
            else { continue }
            let annotation = PDFAnnotation(
                bounds: NSRect(x: x, y: y, width: width, height: height),
                forType: .highlight,
                withProperties: nil
            )
            annotation.color = color(named: stored.color).withAlphaComponent(0.34)
            annotation.userName = stored.id
            page.addAnnotation(annotation)
        }
    }

    func indexPDFText() {
        let url = fileURL
        let documentID = documentRecord.id
        let documentTitle = documentRecord.title
        let store = store
        DispatchQueue.global(qos: .utility).async {
            guard let pdf = PDFDocument(url: url) else { return }
            var batch: [ReaderSearchItem] = []
            let now = Date().timeIntervalSince1970
            for index in 0..<pdf.pageCount {
                autoreleasepool {
                    guard let body = pdf.page(at: index)?.string?.trimmingCharacters(in: .whitespacesAndNewlines), !body.isEmpty else { return }
                    batch.append(ReaderSearchItem(
                        id: "pdf:\(documentID):\(index)", documentID: documentID, kind: "page",
                        title: "\(documentTitle) · Page \(index + 1)", body: String(body.prefix(200_000)), updatedAt: now
                    ))
                }
                if batch.count >= 25 {
                    try? store.indexSearchItems(batch)
                    batch.removeAll(keepingCapacity: true)
                }
            }
            if !batch.isEmpty { try? store.indexSearchItems(batch) }
        }
    }

    func pageIndex(from locator: String) -> Int? {
        (locatorObject(locator)?["page"] as? NSNumber)?.intValue
    }

    func locatorObject(_ locator: String) -> [String: Any]? {
        guard let data = locator.data(using: .utf8) else { return nil }
        return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    }

    func pdfLocator(page: Int, bounds: NSRect? = nil) -> String {
        var value: [String: Any] = ["type": "pdf", "page": page]
        if let bounds {
            value["bounds"] = ["x": bounds.origin.x, "y": bounds.origin.y, "width": bounds.width, "height": bounds.height]
        }
        guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) else { return "{}" }
        return String(data: data, encoding: .utf8) ?? "{}"
    }

    func noteIdentifier(page: Int) -> String { "pdf-note:\(documentRecord.id):\(page)" }

    func color(named value: String) -> NSColor {
        switch value.lowercased() {
        case "green": return .systemGreen
        case "blue": return .systemBlue
        case "pink": return .systemPink
        default: return .systemYellow
        }
    }

    func goToPage(offset: Int) {
        goToPage(index: currentPageIndex() + offset)
    }

    func goToPage(index: Int) {
        guard let document, let reader = pdfView else { return }
        let target = min(max(index, 0), max(document.pageCount - 1, 0))
        guard let page = document.page(at: target) else { return }
        saveCurrentPageNote()
        reader.go(to: page)
        refreshToolbar()
        loadCurrentPageNote()
    }

    func setFocusMode(_ focused: Bool) {
        guard pdfView != nil else { return }
        focusMode = focused
        toolbarHeightConstraint?.constant = focused ? 0 : 58
        toolbar?.isHidden = focused
        sidebarWidthConstraint?.constant = focused ? 0 : (sidebarVisible ? 224 : 0)
        sidebar?.isHidden = focused || !sidebarVisible
        focusExitButton?.isHidden = !focused
        focusButton?.contentTintColor = focused ? .controlAccentColor : .labelColor
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.18
            container?.layoutSubtreeIfNeeded()
        }
        window?.makeFirstResponder(pdfView)
    }

    func showCurrentSearchResult() {
        guard
            let reader = pdfView,
            searchIndex >= 0,
            searchIndex < searchResults.count
        else {
            searchSummary?.stringValue = "0"
            return
        }
        let selection = searchResults[searchIndex]
        reader.setCurrentSelection(selection, animate: true)
        reader.go(to: selection)
        searchSummary?.stringValue = "\(searchIndex + 1)/\(searchResults.count)"
        refreshToolbar()
        loadCurrentPageNote()
    }

    func closeWebReaderShell() {
        let script = """
        if (typeof window.csLibraryCloseReader === 'function') {
            window.csLibraryCloseReader();
        } else {
            document.body.classList.remove('reader-open');
            const shell = document.querySelector('#readerShell');
            shell?.setAttribute('aria-hidden', 'true');
            shell?.classList.remove('is-epub', 'is-focused');
            const pdf = document.querySelector('#pdfReader');
            if (pdf) { pdf.src = 'about:blank'; pdf.hidden = true; }
        }
        """
        webView?.evaluateJavaScript(script)
    }

    func stableIdentifier(for url: URL) -> String {
        let relative = url.path.replacingOccurrences(of: libraryRoot.path, with: "")
        return Data(relative.utf8).base64EncodedString()
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "=", with: "")
    }

    func stateKey(_ suffix: String) -> String {
        "pdf.\(stateIdentifier).\(suffix)"
    }

    func legacyStateKey(_ suffix: String) -> String {
        "cs-library.pdf.\(stableIdentifier(for: fileURL)).\(suffix)"
    }

    func showOpenError() {
        let alert = NSAlert()
        alert.alertStyle = .critical
        alert.messageText = "This PDF could not be opened"
        alert.informativeText = fileURL.lastPathComponent
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    @objc func closeAction(_ sender: Any?) { close(notifyWeb: true) }
    @objc func previousPageAction(_ sender: Any?) { previousPage() }
    @objc func nextPageAction(_ sender: Any?) { nextPage() }
    @objc func toggleSidebarAction(_ sender: Any?) { toggleSidebar() }
    @objc func toggleFocusAction(_ sender: Any?) { toggleFocus() }
    @objc func toggleBookmarkAction(_ sender: Any?) { toggleBookmark() }
    @objc func addSelectionToNoteAction(_ sender: Any?) { appendSelectionToNote() }
    @objc func highlightSelectionAction(_ sender: Any?) { _ = addHighlight() }

    @objc func goToPageFieldAction(_ sender: NSTextField) {
        goToPage(index: max(sender.integerValue, 1) - 1)
    }

    @objc func zoomInAction(_ sender: Any?) {
        guard let reader = pdfView else { return }
        reader.autoScales = false
        reader.scaleFactor = min(reader.scaleFactor * 1.16, reader.maxScaleFactor)
        persistState()
    }

    @objc func zoomOutAction(_ sender: Any?) {
        guard let reader = pdfView else { return }
        reader.autoScales = false
        reader.scaleFactor = max(reader.scaleFactor / 1.16, reader.minScaleFactor)
        persistState()
    }

    @objc func fitPageAction(_ sender: Any?) {
        pdfView?.autoScales = true
        persistState()
    }

    @objc func changeDisplayModeAction(_ sender: NSSegmentedControl) {
        guard let reader = pdfView else { return }
        switch sender.selectedSegment {
        case 1: reader.displayMode = .singlePage
        case 2: reader.displayMode = .twoUpContinuous
        default: reader.displayMode = .singlePageContinuous
        }
        reader.autoScales = true
        persistState()
    }

    @objc func openBookmarkAction(_ sender: NSPopUpButton) {
        guard let index = sender.selectedItem?.representedObject as? Int else { return }
        goToPage(index: index)
        sender.selectItem(at: 0)
    }

    @objc func searchAction(_ sender: NSSearchField) {
        guard let document, let reader = pdfView else { return }
        let query = sender.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        document.cancelFindString()
        searchResults = []
        searchIndex = -1
        reader.highlightedSelections = []
        guard !query.isEmpty else {
            searchSummary?.stringValue = ""
            return
        }
        searchSummary?.stringValue = "…"
        document.beginFindString(query, withOptions: .caseInsensitive)
    }

    @objc func nextSearchResultAction(_ sender: Any?) {
        guard !searchResults.isEmpty else {
            if let searchField { searchAction(searchField) }
            return
        }
        searchIndex = (searchIndex + 1) % searchResults.count
        showCurrentSearchResult()
    }
}
