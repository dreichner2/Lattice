# Library Rules

These rules keep Lattice consistent across subjects, computers, and
metadata sources.

## 1. One logical work, one catalog row

A logical work may contain several artifacts—MIT 6.006 has 20 lecture PDFs and
Software Foundations has seven readable EPUB volumes—but it appears once in
`CATALOG.md`. Alternate packaging is kept only when it adds genuinely different
value. A sample chapter is not retained beside the complete work, and source
chapters are not retained beside a verified complete compilation.

## 2. Short, stable filenames

Payload names must:

- use lowercase kebab-case;
- be 48 characters or fewer, including the extension;
- carry an edition only when it distinguishes the work (`clrs-4e.pdf`);
- avoid author names, download hashes, dates, and full subtitles;
- use zero-padded sequence numbers for ordered sets (`lec-01.pdf`);
- keep the format extension honest: PDF, EPUB, ZIP, TGZ, TXT, MP3, M4A, WAV,
  or FLAC.

The title and full author list belong in metadata, not in the filename.

## 3. Curated and private metadata are separate from reading material

Each curated payload has exactly one JSON record at the mirrored path under
`metadata/`, with the payload extension replaced by `.json`:

```text
books/sicp.pdf                   → metadata/books/sicp.json
papers/mit-6006/lec-01.pdf      → metadata/papers/mit-6006/lec-01.json
```

At minimum, a record must include `title`, `path`, `license`, `bytes`, and a
64-character lowercase `sha256`. Known source URLs, authors, edition/version,
and acquisition dates stay in the same record. Unknown legacy provenance is
written as unknown; it is never guessed.

That mirrored `metadata/` form is the Git-tracked authority for curated catalog
material. Normal UI imports instead write a private sidecar adjacent to the
payload, appending `.library.json` to the complete filename:

```text
books/example.pdf                 → books/example.pdf.library.json
papers/example.epub               → papers/example.epub.library.json
audio/example.mp3                 → audio/example.mp3.library.json
```

Keeping the payload extension prevents same-stem imports from colliding.
Sidecars are ignored by Git and synchronized through Syncthing. They must
follow schema version 2 and retain server-owned path, material type, byte count,
SHA-256, access, and import-provenance fields.

## 4. Subjects and topics are different

`library-taxonomy.json` is the authority for stable, broad subject IDs. A
**subject** is a discipline such as computer science, electrical engineering,
computer engineering, mathematics, or physics. A **topic** is a narrower,
editable description such as distributed systems, circuit analysis, or linear
algebra.

The existing curated catalog defaults to `computer-science`, with topic-level
defaults and selected work overrides recorded in the taxonomy. A new import
defaults to `other` when neither local metadata nor a validated suggestion gives
a known subject. Add new subject IDs to the taxonomy rather than inventing a
one-off value in a sidecar.

## 5. Duplicate policy

`python3 scripts/fetch.py audit` must report zero exact duplicate groups.
Logical redundancy is reviewed separately because a merged book and its source
chapters will not share a byte hash. If a redundant item is removed, prefer a
recoverable move to Trash and record what remains authoritative.

## 6. Source and access policy

- Prefer an author, publisher, standards body, university, or recognized open
  repository.
- Record “official free,” “open license,” and “personal use” separately; they
  are not interchangeable.
- Do not automate identity, email, payment, CAPTCHA, or disabled-download gates.
- Do not add an acquisition tool whose primary purpose is bypassing publisher
  access controls.
- Keep legacy imports with missing rights information local and clearly marked.
- OpenStax material is excluded from generative-AI ingestion unless OpenStax
  grants applicable permission.

The optional Codex import assistant may receive only the filename, selected
material kind, locally extracted embedded publication metadata, and allowed
subject list. It must not receive payload bytes or full text. Its descriptive
suggestions remain editable and untrusted; it cannot
change access, path, byte count, SHA-256, or import provenance. Import must still
finish with deterministic local fallback metadata if Codex is absent, signed
out, unavailable, or invalid.

## 7. Remote policy

Git tracks the catalog, study guide, rules, source metadata, provenance, hash
manifests, tooling, and hidden `.gitkeep` files that create the required
`/books/`, `/papers/`, `/lectures/`, `/audio/`, and nested collection
directories. The payloads inside those directories remain local-only and
ignored. This is deliberate: the shelf contains mixed rights and should not be
republished merely because the repository is private.

Syncthing is the private payload transport. Its repository-root `.stignore`
allowlists only `books/`, `papers/`, `lectures/`, and `audio/`. Private
`.library.json` sidecars sync because they sit inside those roots; curated
catalog metadata, taxonomy, and app source continue to come from GitHub.
Syncthing must not be used to mirror `.git/`, build output, Codex credentials,
or a live SQLite database.

The per-device vault may release only a curated payload that has durable
tracked metadata. Its adjacent sidecar is never released. Check out first
creates a verified copy; the separate release action journals and establishes
an effective exact-path Syncthing ignore before unlinking the payload. Restore
must not overwrite an unexpected local file. New-arrival imports remain local
and synchronized until they are intentionally curated.

Do not force-add a book, paper, lecture, or private sidecar. If a separate
content backup is ever
needed, choose a storage system and rights policy explicitly rather than
silently turning GitHub into an ebook host.

## 8. Safe update sequence

For an ordinary private import:

1. Drag the file into the app or choose **Add**.
2. Select the payload kind and review the generated title, subject, and topics.
   Audio belongs only under **Audio**; documents belong under Book, Paper, or
   Lecture.
3. Confirm that the item opens and its sidecar reports the expected path and
   subject.
4. Let Syncthing finish before editing the same item from the other computer.

For an intentional curated-catalog addition, replacement, or removal:

1. Normalize the filename and create/update its metadata record.
2. Update the one logical row in `CATALOG.md` and the study guide if relevant.
3. Run `python3 scripts/fetch.py self-test`.
4. Run `python3 scripts/fetch.py verify`.
5. Run `python3 scripts/fetch.py manifest`.
6. Run `python3 scripts/fetch.py audit`.
7. Review `git status` and stage explicit tracked paths only.

Extract large web/source archives outside `books/` and `papers/`. Those folders
are the canonical payload shelf, not a scratch directory.
