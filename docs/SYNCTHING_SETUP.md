# Clone and connect Lattice

This setup uses one private Syncthing folder and one public Git checkout. GitHub
provides the app, taxonomy, curated catalog, and empty directory scaffold.
Syncthing supplies private book, paper, and lecture files plus their adjacent
metadata sidecars. OneDrive is not involved.

## Windows: one-time setup

1. Clone the repository into its permanent location in PowerShell:

   ```powershell
   git clone https://github.com/dreichner2/cs-library.git "$HOME\CS-Library"
   cd "$HOME\CS-Library"
   ```

2. Pair the Windows Syncthing device with the Mac mini hub. Exchange the device
   ID privately; do not post it in an issue or commit it to the repository.
3. On the incoming **Lattice** folder prompt, set:

   | Setting | Exact value |
   |---|---|
   | Folder Label | `Lattice` |
   | Folder ID | `cs-library-3b8290f24f15` |
   | Folder Path | the clone root, normally `C:\Users\<name>\CS-Library` |
   | Folder Type | `Send & Receive` |
   | Watch for Changes | enabled |

4. Accept the folder. Do not add `books`, `papers`, or `lectures` as separate
   Syncthing folders.
5. Start the Windows Lattice app and choose that same clone root once. The
   app saves the choice.

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

The only unavoidable manual security steps are pairing the two devices and
choosing the clone root on the incoming-folder prompt. No content directories,
nested collection folders, or ignore rules need to be created by hand.
