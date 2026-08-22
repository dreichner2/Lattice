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

The script validates the existing scaffold, installs the pinned Lattice `v2.0.2`
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
