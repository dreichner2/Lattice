# Lattice for Windows

Lattice is a shared knowledge library. The Windows app is a self-contained
.NET 8 WPF/WebView2 shell for the same local shelf and EPUB interface used on
macOS. It launches a bundled,
loopback-only Python service and opens PDFs in WebView2's built-in PDF viewer.

## Use the CI package

Download `Lattice-Windows-win-x64` from the successful **Lattice Windows desktop app**
workflow, extract the ZIP, and run `Lattice.exe`. On first launch, choose the
synchronized Lattice library folder containing `CATALOG.md`, `metadata/`,
`library-taxonomy.json`, and `ui/`. This is the Git checkout used as the
Syncthing folder, not the installed app directory.

The package also contains `Install Lattice.ps1`, which copies the portable app
into `%LOCALAPPDATA%\Programs\Lattice` and creates a Start menu shortcut.
The installer does not require administrator access.

Use **Add materials…** in the native toolbar or the Add control in the library to
choose files. The shared interface also accepts PDF, EPUB, and TXT files dragged
from Explorer. If the Codex CLI is installed and signed in for the current
Windows account, Lattice asks `gpt-5.6-luna` to suggest editable metadata;
file import still completes with local fallback details when Codex is unavailable.

## Automatic updates

The top-right status button compares the packaged commit with GitHub `main`.
When a verified `latest-main` package is ready, press **Update available**, then
confirm **Install**. The app downloads and verifies the Windows ZIP, exits, and
uses a copied helper executable to replace its application-owned files before
relaunching.

The transaction backs up every file it may replace and restores them if any
copy, validation, or relaunch step fails. Its owned-file manifest explicitly
excludes `books/`, `papers/`, and `lectures/`; the updater also leaves the
selected Git checkout, `%LOCALAPPDATA%\CS Library` reader state, and Syncthing
content untouched. Install under the default per-user location so the updater
has write access without administrator privileges.

## Source build

From a PowerShell terminal in the repository root:

```powershell
.\windows\build-windows.ps1
```

Requirements:

- Windows 10 version 2004 (build 19041) or newer;
- .NET 8 SDK;
- Python 3.13;
- Node.js 24; and
- Microsoft Edge WebView2 Runtime.

The script runs the portable test suite, bundles the local service with pinned
PyInstaller 6.21.0, publishes a self-contained x64 app, and creates
`artifacts/Lattice-Windows-win-x64.zip`.

## Data boundary

Book, paper, and lecture payloads are never included in GitHub artifacts. The
package and every Git clone already contain the complete empty directory
scaffold from `library-layout.json`; do not create those folders manually. Web
reader preferences and progress are mirrored into
`%LOCALAPPDATA%\CS Library\WebReader.sqlite3`; that legacy internal path is
intentionally retained so the Lattice rename does not strand existing
Windows reader data. macOS native notebook data stays
in its separate native database. Syncthing synchronizes the library files, not
either platform's private reader database.

Follow [the exact clone-and-connect procedure](../docs/SYNCTHING_SETUP.md) and
select the same repository root in both Syncthing and Lattice.
