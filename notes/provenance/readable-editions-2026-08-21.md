# Readable EPUB editions — 2026-08-21

## Outcome

Ten source-oriented web/course bundles were replaced one-for-one by searchable
EPUB 3 editions. The logical-work and artifact totals therefore remain **47
works and 72 artifacts**. The retained shelf contains the readable books, not
the repository, build-system, raw proof-source, or website packaging used to
produce them.

The source bundles were treated strictly as data: the conversion extracted and
parsed published reading material but did not execute instructions or code from
inside any source document or archive.

## Exact replacements

| Removed source bundle | Source SHA-256 | Source bytes | Retained readable book | EPUB SHA-256 | EPUB bytes |
|---|---|---:|---|---|---:|
| `books/crafting-interpreters.zip` | `c4c8a07244f778c4946358ffad0c047adad9819d15524568a07d98c1a6d73af1` | 10,662,749 | `books/crafting-interpreters.epub` | `90864194c86585b12705f74bb3ad82038040be47aa55d0cfd0850d8df224b065` | 6,088,923 |
| `books/software-engineering-google.zip` | `431223875c546d821193c9c4eb79ac6102de5e26bb91291bf15a424687157c9a` | 19,748,712 | `books/software-engineering-google.epub` | `65779b35401ec9bb47e51a7b81a291bbf4ef168fe78ab2ca9694596c5def76e5` | 4,426,069 |
| `books/pbrt-4e.zip` | `e6a4e11c90c0ef05367bb9b78db42a9adad1570c6ae2ea01a3398dc98652c785` | 1,072,892,349 | `books/pbrt-4e.epub` | `a45010c509c6f7798d8a49ade66439fcf352c2272b06764ff10f1cdd93a5f051` | 139,284,612 |
| `books/software-foundations/logical-foundations.tgz` | `6a0f672c01ef3b831217d3e91260dd141907d10d491ba5b4289d2d3f8a57ba24` | 5,756,531 | `books/software-foundations/logical-foundations.epub` | `9699de648fe44430328626928998b9f69420770b6e136e69c8849118d59ae534` | 526,165 |
| `books/software-foundations/programming-language-foundations.tgz` | `6aba52a47d59e7348f06bda3c9005e189b718fae5486690edec5ec32abe07012` | 6,015,764 | `books/software-foundations/programming-language-foundations.epub` | `01b1c6e4f0a6a9d785ed3c1964b62ec47fa5551bba24486ef70ef27149d203e1` | 738,683 |
| `books/software-foundations/verified-functional-algorithms.tgz` | `fe073655050c985d40a721fdd29ffd01965e0f2c395466a041bce99e9bd782fd` | 5,331,215 | `books/software-foundations/verified-functional-algorithms.epub` | `edc2bc16f5b276a9f4660d88f1b17d94e378a3dd8a0cb5c39cb450f25c203d8e` | 317,447 |
| `books/software-foundations/quickchick.tgz` | `6c632e62a68413e9760643c6d42ac58a5989e2d236d67cdddc099b38c06ee126` | 5,181,232 | `books/software-foundations/quickchick.epub` | `95c47897af0c7624da38102e82d6d7d0749f77d61e78a589cb3f1bceca6bf5a3` | 248,370 |
| `books/software-foundations/verifiable-c.tgz` | `471c2a7dbcd78afb3a8499f44ed75c79da2bb77427bc882f9084f5c1bb3131b2` | 6,189,426 | `books/software-foundations/verifiable-c.epub` | `3cfdf942225e8c7d3e8e4cb88bf326fb0be7bdf38a655d34bd2236c29afef9bd` | 260,646 |
| `books/software-foundations/separation-logic-foundations.tgz` | `25013f1cf8c0ab174552a08c98dade611383699b1f20bb5bf2ec183ccd4320c9` | 6,002,037 | `books/software-foundations/separation-logic-foundations.epub` | `82691e183b15a97b3e5700986a015f2db9c5042e4b98f9bf0f0f3526697b9434` | 689,997 |
| `books/software-foundations/security-foundations.tgz` | `15d5b786ff8916fd1191b95d7d8bf6458d79acd95bafd52d2415e8d3a225dbdb` | 5,311,240 | `books/software-foundations/security-foundations.epub` | `2e9aa772d6922a956d97aefac6ddaf1a7b92f18d7cbb0b0b66f0ea142763b29b` | 257,224 |

The source hashes above remain historical acquisition evidence in
`manifests/free-study-expansion-2026-08-20.sha256` and in each EPUB's metadata
record. The canonical `manifests/library.sha256` describes only the current
retained shelf.

## Reading-content boundaries

- **Crafting Interpreters:** complete published book text, code listings, and
  183 image references were retained. Repository code, build inputs, and site
  chrome were excluded.
- **Software Engineering at Google:** the complete official book, copyright
  page, figures, and author biographies were retained. Abseil repository and
  website machinery were excluded.
- **Physically Based Rendering, 4th Edition:** all 166 pages linked by the
  fourth-edition table of contents were retained with code, figures, equations,
  and nested navigation. The third-edition mirror, EXR viewer payloads,
  JavaScript/framework files, fonts, icons, and repository machinery were
  excluded.
- **Software Foundations:** published prose plus readable code and proof
  listings were retained. Raw `.v` proof sources and build/site machinery were
  excluded. The exact bundled MIT notice is included as the final section of
  every volume.

## Validation performed before cleanup

`scripts/build_readable_books.py` validates the EPUB ZIP structure, mimetype,
OPF manifest and spine, XML parsing, unique IDs, embedded images, internal links
and anchors, SVG glyph targets, required license text, and absence of raw source
extensions. All ten editions passed. PBRT received an additional rendered
dark-mode inspection after its MathJax equations were given intact glyph
references, inline/display layout, accessible descriptions, and light/dark
colors. Covers and representative chapters from the other editions were also
rendered and inspected.

## Cleanup and recovery

After source/output hashes were paired and all validation passed, the three ZIP
files, seven TGZ files, and the generated `work/` conversion directory were
moved with macOS `trash` to `/Users/danny/.Trash/` on 2026-08-21. They are
recoverable until Trash is emptied. Emptying Trash permanently reclaims roughly
2.9 GB, including the temporary extracted conversion trees.

To rebuild later, restore or reacquire the exact source filenames recorded
above and in metadata, install Pandoc plus Python `lxml` and Pillow, then run:

```bash
python3 scripts/build_readable_books.py --force
python3 scripts/build_readable_books.py --validate-only
```

## Additional normalized conversion found by the final audit

The audit also found `books/Programming Pearls.pdf`, a Calibre 8.4.0 conversion
of the previously cataloged OCR EPUB. Representative cover, prose, diagram,
code, and late-book pages were rendered with Poppler; the PDF is valid,
unencrypted, 472 pages long, searchable on text pages, and keeps some code
plates as image-only pages. It was normalized to
`books/programming-pearls-2e.pdf`, and its metadata retains the original EPUB
hash, byte count, quality warning, and Trash recovery path.
