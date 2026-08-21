# Legacy cs-books import - 2026-08-20

The former `~/cs-books` shelf was integrated into this repository.
The migration copied and verified every unique binary before the original
folder was moved to the macOS Trash at:

`~/.Trash/cs-books-imported-2026-08-20`

That Trash copy remains recoverable until the Trash is emptied.

## Verification boundary

- All 17 original files matched the source `SHA256SUMS` manifest before import.
- Fifteen unique files were copied byte-for-byte under normalized names. Their
  current hashes are in `manifests/cs-books-import-2026-08-20.sha256`.
- The old SICP PDF was byte-identical to `books/sicp.pdf` (SHA-256
  `08709a87567d8311d6fd29c4f4a5386801153e71450e628c4a5a5d7e85feda8b`).
- The old combined OSTEP PDF and `books/ostep.pdf` both contain
  834 pages. All 834 decoded page-content streams, media boxes, and rotations
  matched. The library edition was retained because it also has section and
  chapter bookmarks.
- The legacy README grouped source families but did not map exact acquisition
  URLs or license records to most individual files. Imported sidecars preserve
  that gap and require independent verification before redistribution.

## Path mapping

| Legacy filename | Library destination |
|---|---|
| `AIMA - AI A Modern Approach (Russell & Norvig, 4e).pdf` | `books/aima-4e.pdf` |
| `CLRS - Introduction to Algorithms (Cormen et al, 4e, 2022).pdf` | `books/clrs-4e.pdf` |
| `Clean Code - Robert C. Martin.pdf` | `books/clean-code.pdf` |
| `Concrete Mathematics 2e - Graham, Knuth, Patashnik.pdf` | `books/concrete-math-2e.pdf` |
| `Design Patterns (GoF - Gamma et al).pdf` | `books/design-patterns.pdf` |
| `Dragon Book - Aho, Lam, Sethi, Ullman.pdf` | `books/dragon-book-2e.pdf` |
| `K&R - The C Programming Language (1978).pdf` | `books/c-programming-language-1e.pdf` |
| `Programming Pearls - Jon Bentley.epub` | `books/programming-pearls-2e.epub` |
| `Refactoring - Martin Fowler.pdf` | `books/refactoring-1e.pdf` |
| `Reinforcement Learning - Sutton & Barto (2e).pdf` | `books/reinforcement-learning-2e.pdf` |
| `SICP JavaScript Edition - Source Academy.pdf` | `books/sicp-js.pdf` |
| `Speech and Language Processing 3e - Jurafsky & Martin.pdf` | `books/slp-3e-draft.pdf` |
| `The Art of Unix Programming - Eric S. Raymond.pdf` | `books/art-of-unix-programming.pdf` |
| `The Mythical Man-Month - Brooks.epub` | `books/mythical-man-month.epub` |
| `The Pragmatic Programmer - Hunt & Thomas.pdf` | `books/pragmatic-programmer-1e.pdf` |
| `SICP 2e - Abelson & Sussman (LaTeX, CC-BY-SA).pdf` | Deduplicated against `books/sicp.pdf` |
| `OSTEP - Operating Systems Three Easy Pieces (v1.10).pdf` | Deduplicated against `books/ostep.pdf` |
