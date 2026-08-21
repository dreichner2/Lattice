# Contributing

CS Library is a personal local-first project, but changes should still be small,
reviewable, and reproducible.

## Development setup

Requirements:

- macOS 13 or later for native compilation;
- Xcode command-line tools;
- Python 3;
- Node.js for reader tests; and
- the repository metadata files. Local books are optional for fixture tests.

Run the portable checks:

```bash
python3 -m py_compile scripts/library_ui.py
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
open "CS Library.app"
```

## Pull requests

- Use a feature branch.
- Keep book and paper payloads out of Git.
- Do not add material whose redistribution rights are unclear.
- Add or update tests for every behavior change.
- Describe migrations and recovery implications for reader-data changes.
- Keep the pull request in draft until the macOS build is green.
- Do not merge generated `CS Library.app`, `.library-cache`, `work`, or local
  database files.

## Code organization

- `native/ReaderStore.swift`: durable user-created data.
- `native/ReaderBridge.swift`: web/native contract.
- `native/NativePDFReader*.swift`: PDFKit experience.
- `native/ImmersiveEPUB.js`: native EPUB enhancement.
- `native/LibraryWorkspace.js`: notebook and global search.
- `scripts/library_ui.py`: loopback service and EPUB parser.
- `ui/`: shared shelf and EPUB reader.

Avoid adding another independent persistence mechanism. New reader state belongs
in ReaderStore and must use stable document IDs.

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
or change a license without the owner's explicit decision. Book access and
redistribution terms are tracked independently under `metadata/` and
`notes/provenance/`.
