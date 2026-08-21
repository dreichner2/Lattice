# Library Rules

These rules keep the shelf clean after the current reorganization.

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
- keep the format extension honest: PDF, EPUB, ZIP, TGZ, or TXT.

The title and full author list belong in metadata, not in the filename.

## 3. Metadata is separate from reading material

Each local payload has exactly one JSON record at the mirrored path under
`metadata/`, with the payload extension replaced by `.json`:

```text
books/sicp.pdf                   → metadata/books/sicp.json
papers/mit-6006/lec-01.pdf      → metadata/papers/mit-6006/lec-01.json
```

At minimum, a record must include `title`, `path`, `license`, `bytes`, and a
64-character lowercase `sha256`. Known source URLs, authors, edition/version,
and acquisition dates stay in the same record. Unknown legacy provenance is
written as unknown; it is never guessed.

## 4. Duplicate policy

`python3 scripts/fetch.py audit` must report zero exact duplicate groups.
Logical redundancy is reviewed separately because a merged book and its source
chapters will not share a byte hash. If a redundant item is removed, prefer a
recoverable move to Trash and record what remains authoritative.

## 5. Source and access policy

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

## 6. Remote policy

Git tracks the catalog, study guide, rules, source metadata, provenance, hash
manifests, and tooling. `/books/` and `/papers/` are local-only and ignored.
This is deliberate: the shelf contains mixed rights and should not be
republished merely because the repository is private.

Do not force-add a book or paper payload. If a separate content backup is ever
needed, choose a storage system and rights policy explicitly rather than
silently turning GitHub into an ebook host.

## 7. Safe update sequence

After adding, replacing, or removing material:

1. Normalize the filename and create/update its metadata record.
2. Update the one logical row in `CATALOG.md` and the study guide if relevant.
3. Run `python3 scripts/fetch.py self-test`.
4. Run `python3 scripts/fetch.py verify`.
5. Run `python3 scripts/fetch.py manifest`.
6. Run `python3 scripts/fetch.py audit`.
7. Review `git status` and stage explicit tracked paths only.

Extract large web/source archives outside `books/` and `papers/`. Those folders
are the canonical payload shelf, not a scratch directory.
