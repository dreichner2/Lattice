# Free study expansion - 2026-08-20

This batch adds 21 catalog entries represented by 27 local artifacts. Every
artifact came from an author, publisher, university, standards body, or official
project repository. Each file has a mirrored JSON record under `metadata/` with
its source URL, access or license note, byte size, SHA-256, and acquisition time.
The independent batch hashes are in
`manifests/free-study-expansion-2026-08-20.sha256`.

## Added coverage

- Java: *Think Java, 2e*, the Java SE 26 Language Specification, and the Java
  SE 26 Virtual Machine Specification.
- Mathematics and statistics: *OpenIntro Statistics, 4e*, all three OpenStax
  Calculus volumes, *Mathematics for Machine Learning*, and *Convex
  Optimization*.
- Programming languages and formal methods: the complete official *Crafting
  Interpreters* source archive, PLAI 3.2.5, *Specifying Systems*, and all seven
  current *Software Foundations* volume source archives.
- Systems and engineering: *Security Engineering, 3e* and the complete
  official HTML source for *Software Engineering at Google*.
- Machine learning and responsible computing: *Probabilistic Machine Learning:
  An Introduction*, *Understanding Deep Learning*, *An Introduction to
  Statistical Learning with Applications in Python*, *Fairness and Machine
  Learning*, and the ACM Code of Ethics.
- Graphics: the pinned official PBRT website repository, including the complete
  fourth-edition web text, figures, and related source assets.

## Completeness checks

- All 17 added PDFs have valid PDF signatures and page trees. The PDFs range
  from the 10-page ACM standard to the 1,212-page *Security Engineering* text.
- The calculus PDFs contain 873, 737, and 1,023 pages respectively.
- The Java Language and Virtual Machine specifications contain 892 and 624
  pages respectively; *Think Java* contains 372 pages.
- The *Crafting Interpreters* archive contains 40 Markdown book-source files.
- The Google software-engineering archive contains 40 book HTML documents.
- The PBRT archive contains 168 fourth-edition HTML documents and 929 files
  under its `4ed/` tree (951 archive entries including directories).
- The seven *Software Foundations* gzip-compressed tar archives open cleanly.
  Their release versions are LF 7.1, PLF 7.0, VFA 2.0, QuickChick 2.0,
  Verifiable C 2.0, SLF 3.0, and Security Foundations 1.0.
- At batch completion, `python3 scripts/fetch.py verify` checked 138 artifacts
  with no failures. The later shelf cleanup removed 68 OSTEP source chapters
  and one redundant sample chapter. Three later user-supplied/gated downloads
  bring the current normalized shelf to 72 verified artifacts with no failures.

## Access and reuse boundaries

"Free to access" does not always mean "openly licensed." The catalog and
metadata records preserve each distinction. In particular, *Specifying Systems* is a
personal-use copy; the Oracle specifications use Oracle's limited license;
several publisher-authorized PDFs remain copyrighted; and the no-derivatives
licenses on several web books do not permit republishing altered editions.

OpenStax's current pages additionally state that its textbook content may not
be used for LLM training or otherwise ingested into generative-AI offerings
without permission. The local OpenStax PDFs are for the user's personal study;
AI tools should not ingest them unless OpenStax permission covers that use.

## Free titles originally gated

The initial automated pass stopped at these publisher/author gates:

- *Introduction to Probability, 2e* (Blitzstein and Hwang): the official free
  Google Drive viewer currently says only the owner and editors may download
  the file. The online copy remains readable at `https://probabilitybook.net/`.
- *Distributed Systems, 4e* (van Steen and Tanenbaum): version 4.03 is free as a
  personalized PDF, but the official form requires a valid email address and a
  CAPTCHA: `https://www.distributed-systems.net/index.php/books/ds4/ds4-ebook/`.
- *Computer Vision: Algorithms and Applications, 2e* (Szeliski): the official
  personal-copy form requires a name and email address:
  `https://szeliski.org/Book/download.php`.

No download control was bypassed and no identity or email address was invented
or submitted by the automation.

### Follow-up

The user later completed the official forms for *Distributed Systems, 4e* and
*Computer Vision: Algorithms and Applications, 2e*. Their personalized PDFs
are now stored locally as `books/distributed-systems-4e.pdf` and
`books/computer-vision-2e.pdf`, with local-only metadata that records the
no-redistribution boundary. The user also supplied *Introduction to
Probability, 2e* as `books/introduction-probability-2e.pdf`; its metadata points
to the official author-linked viewer but does not claim that automation
bypassed the viewer's disabled-download state.
