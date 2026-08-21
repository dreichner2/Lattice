#!/usr/bin/env python3
"""Apply the small integration edits required by the cross-platform readers.

The large existing reader files remain the source of truth. Keeping these edits
as deterministic replacements makes the cross-platform migration reviewable and
re-runnable without replacing the established UI or reader implementations.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"Expected one integration point in {path}, found {text.count(old)}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def append_once(path: str, marker: str, addition: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if addition.strip() in text:
        return
    if marker not in text:
        raise SystemExit(f"Missing append marker in {path}: {marker!r}")
    target.write_text(text.replace(marker, marker + addition), encoding="utf-8")


def patch_mac_app() -> None:
    replace_once(
        "native/CSLibraryApp.swift",
        "    private var immersiveReader: ImmersiveReaderCoordinator!\n",
        "    private var immersiveReader: ImmersiveReaderCoordinator!\n"
        "    private var expectedLibraryID = \"\"\n",
    )
    replace_once(
        "native/CSLibraryApp.swift",
        "        libraryRoot = root\n",
        "        libraryRoot = root\n"
        "        expectedLibraryID = LibraryIdentity.id(for: root)\n",
    )
    replace_once(
        "native/CSLibraryApp.swift",
        "        if let script = ImmersiveReaderCoordinator.epubUserScript(libraryRoot: libraryRoot) {\n"
        "            configuration.userContentController.addUserScript(script)\n"
        "        }\n",
        "        for script in ImmersiveReaderCoordinator.userScripts(libraryRoot: libraryRoot) {\n"
        "            configuration.userContentController.addUserScript(script)\n"
        "        }\n",
    )
    replace_once(
        "native/CSLibraryApp.swift",
        "                    json[\"app\"] as? String == \"cs-library\"\n"
        "                else { return }\n",
        "                    json[\"app\"] as? String == \"cs-library\",\n"
        "                    json[\"libraryId\"] as? String == self.expectedLibraryID,\n"
        "                    (json[\"protocolVersion\"] as? Int ?? 0) >= LibraryIdentity.protocolVersion\n"
        "                else { return }\n",
    )
    replace_once(
        "native/CSLibraryApp.swift",
        "                libraryRoot.appendingPathComponent(\"scripts/library_ui.py\").path,\n"
        "                \"--port\", String(preferredPort),\n"
        "                \"--no-browser\"\n",
        "                libraryRoot.appendingPathComponent(\"scripts/cross_platform_server.py\").path,\n"
        "                \"--root\", libraryRoot.path,\n"
        "                \"--port\", String(preferredPort),\n"
        "                \"--parent-pid\", String(ProcessInfo.processInfo.processIdentifier),\n"
        "                \"--no-browser\"\n",
    )
    replace_once(
        "native/CSLibraryApp.swift",
        "    private func configureMenu() {\n",
        "    @objc private func exportReadingData(_ sender: Any?) {\n"
        "        let panel = NSSavePanel()\n"
        "        panel.title = \"Export CS Library Reading Data\"\n"
        "        panel.nameFieldStringValue = \"CS-Library-Reading-Data.json\"\n"
        "        panel.allowedFileTypes = [\"json\"]\n"
        "        guard panel.runModal() == .OK, let url = panel.url else { return }\n"
        "        do {\n"
        "            try ReaderDataStore.shared.export(to: url)\n"
        "        } catch {\n"
        "            showFatalError(title: \"Reading data could not be exported\", message: error.localizedDescription, terminate: false)\n"
        "        }\n"
        "    }\n\n"
        "    @objc private func importReadingData(_ sender: Any?) {\n"
        "        let panel = NSOpenPanel()\n"
        "        panel.title = \"Import CS Library Reading Data\"\n"
        "        panel.allowedFileTypes = [\"json\"]\n"
        "        panel.allowsMultipleSelection = false\n"
        "        guard panel.runModal() == .OK, let url = panel.url else { return }\n"
        "        do {\n"
        "            try ReaderDataStore.shared.importData(from: url)\n"
        "            webView?.reloadFromOrigin()\n"
        "        } catch {\n"
        "            showFatalError(title: \"Reading data could not be imported\", message: error.localizedDescription, terminate: false)\n"
        "        }\n"
        "    }\n\n"
        "    private func configureMenu() {\n",
    )
    replace_once(
        "native/CSLibraryApp.swift",
        "        openFolderItem.target = self\n"
        "        fileItem.submenu = fileMenu\n",
        "        openFolderItem.target = self\n"
        "        fileMenu.addItem(.separator())\n"
        "        let exportItem = fileMenu.addItem(withTitle: \"Export Reading Data…\", action: #selector(exportReadingData(_:)), keyEquivalent: \"e\")\n"
        "        exportItem.keyEquivalentModifierMask = [.command, .shift]\n"
        "        exportItem.target = self\n"
        "        let importItem = fileMenu.addItem(withTitle: \"Import Reading Data…\", action: #selector(importReadingData(_:)), keyEquivalent: \"i\")\n"
        "        importItem.keyEquivalentModifierMask = [.command, .shift]\n"
        "        importItem.target = self\n"
        "        fileItem.submenu = fileMenu\n",
    )


def patch_pdf_state() -> None:
    replace_once(
        "native/NativePDFReaderController.swift",
        "        stateIdentifier = stableIdentifier(for: fileURL)\n"
        "        bookmarks = UserDefaults.standard.array(forKey: stateKey(\"bookmarks\")) as? [Int] ?? []\n",
        "        stateIdentifier = stableIdentifier(for: fileURL)\n"
        "        ReaderDataStore.shared.preparePDFState(identifier: stateIdentifier)\n"
        "        bookmarks = UserDefaults.standard.array(forKey: stateKey(\"bookmarks\")) as? [Int] ?? []\n",
    )
    replace_once(
        "native/NativePDFReaderState.swift",
        "        defaults.set(pageNotes, forKey: stateKey(\"notes\"))\n"
        "    }\n",
        "        defaults.set(pageNotes, forKey: stateKey(\"notes\"))\n"
        "        ReaderDataStore.shared.capturePDFState(identifier: stateIdentifier)\n"
        "    }\n",
    )


def patch_readme() -> None:
    replace_once(
        "README.md",
        "Double-click **`CS Library.app`** in this folder. It is a native macOS window\n"
        "that runs the exact same library interface without opening a normal browser.\n"
        "The app starts the private local library service when needed and shuts down the\n"
        "copy it owns when you quit.\n",
        "Double-click **`CS Library.app`** in this folder. The macOS app uses the shared\n"
        "library interface for browsing, a native PDFKit workspace for PDFs, and the\n"
        "immersive EPUB reader for reflowable books. It starts the private local service\n"
        "when needed and shuts down the copy it owns when you quit.\n",
    )
    replace_once(
        "README.md",
        "## Browser option\n",
        "## Open the Windows app\n\n"
        "Download the Windows artifact from CI or build it on Windows:\n\n"
        "```powershell\n"
        ".\\windows\\build-windows.ps1\n"
        "```\n\n"
        "The portable package contains **`CS Library.exe`**, a bundled loopback-only\n"
        "server, the same shelf UI, the immersive EPUB layer, and an offline PDF.js\n"
        "workspace with thumbnails, text search, bookmarks, notes, resume position,\n"
        "selected-text capture, focus mode, and Markdown export. On first launch, select\n"
        "the folder containing this library. No Python installation is required by the\n"
        "packaged Windows build.\n\n"
        "## Browser option\n",
    )
    replace_once(
        "README.md",
        "- embedded PDF/text reading plus explicit **Open on Mac** and **Finder** actions;\n",
        "- native PDFKit reading on macOS and an offline PDF.js workspace on Windows,\n"
        "  with resume state, search, bookmarks, notes, thumbnails, zoom, and focus mode;\n"
        "- embedded text reading plus explicit operating-system and file-manager actions;\n",
    )
    replace_once(
        "README.md",
        "├── native/                    # macOS WKWebView wrapper, plist, and app icon\n",
        "├── native/                    # macOS app, durable reader store, and shared scripts\n"
        "├── windows/                   # WPF/WebView2 app and offline PDF.js reader\n",
    )


def patch_gitignore() -> None:
    append_once(
        ".gitignore",
        "/CS Library.app/\n",
        "/artifacts/\n"
        "/windows/build/\n"
        "/windows/reader/node_modules/\n"
        "/windows/reader/vendor/\n"
        "/windows/CSLibrary.Windows/bin/\n"
        "/windows/CSLibrary.Windows/obj/\n",
    )


def main() -> None:
    patch_mac_app()
    patch_pdf_state()
    patch_readme()
    patch_gitignore()


if __name__ == "__main__":
    main()
