# CS Library for Windows

The Windows application is a .NET 8 WPF/WebView2 host for the same local shelf
and EPUB interface used by the browser and macOS app. PDFs open in a dedicated,
offline PDF.js workspace rather than the browser's default PDF chrome.

## Reader parity

The Windows PDF workspace includes:

- continuous scroll and single-page modes;
- page thumbnails and direct page entry;
- resume position, layout, zoom, and sidebar state;
- bookmarks and a bookmark navigator;
- full-document text search with result snippets;
- selectable text and insertion into per-page notes;
- fit-width, fit-page, and manual zoom;
- focus mode and reading-first shortcuts; and
- Markdown export of notes and bookmarks.

EPUBs use the existing CS Library pagination, typography, tones, contents,
bookmarks, resume state, and the native-app quotes-and-notes layer.

## Build

Run from the repository root in PowerShell:

```powershell
.\windows\build-windows.ps1
```

The script installs the pinned PDF.js package, tests the shared state bridge and
local server, bundles the Python service with PyInstaller, publishes a
self-contained WPF application, and creates:

```text
artifacts/CS-Library-Windows-win-x64.zip
```

The portable package contains the complete metadata/UI skeleton but no book or
paper payloads. Add the local `books/` and `papers/` folders, or select an
existing CS Library folder when the app first opens.

## Requirements for a source build

- Windows 10 19041 or newer
- .NET 8 SDK
- Node.js 24
- Python 3.13
- Microsoft Edge WebView2 Runtime

The packaged app is self-contained and includes its Python server. WebView2 is
normally present on supported Windows systems; Microsoft also distributes an
offline runtime installer for systems where it is absent.
