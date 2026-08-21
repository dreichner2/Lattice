# Security Policy

## Supported code

Security fixes are applied to the current default branch and active desktop
reader pull requests. The local book and paper payloads are deliberately not
stored in GitHub.

## Reporting a vulnerability

Open a private GitHub security advisory for vulnerabilities involving path
escape, unintended network exposure, local file disclosure, unsafe EPUB/PDF
handling, token bypass, or reading-data loss. Do not attach copyrighted book
files. A minimal synthetic fixture is preferred.

## Security invariants

CS Library must preserve these properties:

1. The content service binds only to loopback.
2. A request cannot read outside the selected library root.
3. Only currently indexed material can be opened or revealed.
4. Operating-system actions require the per-process action token.
5. EPUB publisher scripts and external network requests remain disabled.
6. Desktop applications attach only to the expected library identity and a
   compatible protocol version.
7. Reading-data imports never execute content and are bounded in size.
8. Build artifacts never include the user's local book or paper payloads.

## Local data

Reading positions, preferences, bookmarks, notes, and reading sessions are
stored in `reader-state.sqlite3` under the operating system's application-data
directory. Exported JSON files may contain private notes and quotations and
should be handled accordingly.
