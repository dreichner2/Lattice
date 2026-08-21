# Library cleanup and remote preparation — 2026-08-20

This pass reorganized the local shelf before its first GitHub publication.

## Starting state

- 46 catalog records represented by 138 physical artifacts.
- 1.8 GB of local payloads.
- No Git remote.
- No byte-identical duplicate files, but two logical redundancies.
- Several hash-prefixed, title-length, or source-oriented filenames.
- Metadata stored beside payloads as `.meta.json` sidecars.

## Deduplication

Two recoverable groups were removed from the active shelf:

1. Sixty-eight official OSTEP chapter PDFs and sidecars were redundant with the
   verified, bookmarked, 834-page `books/ostep.pdf` compilation.
2. The Crafting Interpreters sample chapter was redundant with the complete
   official `books/crafting-interpreters.zip` archive, which contains the same
   garbage-collection chapter and the rest of the book/source tree.

The removed files were moved to
`~/.Trash/cs-library-dedup-2026-08-20/` and remain recoverable until Trash is
emptied. They were not irreversibly deleted.

## Naming and layout

- All 69 payload filenames now use lowercase kebab-case and are at most 48
  characters long.
- MIT 6.006's source hashes were replaced locally by `lec-01.pdf` through
  `lec-20.pdf`; original official URLs remain in metadata.
- Long titles were replaced by stable shelf IDs such as `aima-4e.pdf`,
  `clrs-4e.pdf`, `dragon-book-2e.pdf`, `jls-26.pdf`, and `pbrt-4e.zip`.
- Metadata moved from adjacent sidecars into a mirrored, tracked `metadata/`
  tree. Reading folders now contain only reading payloads.
- `CATALOG.md` was rebuilt as nine subject shelves with one row per logical
  work. `STUDY_GUIDE.md` supplies both Java-first and general learning routes.

## Remote boundary

The remote intentionally tracks documentation, source/access metadata,
provenance, checksums, and the fetch/audit CLI. `/books/` and `/papers/` remain
local and ignored because the shelf mixes open licenses, personal-use editions,
and legacy imports with unknown redistribution history.

This is a rights boundary as well as a repository-size decision. A private Git
repository is not treated as automatic permission to re-host third-party
books.

## Final validation target

- 47 logical works
- 72 physical artifacts
- 72 metadata records
- 0 exact duplicate groups
- 72/72 artifact verification passes
- all three SHA-256 manifests valid after path normalization

The canonical current manifest is `manifests/library.sha256`. The two dated
manifests remain as acquisition-batch records with paths updated to their
current stable names.

During final validation, three user-supplied downloads appeared in the local
shelf. *Distributed Systems, 4e*, *Computer Vision: Algorithms and
Applications, 2e*, and *Introduction to Probability, 2e* were visually and
structurally inspected, normalized, and recorded as local-only artifacts. No
personalized watermark content is stored in tracked metadata or documentation.
