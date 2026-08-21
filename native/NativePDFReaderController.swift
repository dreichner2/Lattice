import AppKit
import Foundation
import PDFKit
import WebKit

final class NativePDFReaderController: NSObject, NSTextViewDelegate {
    var onClose: (() -> Void)?

    weak var window: NSWindow?
    weak var rootView: NSView?
    weak var webView: WKWebView?
    let libraryRoot: URL
    let fileURL: URL
    let title: String

    var container: NSView?
    var pdfView: PDFView?
    var document: PDFDocument?
    var toolbar: NSVisualEffectView?
    var sidebar: NSVisualEffectView?
    var thumbnailView: PDFThumbnailView?
    var toolbarHeightConstraint: NSLayoutConstraint?
    var sidebarWidthConstraint: NSLayoutConstraint?
    var pageField: NSTextField?
    var pageSummary: NSTextField?
    var searchField: NSSearchField?
    var searchSummary: NSTextField?
    var bookmarkButton: NSButton?
    var bookmarkPopup: NSPopUpButton?
    var sidebarButton: NSButton?
    var focusButton: NSButton?
    var displayModeControl: NSSegmentedControl?
    var focusExitButton: NSButton?
    var notesTextView: NSTextView?
    var notesPageLabel: NSTextField?

    var stateIdentifier = ""
    var bookmarks: [Int] = []
    var pageNotes: [String: String] = [:]
    var loadedNotePage = -1
    var searchResults: [PDFSelection] = []
    var searchIndex = -1
    var focusMode = false
    var sidebarVisible = true
    var noteSaveWorkItem: DispatchWorkItem?
    var pageObserver: NSObjectProtocol?
    var scaleObserver: NSObjectProtocol?
    var findMatchObserver: NSObjectProtocol?
    var findEndObserver: NSObjectProtocol?

    init(
        window: NSWindow,
        rootView: NSView,
        webView: WKWebView,
        libraryRoot: URL,
        fileURL: URL,
        title: String
    ) {
        self.window = window
        self.rootView = rootView
        self.webView = webView
        self.libraryRoot = libraryRoot
        self.fileURL = fileURL
        self.title = title
        super.init()
    }

    deinit {
        removeObservers()
        noteSaveWorkItem?.cancel()
    }

    func present() {
        guard
            let rootView,
            let window,
            let document = PDFDocument(url: fileURL)
        else {
            showOpenError()
            closeWebReaderShell()
            onClose?()
            return
        }

        self.document = document
        stateIdentifier = stableIdentifier(for: fileURL)
        bookmarks = UserDefaults.standard.array(forKey: stateKey("bookmarks")) as? [Int] ?? []
        bookmarks = Array(Set(bookmarks.filter { $0 >= 0 && $0 < document.pageCount })).sorted()
        pageNotes = UserDefaults.standard.dictionary(forKey: stateKey("notes")) as? [String: String] ?? [:]
        sidebarVisible = UserDefaults.standard.object(forKey: stateKey("sidebar")) as? Bool ?? true

        let container = NSView(frame: .zero)
        container.translatesAutoresizingMaskIntoConstraints = false
        container.wantsLayer = true
        container.layer?.backgroundColor = NSColor(calibratedWhite: 0.065, alpha: 1).cgColor
        rootView.addSubview(container)
        NSLayoutConstraint.activate([
            container.leadingAnchor.constraint(equalTo: rootView.leadingAnchor),
            container.trailingAnchor.constraint(equalTo: rootView.trailingAnchor),
            container.topAnchor.constraint(equalTo: rootView.topAnchor),
            container.bottomAnchor.constraint(equalTo: rootView.bottomAnchor)
        ])
        self.container = container

        let toolbar = makeToolbar()
        container.addSubview(toolbar)
        let toolbarHeight = toolbar.heightAnchor.constraint(equalToConstant: 58)
        toolbarHeightConstraint = toolbarHeight
        NSLayoutConstraint.activate([
            toolbar.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            toolbar.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            toolbar.topAnchor.constraint(equalTo: container.topAnchor),
            toolbarHeight
        ])
        self.toolbar = toolbar

        let sidebar = makeSidebar()
        container.addSubview(sidebar)
        let sidebarWidth = sidebar.widthAnchor.constraint(equalToConstant: sidebarVisible ? 224 : 0)
        sidebarWidthConstraint = sidebarWidth
        NSLayoutConstraint.activate([
            sidebar.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            sidebar.topAnchor.constraint(equalTo: toolbar.bottomAnchor),
            sidebar.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            sidebarWidth
        ])
        sidebar.isHidden = !sidebarVisible
        self.sidebar = sidebar

        let reader = PDFView(frame: .zero)
        reader.translatesAutoresizingMaskIntoConstraints = false
        reader.document = document
        reader.displayBox = .cropBox
        reader.displayDirection = .vertical
        reader.displayMode = .singlePageContinuous
        reader.displaysPageBreaks = true
        reader.pageShadowsEnabled = true
        reader.backgroundColor = NSColor(calibratedWhite: 0.065, alpha: 1)
        reader.minScaleFactor = 0.2
        reader.maxScaleFactor = 5.0
        reader.autoScales = true
        container.addSubview(reader)
        NSLayoutConstraint.activate([
            reader.leadingAnchor.constraint(equalTo: sidebar.trailingAnchor),
            reader.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            reader.topAnchor.constraint(equalTo: toolbar.bottomAnchor),
            reader.bottomAnchor.constraint(equalTo: container.bottomAnchor)
        ])
        pdfView = reader
        thumbnailView?.pdfView = reader

        let focusExit = makeIconButton(
            symbol: "arrow.down.right.and.arrow.up.left",
            accessibilityLabel: "Show reader controls",
            action: #selector(toggleFocusAction(_:))
        )
        focusExit.translatesAutoresizingMaskIntoConstraints = false
        focusExit.isHidden = true
        container.addSubview(focusExit)
        NSLayoutConstraint.activate([
            focusExit.topAnchor.constraint(equalTo: container.topAnchor, constant: 16),
            focusExit.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -16)
        ])
        focusExitButton = focusExit

        installObservers(for: reader)
        restoreState()
        refreshToolbar()
        refreshBookmarks()
        loadCurrentPageNote()
        window.title = title
        container.alphaValue = 0
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.20
            container.animator().alphaValue = 1
        }
        window.makeFirstResponder(reader)
    }

    func close(notifyWeb: Bool) {
        guard container != nil else { return }
        saveCurrentPageNote()
        persistState()
        removeObservers()
        noteSaveWorkItem?.cancel()
        noteSaveWorkItem = nil
        container?.removeFromSuperview()
        container = nil
        pdfView = nil
        document = nil
        toolbar = nil
        sidebar = nil
        thumbnailView = nil
        toolbarHeightConstraint = nil
        sidebarWidthConstraint = nil
        pageField = nil
        pageSummary = nil
        searchField = nil
        searchSummary = nil
        bookmarkButton = nil
        bookmarkPopup = nil
        sidebarButton = nil
        focusButton = nil
        displayModeControl = nil
        focusExitButton = nil
        notesTextView = nil
        notesPageLabel = nil
        searchResults = []
        searchIndex = -1
        focusMode = false
        window?.title = "CS Library"
        if notifyWeb {
            closeWebReaderShell()
        }
        window?.makeFirstResponder(webView)
        onClose?()
    }

    func handleKeyEvent(_ event: NSEvent) -> NSEvent? {
        if isEditingText {
            return event
        }

        let modifiers = event.modifierFlags.intersection([.command, .control, .option])
        if modifiers.isEmpty {
            switch event.keyCode {
            case 53:
                if focusMode {
                    setFocusMode(false)
                    return nil
                }
            case 49:
                goToPage(offset: event.modifierFlags.contains(.shift) ? -1 : 1)
                return nil
            case 116, 123:
                goToPage(offset: -1)
                return nil
            case 121, 124:
                goToPage(offset: 1)
                return nil
            case 3:
                toggleFocus()
                return nil
            case 11:
                toggleBookmark()
                return nil
            case 17:
                toggleSidebar()
                return nil
            default:
                break
            }
        }
        return event
    }

    func previousPage() {
        goToPage(offset: -1)
    }

    func nextPage() {
        goToPage(offset: 1)
    }

    func toggleFocus() {
        setFocusMode(!focusMode)
    }

    func toggleSidebar() {
        guard !focusMode else { return }
        sidebarVisible.toggle()
        sidebarWidthConstraint?.constant = sidebarVisible ? 224 : 0
        sidebar?.isHidden = !sidebarVisible
        refreshToolbar()
        persistState()
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.18
            container?.layoutSubtreeIfNeeded()
        }
    }

    func toggleBookmark() {
        guard let document, let page = pdfView?.currentPage else { return }
        let index = document.index(for: page)
        if let existing = bookmarks.firstIndex(of: index) {
            bookmarks.remove(at: existing)
        } else {
            bookmarks.append(index)
            bookmarks.sort()
        }
        refreshToolbar()
        refreshBookmarks()
        persistState()
    }

    func focusSearch() {
        if let searchField {
            window?.makeFirstResponder(searchField)
        }
    }

    func textDidChange(_ notification: Notification) {
        noteSaveWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            self?.saveCurrentPageNote()
            self?.persistState()
        }
        noteSaveWorkItem = workItem
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35, execute: workItem)
    }

    var isEditingText: Bool {
        guard let responder = window?.firstResponder else { return false }
        return responder is NSTextView || responder is NSTextField || responder is NSSearchField
    }
}
