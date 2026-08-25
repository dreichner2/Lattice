# Lattice for Windows

Lattice is a shared knowledge library. The Windows app is a self-contained
.NET 8 WPF/WebView2 shell for the same local shelf and EPUB interface used on
macOS. It launches a bundled loopback-only service and includes a polished
Lattice PDF reader built on PDF.js 6.2.108. The reader range-loads large files,
supports continuous, single-page, and two-page layouts, search, outlines,
lazy thumbnails, zoom, rotation, restored reading position, and true native
fullscreen. Its Shelf control closes the reader and returns to the existing
collection. The installed package does not require a separate Python or .NET
runtime.

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
2. downloads the pinned public `v2.3.2` release and verifies its SHA-256;
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
[`v2.3.2/Lattice-Windows-win-x64.zip`](https://github.com/dreichner2/Lattice/releases/download/v2.3.2/Lattice-Windows-win-x64.zip).
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

## Move the library to another drive

Wait until Syncthing reports **Up to Date**, open Lattice's library-options
menu, and choose **Move library to another drive…**. Select the external drive
or a folder on it. Lattice pauses the current folder, copies the whole library
to a new `Lattice` directory, verifies each file, redirects both Lattice and the
same Syncthing folder ID, resumes and scans it, then removes the original copy.

Keep the drive connected until the library reopens. If any copy, hash, API, or
post-scan check fails, Lattice preserves the original and restores Syncthing's
old path when its API remains reachable. If restoration cannot be confirmed, it
keeps both copies and reports the failure. Do not manually move individual
books: their disappearance can be synchronized as deletion.

## Add material and optional Codex details

Use the **Add** control in the Lattice header, or drag a PDF, EPUB, or TXT file
from Explorer. The shared import flow validates
the file, creates a collision-safe name and adjacent `.library.json` sidecar,
and synchronizes both through Syncthing.

The Windows host uses the standard compact system title bar; it does not add a
second navigation toolbar above Lattice. Update, Move Library, folder, library
switching, and reload actions live in the header's three-dot menu. Back/home
navigation stays inside the shelf and reader, and the live shelf refreshes
automatically.

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
If a Tutor turn exits inside Codex, Lattice reports the exit code and saves the
latest bounded stderr diagnostic under
`%LOCALAPPDATA%\Lattice\Tutor\<library-id>\last-codex-stderr.log`. Keep that
local diagnostic private because it can contain library paths. Tutor source
files may remain on the external SSD: Lattice stages only the bounded selected
context under `%TEMP%` and gives Codex one read-only temporary workspace instead
of direct grants to one or more library volumes. A sandbox launch failure is not
a corrupt conversation, so clearing the Tutor session is not a repair.

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
retained. An exact copied `Lattice.exe` on the desktop is digest-bound when the
update starts, then atomically replaced by a detached helper only after the old
process exits. A changed or unrelated executable is never overwritten. The
updated launcher remains at the same desktop path and redirects to the verified
active installation when opened.

After an update activates, the menu shows **Version &lt;ID&gt;**. That item remains
enabled: selecting it performs another signed update check without requiring
the newly updated window to be closed and reopened.

For an external library SSD, use the in-app three-dot menu's **Disconnect
library drive** command. It waits for an Up to Date folder, pauses only
Lattice's stable Syncthing folder ID, stops the dedicated Syncthing process and
local service, releases the WebView, resolves the parent USB device, saves
reconnect state, and launches a detached eject helper from local storage. The
main Lattice process exits completely before the helper makes Windows' native
eject request. Before disposal, Lattice records the exact PID and start time of
every process reported by its WebView2 environment; the helper waits for the
main app and every captured process to exit. If a File Explorer window or tab
is open on the library drive, the helper shows the blocking location and waits
for the user to close it before allowing final handles to drain. The helper
stays visibly in **Ejecting…** and retries only pending or outstanding handle
closes within a bounded window, allowing a quiet 30-second drain interval
between native eject requests. Keep the SSD attached until
**Safe to unplug** appears. Lattice does not use volume lock, dismount, offline,
or mount-point operations. If Windows vetoes eject, Lattice reports the exact
veto type and name, writes `%LOCALAPPDATA%\CS Library\last-eject-diagnostic.txt`,
and leaves the library disconnected. After reconnecting the SSD and reopening
Lattice, the app detects the saved volume even if its drive letter changed,
restarts Syncthing, rescans,
and waits for Up to Date. A pause recorded by Lattice resumes automatically. If
only an existing pause remains, Lattice asks before resuming that exact folder.

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
