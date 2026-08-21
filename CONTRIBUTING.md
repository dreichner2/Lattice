# Contributing

## Principles

- Keep all reading and catalog features local-first.
- Preserve the browser interface when adding platform-specific behavior.
- Never commit book or paper payloads.
- Use synthetic, redistribution-safe PDF and EPUB fixtures in tests.
- Treat notes, bookmarks, highlights, and progress as durable user data.
- Keep macOS and Windows shortcut behavior aligned where platform conventions
  allow.

## Checks

### Shared service and JavaScript

```bash
python3 tests/test_cross_platform_server.py
node --test tests/test_immersive_epub.mjs
node --test tests/test_reader_state.mjs
node --check windows/reader/pdf-reader.js
```

### macOS

```bash
./scripts/build-macos-app.sh
```

### Windows

```powershell
.\windows\build-windows.ps1
```

## Publishing changes

Use a feature branch and a draft pull request. Stage only the files belonging to
the change. Do not commit generated applications, PDF.js vendor files,
`node_modules`, PyInstaller output, or release archives.
