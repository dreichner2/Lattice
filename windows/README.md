# Lattice for Windows

Lattice is a shared knowledge library. The Windows app is a self-contained
.NET 8 WPF/WebView2 shell for the same local shelf and EPUB interface used on
macOS. It launches a bundled loopback-only service and opens PDFs in WebView2's
built-in PDF viewer. The installed package does not require a separate Python
or .NET runtime.

## Fast setup from a clean Windows PC

The supported happy path needs Windows 10 version 2004 (build 19041) or newer,
Git for Windows, WinGet, an internet connection, and the Microsoft Edge WebView2
Runtime. Run this in PowerShell as the Windows account that will use Lattice:

```powershell
winget install --id Git.Git -e --source winget
```

If Git was just installed, close and reopen PowerShell once. Then run:

```powershell
git clone https://github.com/dreichner2/Lattice.git "$HOME\Lattice"
cd "$HOME\Lattice"
& ".\windows\setup\Install Lattice and Connect.cmd"
```

You can also double-click `windows\setup\Install Lattice and Connect.cmd` after
cloning. The script:

1. validates the clone and its complete empty library scaffold;
2. downloads the pinned public `v2.0.2` release and verifies its SHA-256;
3. installs Lattice for the current user under
   `%LOCALAPPDATA%\Programs\Lattice`;
4. installs official Syncthing `2.1.3` with WinGet when needed;
5. keeps Syncthing certificates, its database, and its API key outside the
   shared clone in `%LOCALAPPDATA%\Syncthing`;
6. configures the clone as the `cs-library-3b8290f24f15` **Send & Receive**
   folder, paired locally with the Mac mini hub;
7. creates the Lattice Start-menu shortcut and a per-user Syncthing startup
   shortcut; and
8. launches Lattice and prints and copies this PC's Syncthing Device ID.

The interactive happy path is designed to take less than two minutes. That is
not a promise about elapsed download, package-install, Windows security-scan, or
initial library-sync time, which depends on the PC and connection. No OneDrive
account or manually created library folder is required.

Preview every target without changing the PC:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\setup\Setup-LatticeWindows.ps1 -PlanOnly
```

The pinned release can also be downloaded directly from
[`v2.0.2/Lattice-Windows-win-x64.zip`](https://github.com/dreichner2/Lattice/releases/download/v2.0.2/Lattice-Windows-win-x64.zip).
See [`windows/setup/README.md`](setup/README.md) for offline/test inputs and the
full switch list.

## Finish the mutual Syncthing approval

Setup can configure only the Windows side. Send the displayed Device ID
privately to the Mac mini owner. On the Mac mini, the owner must:

1. add that exact Windows Device ID; and
2. share the existing **Lattice** folder with the new Windows device.

The Windows device has already been configured with the hub Device ID and
folder ID, but Syncthing requires both devices to approve one another. Both
computers must be online together for the first transfer. Wait for Syncthing to
show **Up to Date** before expecting the complete shelf. A Device ID is not a
password, but it should still be exchanged privately; no hub password or API
key is needed on Windows.

Do not add `books/`, `papers/`, or `lectures/` as separate Syncthing folders.
The repository root is the one shared folder, and the checked-in `.stignore`
keeps the public Git source separate from private payloads and sidecars.

## Add material and optional Codex details

Use **Add materials…** in the native toolbar or the Add control in the library,
or drag a PDF, EPUB, or TXT file from Explorer. The shared import flow validates
the file, creates a collision-safe name and adjacent `.library.json` sidecar,
and synchronizes both through Syncthing.

The shelf, reader, search, import, subject chooser, and manual metadata editor
all work without Codex. Codex enrichment is optional. If the current Windows
user wants Lattice to ask `gpt-5.6-luna` for editable title, author, year,
subject, and topic suggestions, install the official Codex CLI and authenticate
that computer:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
codex login
codex login status
```

Complete the browser sign-in with that person's own ChatGPT account. Never
share a ChatGPT login or copy Codex credentials between computers. Lattice does
not send the publication bytes or full text to Codex, and import falls back to
local metadata if the CLI is absent, signed out, unavailable, or returns invalid
data. See the official [Codex authentication
guide](https://learn.chatgpt.com/docs/auth) and
[`gpt-5.6-luna` model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

## Updates and rollback

The installed layout is versioned:

```text
%LOCALAPPDATA%\Programs\Lattice\
├── active-version.json
├── versions\
│   ├── 2.0.0\
│   └── <next-version>\
└── rollback\
```

Automatic updates accept stable `major.minor.patch` versions only. The app
downloads fixed `update-manifest.json` and `update-manifest.json.sig` release
assets, verifies the exact manifest bytes with its embedded RSA-3072 release
public key, and then enforces the signed versioned GitHub URL, file size, and
SHA-256 for the Windows ZIP. A downloaded candidate is extracted to a new
version directory; it becomes active only after its own isolated loopback
`/api/health` probe and the complete shared interface succeed. Start-menu and
`active-version.json` replacements are atomic. Promotion re-reads the active
authority under a cross-process lock, so a slower older candidate cannot
replace a newer version. The authority is published first so a stale shortcut
or old executable redirects to the healthy candidate. Once promotion is
durable, the candidate closes the exact superseded Lattice window; a failed
candidate leaves the current version open. One previous healthy version is
retained.

This release-manifest signature is an application update control, not a Windows
Authenticode signature. The current executable is not Authenticode-signed, so
Microsoft Defender SmartScreen or Smart App Control may warn or block it on
some PCs. Do not turn off SmartScreen, Smart App Control, antivirus, or other
Windows protections to install Lattice. If Windows blocks the app, stop and ask
the maintainer for a signed-distribution path.

## Source build

From a PowerShell terminal in the repository root:

```powershell
.\windows\build-windows.ps1
```

Source-build requirements are:

- Windows 10 version 2004 (build 19041) or newer;
- .NET 8 SDK;
- Python 3.13;
- Node.js 24; and
- Microsoft Edge WebView2 Runtime.

The script runs the portable test suite, bundles the local service with pinned
PyInstaller 6.21.0, publishes a self-contained x64 app, and creates
`artifacts\Lattice-Windows-win-x64.zip`.

## Data boundary

Book, paper, and lecture payloads are never included in GitHub artifacts. The
package and every Git clone already contain the complete empty directory
scaffold from `library-layout.json`; do not create those folders manually. Web
reader preferences and progress are mirrored into
`%LOCALAPPDATA%\CS Library\WebReader.sqlite3`; that legacy internal path is
intentionally retained so the Lattice rename does not strand existing Windows
reader data. macOS native notebook data stays in its separate native database.
Syncthing synchronizes the library payloads and sidecars, not either platform's
private reader database.

Follow [the exact clone-and-connect procedure](../docs/SYNCTHING_SETUP.md). The
repository root must be the same path selected by Syncthing and Lattice.
