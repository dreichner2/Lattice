# Clone and connect the shared CS Library

This setup uses one private Syncthing folder and one public Git checkout. GitHub
provides the app, catalog, and empty directory scaffold. Syncthing supplies the
private book, paper, and lecture files. OneDrive is not involved.

## Windows: one-time setup

1. Clone the repository into its permanent location in PowerShell:

   ```powershell
   git clone https://github.com/dreichner2/cs-library.git "$HOME\CS-Library"
   cd "$HOME\CS-Library"
   ```

2. Pair the Windows Syncthing device with the Mac mini hub. Exchange the device
   ID privately; do not post it in an issue or commit it to the repository.
3. On the incoming **CS Library** folder prompt, set:

   | Setting | Exact value |
   |---|---|
   | Folder Label | `CS Library` |
   | Folder ID | `cs-library-3b8290f24f15` |
   | Folder Path | the clone root, normally `C:\Users\<name>\CS-Library` |
   | Folder Type | `Send & Receive` |
   | Watch for Changes | enabled |

4. Accept the folder. Do not add `books`, `papers`, or `lectures` as separate
   Syncthing folders.
5. Start the Windows CS Library app and choose that same clone root once. The
   app saves the choice.

## macOS: one-time setup

Use the existing checkout as the folder path:

```text
/Users/danny/Developer/cs-library
```

Accept the same **CS Library** folder ID as **Send & Receive**, with filesystem
watching enabled. The Mac mini remains the always-on hub; it uses its dedicated
service path and does not need a Git checkout.

## What a clean clone already contains

Git cannot store a literally empty directory, so each payload directory has a
hidden `.gitkeep` placeholder. Those placeholders create this layout during
clone and are not reading material:

```text
CS-Library/
├── CATALOG.md
├── library-layout.json
├── .stignore
├── books/
│   ├── art-of-hpc/
│   └── software-foundations/
├── papers/
│   └── mit-6006/
└── lectures/
```

`library-layout.json` is the machine-readable authority used by tests and the
Windows package builder. To validate a checkout when Python is available:

```powershell
python scripts/validate_library_layout.py
```

## What Syncthing shares

The root `.stignore` uses an explicit allowlist. It shares only `books/`,
`papers/`, and `lectures/`. The catalog, metadata, manifests, provenance, and
application source continue to come from GitHub; Git internals, builds, caches,
and both platforms' live SQLite reader databases remain local. Syncthing
intentionally never syncs the `.stignore` file itself, so every Git clone
carries its own identical copy.

After setup, either person can add a supported file. It appears on the other
computer after Syncthing finishes and as a **New arrival** in CS Library even
before catalog metadata is added. The Mac mini's 90-day versioning is recovery
protection, but Syncthing is still synchronization rather than a complete
backup: deletions also propagate.

The only unavoidable manual security steps are pairing the two devices and
choosing the clone root on the incoming-folder prompt. No content directories,
nested collection folders, or ignore rules need to be created by hand.
