import AppKit
import PDFKit

extension NativePDFReaderController {
    func makeToolbar() -> NSVisualEffectView {
        let toolbar = NSVisualEffectView(frame: .zero)
        toolbar.translatesAutoresizingMaskIntoConstraints = false
        toolbar.material = .titlebar
        toolbar.blendingMode = .withinWindow
        toolbar.state = .active

        let stack = NSStackView()
        stack.translatesAutoresizingMaskIntoConstraints = false
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 7
        stack.edgeInsets = NSEdgeInsets(top: 8, left: 12, bottom: 8, right: 12)
        toolbar.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: toolbar.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: toolbar.trailingAnchor),
            stack.topAnchor.constraint(equalTo: toolbar.topAnchor),
            stack.bottomAnchor.constraint(equalTo: toolbar.bottomAnchor)
        ])

        let shelfButton = NSButton(title: "Shelf", target: self, action: #selector(closeAction(_:)))
        shelfButton.bezelStyle = .texturedRounded
        shelfButton.image = NSImage(systemSymbolName: "chevron.left", accessibilityDescription: nil)
        shelfButton.imagePosition = .imageLeading
        shelfButton.toolTip = "Return to the library"
        shelfButton.widthAnchor.constraint(greaterThanOrEqualToConstant: 70).isActive = true

        let sidebarButton = makeIconButton(symbol: "sidebar.left", accessibilityLabel: "Toggle thumbnails and notes", action: #selector(toggleSidebarAction(_:)))
        self.sidebarButton = sidebarButton

        let titleLabel = NSTextField(labelWithString: title)
        titleLabel.lineBreakMode = .byTruncatingMiddle
        titleLabel.font = NSFont.systemFont(ofSize: 12.5, weight: .semibold)
        titleLabel.textColor = .labelColor
        titleLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        titleLabel.setContentHuggingPriority(.defaultLow, for: .horizontal)

        let previousButton = makeIconButton(symbol: "chevron.left", accessibilityLabel: "Previous page", action: #selector(previousPageAction(_:)))
        let nextButton = makeIconButton(symbol: "chevron.right", accessibilityLabel: "Next page", action: #selector(nextPageAction(_:)))

        let pageField = NSTextField(string: "1")
        pageField.alignment = .center
        pageField.font = NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .medium)
        pageField.bezelStyle = .roundedBezel
        pageField.target = self
        pageField.action = #selector(goToPageFieldAction(_:))
        pageField.widthAnchor.constraint(equalToConstant: 46).isActive = true
        self.pageField = pageField

        let pageSummary = NSTextField(labelWithString: "/ 1")
        pageSummary.font = NSFont.monospacedDigitSystemFont(ofSize: 10, weight: .regular)
        pageSummary.textColor = .secondaryLabelColor
        pageSummary.widthAnchor.constraint(greaterThanOrEqualToConstant: 32).isActive = true
        self.pageSummary = pageSummary

        let bookmarkButton = makeIconButton(symbol: "bookmark", accessibilityLabel: "Bookmark this page", action: #selector(toggleBookmarkAction(_:)))
        self.bookmarkButton = bookmarkButton

        let bookmarkPopup = NSPopUpButton(frame: .zero, pullsDown: false)
        bookmarkPopup.font = NSFont.systemFont(ofSize: 10, weight: .medium)
        bookmarkPopup.target = self
        bookmarkPopup.action = #selector(openBookmarkAction(_:))
        bookmarkPopup.toolTip = "Saved pages"
        bookmarkPopup.widthAnchor.constraint(equalToConstant: 80).isActive = true
        self.bookmarkPopup = bookmarkPopup

        let addQuote = makeIconButton(symbol: "text.quote", accessibilityLabel: "Add selected text to page note", action: #selector(addSelectionToNoteAction(_:)))
        let zoomOut = makeIconButton(symbol: "minus.magnifyingglass", accessibilityLabel: "Zoom out", action: #selector(zoomOutAction(_:)))
        let fit = makeIconButton(symbol: "arrow.up.left.and.arrow.down.right", accessibilityLabel: "Fit page", action: #selector(fitPageAction(_:)))
        let zoomIn = makeIconButton(symbol: "plus.magnifyingglass", accessibilityLabel: "Zoom in", action: #selector(zoomInAction(_:)))

        let displayMode = NSSegmentedControl(labels: ["Scroll", "Page"], trackingMode: .selectOne, target: self, action: #selector(changeDisplayModeAction(_:)))
        displayMode.segmentStyle = .rounded
        displayMode.selectedSegment = 0
        displayMode.setWidth(50, forSegment: 0)
        displayMode.setWidth(46, forSegment: 1)
        displayModeControl = displayMode

        let searchField = NSSearchField(frame: .zero)
        searchField.placeholderString = "Search this PDF"
        searchField.font = NSFont.systemFont(ofSize: 10.5)
        searchField.target = self
        searchField.action = #selector(searchAction(_:))
        searchField.sendsSearchStringImmediately = false
        let preferredSearchWidth = searchField.widthAnchor.constraint(equalToConstant: 170)
        preferredSearchWidth.priority = .defaultHigh
        preferredSearchWidth.isActive = true
        searchField.widthAnchor.constraint(greaterThanOrEqualToConstant: 120).isActive = true
        self.searchField = searchField

        let searchSummary = NSTextField(labelWithString: "")
        searchSummary.font = NSFont.monospacedDigitSystemFont(ofSize: 9, weight: .regular)
        searchSummary.textColor = .secondaryLabelColor
        searchSummary.widthAnchor.constraint(equalToConstant: 42).isActive = true
        self.searchSummary = searchSummary

        let searchNext = makeIconButton(symbol: "arrow.down", accessibilityLabel: "Next search result", action: #selector(nextSearchResultAction(_:)))
        let focus = makeIconButton(symbol: "arrow.up.left.and.arrow.down.right", accessibilityLabel: "Focus mode", action: #selector(toggleFocusAction(_:)))
        focusButton = focus

        stack.addArrangedSubview(shelfButton)
        stack.addArrangedSubview(sidebarButton)
        stack.addArrangedSubview(makeSeparator())
        stack.addArrangedSubview(titleLabel)
        stack.addArrangedSubview(previousButton)
        stack.addArrangedSubview(pageField)
        stack.addArrangedSubview(pageSummary)
        stack.addArrangedSubview(nextButton)
        stack.addArrangedSubview(bookmarkButton)
        stack.addArrangedSubview(bookmarkPopup)
        stack.addArrangedSubview(addQuote)
        stack.addArrangedSubview(makeSeparator())
        stack.addArrangedSubview(zoomOut)
        stack.addArrangedSubview(fit)
        stack.addArrangedSubview(zoomIn)
        stack.addArrangedSubview(displayMode)
        stack.addArrangedSubview(searchField)
        stack.addArrangedSubview(searchSummary)
        stack.addArrangedSubview(searchNext)
        stack.addArrangedSubview(focus)
        return toolbar
    }

    func makeSidebar() -> NSVisualEffectView {
        let sidebar = NSVisualEffectView(frame: .zero)
        sidebar.translatesAutoresizingMaskIntoConstraints = false
        sidebar.material = .sidebar
        sidebar.blendingMode = .withinWindow
        sidebar.state = .active

        let pageHeading = NSTextField(labelWithString: "PAGES")
        pageHeading.translatesAutoresizingMaskIntoConstraints = false
        pageHeading.font = NSFont.systemFont(ofSize: 9, weight: .bold)
        pageHeading.textColor = .secondaryLabelColor

        let thumbnails = PDFThumbnailView(frame: .zero)
        thumbnails.translatesAutoresizingMaskIntoConstraints = false
        thumbnails.thumbnailSize = NSSize(width: 126, height: 166)
        thumbnails.backgroundColor = .clear
        thumbnails.allowsDragging = false
        thumbnailView = thumbnails

        let noteHeading = NSTextField(labelWithString: "PAGE NOTE")
        noteHeading.translatesAutoresizingMaskIntoConstraints = false
        noteHeading.font = NSFont.systemFont(ofSize: 9, weight: .bold)
        noteHeading.textColor = .secondaryLabelColor

        let pageLabel = NSTextField(labelWithString: "Page 1")
        pageLabel.translatesAutoresizingMaskIntoConstraints = false
        pageLabel.font = NSFont.monospacedDigitSystemFont(ofSize: 9, weight: .regular)
        pageLabel.textColor = .tertiaryLabelColor
        pageLabel.alignment = .right
        notesPageLabel = pageLabel

        let notesScroll = NSScrollView(frame: .zero)
        notesScroll.translatesAutoresizingMaskIntoConstraints = false
        notesScroll.hasVerticalScroller = true
        notesScroll.autohidesScrollers = true
        notesScroll.borderType = .bezelBorder
        notesScroll.drawsBackground = false

        let notes = NSTextView(frame: NSRect(x: 0, y: 0, width: 190, height: 120))
        notes.isRichText = false
        notes.allowsUndo = true
        notes.font = NSFont.systemFont(ofSize: 11)
        notes.textColor = .labelColor
        notes.backgroundColor = .textBackgroundColor.withAlphaComponent(0.72)
        notes.textContainerInset = NSSize(width: 8, height: 8)
        notes.delegate = self
        notesScroll.documentView = notes
        notesTextView = notes

        sidebar.addSubview(pageHeading)
        sidebar.addSubview(thumbnails)
        sidebar.addSubview(noteHeading)
        sidebar.addSubview(pageLabel)
        sidebar.addSubview(notesScroll)
        NSLayoutConstraint.activate([
            pageHeading.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 16),
            pageHeading.trailingAnchor.constraint(equalTo: sidebar.trailingAnchor, constant: -12),
            pageHeading.topAnchor.constraint(equalTo: sidebar.topAnchor, constant: 14),
            thumbnails.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 8),
            thumbnails.trailingAnchor.constraint(equalTo: sidebar.trailingAnchor, constant: -8),
            thumbnails.topAnchor.constraint(equalTo: pageHeading.bottomAnchor, constant: 8),
            thumbnails.bottomAnchor.constraint(equalTo: noteHeading.topAnchor, constant: -12),
            noteHeading.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 16),
            noteHeading.bottomAnchor.constraint(equalTo: notesScroll.topAnchor, constant: -8),
            pageLabel.trailingAnchor.constraint(equalTo: sidebar.trailingAnchor, constant: -14),
            pageLabel.centerYAnchor.constraint(equalTo: noteHeading.centerYAnchor),
            pageLabel.leadingAnchor.constraint(greaterThanOrEqualTo: noteHeading.trailingAnchor, constant: 8),
            notesScroll.leadingAnchor.constraint(equalTo: sidebar.leadingAnchor, constant: 10),
            notesScroll.trailingAnchor.constraint(equalTo: sidebar.trailingAnchor, constant: -10),
            notesScroll.bottomAnchor.constraint(equalTo: sidebar.bottomAnchor, constant: -10),
            notesScroll.heightAnchor.constraint(equalToConstant: 128)
        ])
        return sidebar
    }

    func makeIconButton(symbol: String, accessibilityLabel: String, action: Selector) -> NSButton {
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: accessibilityLabel) ?? NSImage(size: .zero)
        let button = NSButton(image: image, target: self, action: action)
        button.bezelStyle = .texturedRounded
        button.imagePosition = .imageOnly
        button.toolTip = accessibilityLabel
        button.setAccessibilityLabel(accessibilityLabel)
        button.widthAnchor.constraint(equalToConstant: 34).isActive = true
        button.heightAnchor.constraint(equalToConstant: 32).isActive = true
        return button
    }

    func makeSeparator() -> NSBox {
        let separator = NSBox()
        separator.boxType = .separator
        separator.widthAnchor.constraint(equalToConstant: 1).isActive = true
        separator.heightAnchor.constraint(equalToConstant: 22).isActive = true
        return separator
    }
}
