<p align="center">
  <img src="assets/library-banner.svg" alt="CS Library — a source-traceable shelf for serious computer science study" width="100%">
</p>

<p align="center">
  <strong>47 works</strong> · <strong>72 verified artifacts</strong> ·
  <strong>0 exact duplicates</strong> · <strong>9 subject shelves</strong>
</p>

<p align="center">
  A clean, local-first computer-science library with short filenames, recorded
  provenance, reproducible checksums, and an actual study path.
</p>

---

| | Go here when you want to… |
|---|---|
| 📚 **[Browse the catalog](CATALOG.md)** | Open every local book or course file, grouped by subject, with provenance kept separate. |
| 🧭 **[Follow the study guide](STUDY_GUIDE.md)** | Turn the shelf into an ordered curriculum, including a Java-first route. |
| 🧾 **[Read the library rules](LIBRARY_RULES.md)** | Understand naming, deduplication, metadata, and remote-storage policy. |
| 🔎 **[Inspect provenance](notes/provenance/)** | Review import history, source gates, licenses, and acquisition caveats. |

## Open the Mac app

Double-click **`CS Library.app`** in this folder. The macOS app uses the shared
library interface for browsing, a native PDFKit workspace for PDFs, and the
immersive EPUB reader for reflowable books. It starts the private local service
when needed and shuts down the copy it owns when you quit.

Rebuild the app after changing its native wrapper:

```bash
./scripts/build-macos-app.sh
```

The generated app stays local and is intentionally ignored by Git. Its native
source, icon, build script, and the shared web interface are versioned.

## Open the Windows app

Download the Windows artifact from CI or build it on Windows:

```powershell
.\windows\build-windows.ps1
```

The portable package contains **`CS Library.exe`**, a bundled loopback-only
server, the same shelf UI, the immersive EPUB layer, and an offline PDF.js
workspace with thumbnails, text search, bookmarks, notes, resume position,
selected-text capture, focus mode, and Markdown export. On first launch, select
the folder containing this library. No Python installation is required by the
packaged Windows build.

## Browser option

Double-click **`open-library.command`** in Finder. It starts the private local
catalog and opens it in your browser. Keep the small Terminal window open while
you use the library; press Control-C or close that window when you are done.

You can also launch it from Terminal:

```bash
./open-library.command
```

The interface provides:

- instant search across titles, authors, subjects, formats, and filenames;
- first-class views for 39 books, 20 lecture PDFs, seven course volumes, two
  papers, two specifications, and two professional/technical standards;
- subject shelves plus favorites, currently-reading, and finished views;
- a responsive grid/list layout and light/dark themes;
- an in-app EPUB reader with chapter navigation, searchable contents, bookmarks,
  resume position, typography controls, page tones, and next/previous controls;
- native PDFKit reading on macOS and an offline PDF.js workspace on Windows,
  with resume state, search, bookmarks, notes, thumbnails, zoom, and focus mode;
- embedded text reading plus explicit operating-system and file-manager actions;
- a study guide whose book and course links open the matching local material
  directly, plus the catalog, provenance notes, rules, and integrity manifest
  rendered inside a polished library reading desk instead of raw browser pages;
- live filesystem updates: added PDFs/EPUBs/texts appear immediately as cleanly
  titled **New arrivals**, and removed files disappear without a reload;
- one-click opening in the default Mac app or revealing a file in Finder;
- expandable access to all 20 MIT 6.006 lectures and all seven readable
  Software Foundations volumes;
- reading status and recent activity stored only in the local interface.

The server binds only to `127.0.0.1`. It has no upload feature, does not expose
a network-facing listener, and only permits file actions for readable files
currently present beneath `books/` or `papers/`. The books remain exactly where
they are; live discovery indexes them without moving or renaming their bytes.

## Start here

Choose one lane and begin building things immediately:

- **Java-first:** `books/think-java-2e.pdf` → small console projects →
  `papers/mit-6006/` → `books/jls-26.pdf` and `books/jvms-26.pdf` as references.
- **General CS:** `books/think-python-2e.pdf` →
  `books/openstax-intro-cs.pdf` → `books/sicp.pdf` → algorithms and systems.
- **Already programming:** start with `books/clrs-4e.pdf`,
  `books/ostep.pdf`, and `books/crafting-interpreters.epub`, while filling math
  gaps from `books/concrete-math-2e.pdf`.

The [study guide](STUDY_GUIDE.md) turns those starting points into a full
sequence with projects and exit criteria.

## Shelf at a glance

| Shelf | Works | Good first pick |
|---|---:|---|
| Foundations & programming | 7 | Think Java 2e or Think Python 2e |
| Algorithms & data structures | 2 | MIT 6.006 lecture notes |
| Systems, networks & security | 5 | OSTEP |
| Software engineering & design | 6 | Software Engineering at Google |
| Mathematics & statistics | 8 | Introduction to Probability or OpenIntro Statistics |
| AI & machine learning | 9 | ISL with Python |
| Languages & formal methods | 7 | Crafting Interpreters |
| Computer graphics & vision | 2 | PBRT 4e or Szeliski |
| Ethics & professional practice | 1 | ACM Code of Ethics |

## Everyday commands

Run these from the repository root:

```bash
# See what is physically present on this Mac
python3 scripts/fetch.py list

# Validate format, byte count, metadata path, and SHA-256 for every artifact
python3 scripts/fetch.py verify

# Check metadata coverage, filename hygiene, manifest parity, and duplicates
python3 scripts/fetch.py audit

# Browse curated, authorized downloads
python3 scripts/fetch.py book
python3 scripts/fetch.py sets

# Examples
python3 scripts/fetch.py book think-java
python3 scripts/fetch.py book mit-6006
python3 scripts/fetch.py download 1706.03762
python3 scripts/fetch.py rfc 9110

# Run deterministic tests without touching the network
python3 scripts/fetch.py self-test

# Update only after an intentional shelf change
python3 scripts/fetch.py manifest
```

Downloads are streamed to a temporary file, validated before installation,
hashed, and recorded under `metadata/`. ZIP, EPUB, and TGZ archives are opened
and structurally tested during verification.

## Clean layout

```text
cs-library/
├── README.md                  # landing page
├── CATALOG.md                 # authoritative, subject-grouped shelf
├── STUDY_GUIDE.md             # learning order and project checkpoints
├── LIBRARY_RULES.md           # naming, dedupe, provenance, remote policy
├── assets/                    # GitHub-facing artwork
├── metadata/                  # one tracked JSON record per local artifact
├── manifests/                 # stable SHA-256 inventories
├── notes/provenance/          # acquisition and license history
├── native/                    # macOS app, durable reader store, and shared scripts
├── windows/                   # WPF/WebView2 app and offline PDF.js reader
├── scripts/fetch.py           # fetch, list, verify, audit, manifest
├── scripts/build_readable_books.py # reproducible source-to-EPUB conversion
├── scripts/build-macos-app.sh # builds the double-clickable native app
├── scripts/library_ui.py      # loopback-only virtual-library server
├── ui/                        # local bookshelf interface
├── CS Library.app/            # generated local Mac app; ignored by Git
├── open-library.command       # double-click Mac launcher
├── books/                     # local payloads; ignored by Git
└── papers/                    # local payloads; ignored by Git
```

Book filenames are lowercase kebab-case, descriptive, and capped at 48
characters. Course material uses predictable sequence names such as
`papers/mit-6006/lec-01.pdf`. Metadata lives separately so the reading folders
contain reading material—not bookkeeping clutter.

## Why the remote is metadata-first

This shelf mixes open works, author-authorized personal copies, and legacy
imports whose redistribution history was not preserved. GitHub therefore
stores the catalog, metadata, checksums, provenance, and fetch tooling, while
the book and paper payloads remain local. This avoids accidentally
republishing copyrighted material and keeps the repository fast to clone.

The remote is still enough to answer: *What belongs on the shelf? Which exact
bytes did I verify? Where did an authorized copy come from? What is missing?*
For freely downloadable entries, `scripts/fetch.py` can repopulate the local
payload from the recorded official source.

## Important access boundary

OpenStax's current terms permit human reading but prohibit using its textbooks
for LLM training or otherwise ingesting them into generative-AI offerings
without permission. AI workflows must exclude `books/openstax-*` unless
OpenStax has granted applicable permission. Other works have their own terms;
“free to read” never automatically means “free to redistribute or train on.”

## Current integrity state

- 47 logical works represented by 72 artifacts
- 72/72 artifacts pass full format, size, metadata, and SHA-256 verification
- 0 byte-identical duplicate groups
- 0 filenames outside the short kebab-case convention
- OSTEP chapter copies and the Crafting Interpreters sample removed after their
  complete retained editions were verified
- Ten web/source bundles replaced by searchable EPUB editions after structural
  and visual validation; original hashes and conversion boundaries are recorded
  under `notes/provenance/`
- Canonical inventory: `manifests/library.sha256`

The personalized *Distributed Systems, 4e* and *Computer Vision: Algorithms and
Applications, 2e* copies were added after the user completed their official
forms. The user also supplied *Introduction to Probability, 2e*, whose official
author-linked Drive viewer had blocked automated downloading. No access gate
was bypassed by the library tooling.
