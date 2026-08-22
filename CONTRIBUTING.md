# Contributing

Lattice is a personal local-first project, but changes should still be small,
reviewable, and reproducible.

## Development setup

Requirements:

- macOS 13 or later for native compilation;
- Xcode command-line tools;
- Python 3;
- Node.js for reader tests; and
- the repository metadata and taxonomy files. Local reading payloads are
  optional for fixture tests.

Run the portable checks:

```bash
python3 -m py_compile scripts/library_ui.py
python3 scripts/validate_library_layout.py
python3 -m unittest discover -s tests -p 'test_*.py' -v
node --check ui/app.js
node --check native/ImmersiveEPUB.js
node --check native/LibraryWorkspace.js
node --test tests/test_immersive_epub.mjs tests/test_library_workspace.mjs
bash -n scripts/build-macos-app.sh
```

On macOS, build and verify the application:

```bash
./scripts/build-macos-app.sh
open "Lattice.app"
```

## Pull requests

- Use a feature branch.
- Keep book, paper, lecture, and `.library.json` sidecar payloads out of Git.
- Do not add material whose redistribution rights are unclear.
- Add or update tests for every behavior change.
- Describe migrations and recovery implications for reader-data changes.
- Keep the pull request in draft until the macOS build is green.
- Do not merge generated `Lattice.app` or legacy `CS Library.app`
  bundles, `.library-cache`, `work`, or local database files.

## Code organization

- `native/ReaderStore.swift`: durable user-created data.
- `native/ReaderBridge.swift`: web/native contract.
- `native/NativePDFReader*.swift`: PDFKit experience.
- `native/ImmersiveEPUB.js`: native EPUB enhancement.
- `native/LibraryWorkspace.js`: notebook and global search.
- `scripts/library_ui.py`: loopback service and EPUB parser.
- `library-taxonomy.json`: stable subject IDs, catalog topic defaults, and
  selected work overrides.
- `library-layout.json`: clone scaffold, sidecar naming, and Syncthing contract.
- `ui/`: shared shelf and EPUB reader.

Avoid adding another independent persistence mechanism. New reader state belongs
in ReaderStore and must use stable document IDs.

For a payload named `example.pdf`, the private import sidecar is
`example.pdf.library.json`. Do not change this suffix or strip the payload
extension without a migration. Sidecar integrity fields (`path`, `bytes`, and
`sha256`), material type, and access defaults are server-owned; UI or AI
features may edit only title, authors, year, edition, subject, and topics. New
subject IDs must be lowercase kebab-case, documented, and covered by the layout
tests.

## Commit hygiene

Stage only intentional files. Prefer focused commits such as:

```text
feat(reader-store): add annotation migration
fix(epub): preserve location after resize
test(server): reject archive compression bombs
docs: document reader backup format
```

## Licensing

The repository currently does not declare a general software license. Do not add
or change a license without the owner's explicit decision. Reading-material access and
redistribution terms are tracked independently under `metadata/` and
`notes/provenance/`.
