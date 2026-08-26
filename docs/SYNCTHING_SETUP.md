# Clone and connect Lattice

This setup uses one private Syncthing folder and one public Git checkout. GitHub
provides the app, taxonomy, curated catalog, and empty directory scaffold.
Syncthing supplies private book, paper, and lecture files plus their adjacent
metadata sidecars. OneDrive is not involved.

## Windows: one-time setup

The fast path needs Git for Windows, WinGet, and an internet connection. Clone
the repository into its permanent location and run the checked-in setup:

```powershell
winget install --id Git.Git -e --source winget
```

Close and reopen PowerShell if Git was just installed, then run:

```powershell
git clone https://github.com/dreichner2/Lattice.git "$HOME\Lattice"
cd "$HOME\Lattice"
& ".\windows\setup\Install Lattice and Connect.cmd"
```

The script validates the existing scaffold, installs the pinned Lattice `v2.3.3`
package for the current user, installs official Syncthing `2.1.3` through
WinGet when needed, saves the clone as Lattice's library, and configures this
exact Syncthing folder on the Windows side:

| Setting | Exact value |
|---|---|
| Folder Label | `Lattice` |
| Folder ID | `cs-library-3b8290f24f15` |
| Folder Path | the clone root, normally `C:\Users\<name>\Lattice` |
| Folder Type | `Send & Receive` |
| Watch for Changes | enabled |

It also creates a per-user Syncthing startup shortcut, launches Lattice, and
prints and copies the Windows Device ID. Syncthing's certificates, database,
and API key remain outside the clone in `%LOCALAPPDATA%\Syncthing`. No hub GUI
password or API key is copied or printed.

The interactive happy path is designed to take less than two minutes. Actual
download, install, Windows security-scan, and first-sync duration depends on the
PC and connection. OneDrive is not used, and no content folders or ignore rules
need to be created manually.

### Required hub approval

The setup cannot approve its own device on the Mac mini. Send the displayed
Windows Device ID privately to the Mac mini owner; do not post it in an issue or
commit it. On the Mac mini's authenticated Syncthing GUI, the owner must:

1. choose **Add Remote Device** and enter that exact Windows Device ID;
2. give it a recognizable name such as **Aidan's Windows PC**;
3. share the existing folder whose ID is `cs-library-3b8290f24f15` with the new
   device; and
4. save, keep both computers online, and wait for each side to show **Up to
   Date**.

The visible hub label may still be **CS Library** or may already be **Lattice**;
the stable folder ID above is authoritative. Do not create a second hub folder.
Do not add `books`, `papers`, or `lectures` as separate Syncthing folders.

## macOS clients: one-time setup

Use the existing checkout as the folder path:

```text
/Users/danny/Developer/cs-library
```

Accept the same **Lattice** folder ID as **Send & Receive**, with
filesystem watching enabled. The visible label may be changed independently,
but the folder ID must remain `cs-library-3b8290f24f15`.

The Mac mini remains the always-on hub. Its existing system service uses the
protected `/Library/Application Support/CSLibraryHub/Library` path rather than
the Git checkout; do not move that service or replace its folder ID. Existing
devices that still display the earlier **CS Library** label can safely rename
only the label to **Lattice**.

## Move a client library to external storage

Do not drag individual books out of the synchronized folder. Syncthing can
interpret that as deletion. On a Windows or macOS client, use Lattice's native
**Move Library** command instead:

1. connect the destination drive and wait for Syncthing to show **Up to Date**;
2. in Windows, open the library-options menu and choose **Move reading
   library**; on macOS choose **File → Move Reading Library to External
   Storage…**;
3. select the drive or a destination folder and keep it connected until Lattice
   reports success; and
4. let Lattice reopen the relocated library before removing the drive.

The command pauses folder `cs-library-3b8290f24f15`, copies the complete
library and `.stfolder` through a temporary directory on the destination,
verifies every destination file against its source SHA-256, changes the path on
that same Syncthing folder record, resumes and rescans it, and then removes the
old directory. It never copies the Syncthing API key or configuration into the
library. If any preflight, copy, verification, configuration, or post-scan gate
fails, the original remains intact. Lattice restores Syncthing's old path and
pause state when its API remains reachable. If restoration cannot be confirmed,
both copies are retained and the error identifies the path that needs checking.

The installed Lattice app never moves with this command. The executable,
updater, WebView profile, private reader data, Tutor cache, Study Lab database,
and bundled runtimes stay on internal storage. The lightweight Git checkout travels with the reading
payloads because it supplies the catalog, stable relative paths, import rules,
and the root-level Syncthing allowlist.

An unplugged drive makes `.stfolder` unavailable, so Syncthing stops the folder
instead of treating the whole library as deleted. On Windows, Lattice saves the
volume identity and library-relative path before ejecting. When that volume is
mounted again, Lattice resolves the current drive letter and safely restores
the same paused Syncthing folder binding before resuming it. The Mac mini hub
is deliberately excluded from this client workflow.

Before ejecting a connected library SSD, open Lattice's three-dot menu and use
**Disconnect library drive**. Lattice first requires the folder to be Up to
Date, pauses only folder `cs-library-3b8290f24f15`, stops the dedicated
Syncthing process and local service, releases its WebView, and saves reconnect
state. It then launches a detached helper from local storage and closes the
main Lattice process completely. Lattice passes the helper the exact PID and
start time of every process in its WebView2 environment, and the helper waits
for the main app and the complete captured process set to exit before asking
Windows to eject the parent USB device. It then allows final handles to drain
and retries only pending or outstanding handle closes within a bounded window.
Keep the SSD attached while **Ejecting…** is shown and unplug only after **Safe
to unplug**. A Windows veto leaves the library disconnected, reports the exact
veto type and name, and records `%LOCALAPPDATA%\CS Library\last-eject-diagnostic.txt`;
Lattice never falls back to a manual volume dismount. On macOS, eject through
Finder after Lattice closes. When the drive is mounted again, reopen Lattice.
Windows automatically detects the saved volume, restarts Syncthing, rescans, and waits
for Up to Date. Lattice resumes only a pause it recorded itself; an existing
manual pause is preserved unless the user explicitly chooses **Resume Sync**.

If the exact Lattice folder is paused but no Lattice-owned reconnect record is
available, Reconnect reports that distinction and asks whether to **Resume
Sync** or **Keep Paused**. Choosing Resume changes only the stable Lattice
folder, scans it, and waits for a healthy state before reporting it connected.

## What a clean clone already contains

Git cannot store a literally empty directory, so each payload directory has a
hidden `.gitkeep` placeholder. Those placeholders create this layout during
clone and are not reading material:

```text
cs-library/
├── CATALOG.md
├── library-layout.json
├── library-taxonomy.json
├── .stignore
├── books/
│   ├── art-of-hpc/
│   └── software-foundations/
├── papers/
│   └── mit-6006/
└── lectures/
```

`library-layout.json` is the machine-readable scaffold and sync authority;
`library-taxonomy.json` defines stable subject IDs. They are used by tests and
the Windows package builder. To validate a checkout when Python is available:

```powershell
python scripts/validate_library_layout.py
```

## What Syncthing shares

The root `.stignore` uses an explicit allowlist. It shares only `books/`,
`papers/`, and `lectures/`, including adjacent private sidecars. For example:

```text
books/example.pdf
books/example.pdf.library.json
```

The curated catalog, taxonomy, `metadata/`, manifests, provenance, and
application source continue to come from GitHub; Git internals, builds, caches,
and both platforms' live SQLite reader databases remain local. Syncthing
intentionally never syncs the `.stignore` file itself, so every Git clone
carries its own identical copy.

After setup, either person can drag a supported file into Lattice or use
its **Add** button. The payload and sidecar appear on the other computer after
Syncthing finishes, already carrying the same title and subject. The Mac mini's
90-day versioning is recovery protection, but Syncthing is still synchronization
rather than a complete backup: deletions also propagate.

### Device-vault ignores

Lattice's device vault is payload-only and local to one computer. **Check out
to vault** verifies a second copy but does not remove anything. The separate
**Release local copy** action preserves the adjacent `.library.json` sidecar,
adds a rooted payload rule before the allowlist's `!/books/**`, `!/papers/**`,
or `!/lectures/**` rule, and only then removes the payload. This ordering is
required because Syncthing applies the first matching ignore pattern.

If Syncthing is running, Lattice requires the exact folder to be healthy and Up
to Date and pauses it around release or restore; it resumes and requests a scan
after the transition. If the verified configuration is offline, the durable
`.stignore` rule is already present before Syncthing's next scan. Filenames with
cross-platform ignore metacharacters are not eligible. Restoring removes only a
rule Lattice added; a pre-existing exact rule remains in force.

The only unavoidable manual security step in the Windows happy path is the Mac
mini owner's approval of the new Device ID and existing-folder share. The
Windows script has already selected the clone root and configured its half of
the relationship.

## Optional Codex metadata

Codex is not required for cloning, Syncthing, reading, searching, importing, or
editing metadata. If a person wants automatic metadata suggestions on their own
computer, they can install the official Codex CLI and authenticate it locally:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
codex login
codex login status
```

Each person must use their own ChatGPT account. Never share an account or copy
Codex credential files between the Mac and Windows computers. Lattice asks
`gpt-5.6-luna` only for editable descriptive suggestions; if Codex is missing or
unavailable, import completes with local fallback metadata. See the official
[Codex authentication guide](https://learn.chatgpt.com/docs/auth) and
[`gpt-5.6-luna` model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna).
