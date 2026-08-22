# Lattice Catalog

> **96 readable works · 125 readable artifacts · 0 exact duplicates**
> Last reorganized and fully verified: 2026-08-21

This is the authoritative index for Lattice's initial computer-science
collection. Every title links directly to the local PDF, EPUB, text, or course
folder. Official webpages live in a separate `Source` column. Binary payloads
are intentionally not published to GitHub—see [Library rules](LIBRARY_RULES.md)—but
every curated payload has tracked metadata under `metadata/` and a checksum in
`manifests/library.sha256`.

Broad subject IDs and current catalog defaults are defined in
[`library-taxonomy.json`](library-taxonomy.json). Shelf headings below remain
useful topic groupings; they are not the complete list of supported subjects.
Private imports in any subject use adjacent `.library.json` sidecars and do not
need a row here.

## Jump to a shelf

[Foundations](#foundations--programming) ·
[Algorithms](#algorithms--data-structures) ·
[Systems](#systems-networks--security) ·
[Software engineering](#software-engineering--design) ·
[Math](#mathematics--statistics) ·
[AI/ML](#artificial-intelligence--machine-learning) ·
[Languages](#programming-languages--formal-methods) ·
[Graphics/vision](#computer-graphics--vision) ·
[Ethics](#ethics--professional-practice)

### Access legend

| Mark | Meaning |
|---|---|
| 🟢 Open | An open license is recorded; follow its exact conditions. |
| 🔵 Official free | Author/publisher-authorized access; reuse may be narrower than reading. |
| 🟣 Human study | OpenStax permits human reading but currently restricts generative-AI ingestion without permission. |
| 🟠 Local import | Acquisition URL or redistribution rights were not preserved; keep local. |
| ⚪ Source terms | Consult the linked standard, specification, or source record. |

## Foundations & Programming

| Book | Author(s) | Edition | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: openstax-intro-cs --> [Introduction to Computer Science](books/openstax-intro-cs.pdf) | OpenStax contributors | 2024 | `books/openstax-intro-cs.pdf` | [source](https://openstax.org/details/books/introduction-computer-science) | 🟣 Human study |
| <!-- work: sicp --> [Structure and Interpretation of Computer Programs](books/sicp.pdf) | Abelson, Sussman | 2e | `books/sicp.pdf` | [source](https://web.mit.edu/6.001/6.037/sicp.pdf) | 🔵 Official free |
| <!-- work: sicp-js --> [Structure and Interpretation of Computer Programs: JavaScript Edition](books/sicp-js.pdf) | Abelson, Sussman; Henz, Wrigstad | 2022 | `books/sicp-js.pdf` | — | 🟠 Local import |
| <!-- work: think-python-2e --> [Think Python](books/think-python-2e.pdf) | Allen B. Downey | 2e | `books/think-python-2e.pdf` | [source](https://greenteapress.com/thinkpython2/thinkpython2.pdf) | 🟢 Open |
| <!-- work: think-java-2e --> [Think Java](books/think-java-2e.pdf) | Downey, Mayfield | 2e | `books/think-java-2e.pdf` | [source](https://greenteapress.com/wp/think-java-2e/) | 🟢 Open |
| <!-- work: c-programming-language --> [The C Programming Language](books/c-programming-language-1e.pdf) | Kernighan, Ritchie | 1e | `books/c-programming-language-1e.pdf` | — | 🟠 Local import |
| <!-- work: programming-pearls --> [Programming Pearls](books/programming-pearls-2e.pdf) | Jon Bentley | 2e | `books/programming-pearls-2e.pdf` | — | 🟠 Local import |

## Algorithms & Data Structures

| Book | Author(s) | Edition | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: clrs --> [Introduction to Algorithms](books/clrs-4e.pdf) | Cormen, Leiserson, Rivest, Stein | 4e | `books/clrs-4e.pdf` | — | 🟠 Local import |
| <!-- work: mit-6006 --> [MIT 6.006 Introduction to Algorithms — Lecture Notes](papers/mit-6006/) | MIT OpenCourseWare | Spring 2020 | `papers/mit-6006/` (20 PDFs) | [source](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/) | 🟢 Open |

## Systems, Networks & Security

| Book | Author(s) | Edition | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: ostep --> [Operating Systems: Three Easy Pieces](books/ostep.pdf) | Arpaci-Dusseau, Arpaci-Dusseau | v1.10 | `books/ostep.pdf` | [source](https://pages.cs.wisc.edu/~remzi/OSTEP/) | 🔵 Official free chapters |
| <!-- work: distributed-systems --> [Distributed Systems](books/distributed-systems-4e.pdf) | van Steen, Tanenbaum | 4e, v4.03x | `books/distributed-systems-4e.pdf` | [source](https://www.distributed-systems.net/index.php/books/ds4/) | 🔵 Personalized copy |
| <!-- work: art-of-unix-programming --> [The Art of Unix Programming](books/art-of-unix-programming.pdf) | Eric S. Raymond | 2003 | `books/art-of-unix-programming.pdf` | — | 🟠 Local import |
| <!-- work: security-engineering --> [Security Engineering](books/security-engineering-3e.pdf) | Ross Anderson | 3e | `books/security-engineering-3e.pdf` | [source](https://www.cl.cam.ac.uk/archive/rja14/book.html) | 🔵 Official free |
| <!-- work: rfc-791 --> [RFC 791 — Internet Protocol](papers/rfc-791.txt) | RFC Editor | 1981 | `papers/rfc-791.txt` | [source](https://www.rfc-editor.org/rfc/rfc791.txt) | ⚪ Source terms |

## Software Engineering & Design

| Book | Author(s) | Edition | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: clean-code --> [Clean Code](books/clean-code.pdf) | Robert C. Martin | 2008 | `books/clean-code.pdf` | — | 🟠 Local import |
| <!-- work: design-patterns --> [Design Patterns](books/design-patterns.pdf) | Gamma, Helm, Johnson, Vlissides | 1994 | `books/design-patterns.pdf` | — | 🟠 Local import |
| <!-- work: refactoring --> [Refactoring](books/refactoring-1e.pdf) | Martin Fowler | 1e | `books/refactoring-1e.pdf` | — | 🟠 Local import |
| <!-- work: pragmatic-programmer --> [The Pragmatic Programmer](books/pragmatic-programmer-1e.pdf) | Hunt, Thomas | 1e | `books/pragmatic-programmer-1e.pdf` | — | 🟠 Local import |
| <!-- work: mythical-man-month --> [The Mythical Man-Month](books/mythical-man-month.epub) | Frederick P. Brooks Jr. | Not recorded | `books/mythical-man-month.epub` | — | 🟠 Local import |
| <!-- work: software-engineering-google --> [Software Engineering at Google](books/software-engineering-google.epub) | Winters, Manshreck, Wright | 2020 | `books/software-engineering-google.epub` | [source](https://abseil.io/resources/swe-book) | 🔵 Official free |

## Mathematics & Statistics

| Book | Author(s) | Edition | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: concrete-math --> [Concrete Mathematics](books/concrete-math-2e.pdf) | Graham, Knuth, Patashnik | 2e | `books/concrete-math-2e.pdf` | — | 🟠 Local import |
| <!-- work: introduction-probability --> [Introduction to Probability](books/introduction-probability-2e.pdf) | Blitzstein, Hwang | 2e | `books/introduction-probability-2e.pdf` | [source](https://probabilitybook.net/) | 🔵 Author-linked copy |
| <!-- work: openintro-statistics --> [OpenIntro Statistics](books/openintro-statistics-4e.pdf) | Diez, Çetinkaya-Rundel, Barr | 4e | `books/openintro-statistics-4e.pdf` | [source](https://www.openintro.org/book/os/) | 🟢 Open |
| <!-- work: openstax-calculus-1 --> [Calculus, Volume 1](books/openstax-calculus-1.pdf) | Strang, Herman | 2016 | `books/openstax-calculus-1.pdf` | [source](https://openstax.org/details/books/calculus-volume-1) | 🟣 Human study |
| <!-- work: openstax-calculus-2 --> [Calculus, Volume 2](books/openstax-calculus-2.pdf) | Strang, Herman | 2016 | `books/openstax-calculus-2.pdf` | [source](https://openstax.org/details/books/calculus-volume-2) | 🟣 Human study |
| <!-- work: openstax-calculus-3 --> [Calculus, Volume 3](books/openstax-calculus-3.pdf) | Strang, Herman | 2016 | `books/openstax-calculus-3.pdf` | [source](https://openstax.org/details/books/calculus-volume-3) | 🟣 Human study |
| <!-- work: math-for-ml --> [Mathematics for Machine Learning](books/math-for-ml.pdf) | Deisenroth, Faisal, Ong | 2020 | `books/math-for-ml.pdf` | [source](https://mml-book.github.io/) | 🔵 Official free |
| <!-- work: convex-optimization --> [Convex Optimization](books/convex-optimization.pdf) | Boyd, Vandenberghe | 2004 | `books/convex-optimization.pdf` | [source](https://web.stanford.edu/~boyd/cvxbook/) | 🔵 Official free |

## Artificial Intelligence & Machine Learning

| Book | Author(s) | Edition | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: aima --> [Artificial Intelligence: A Modern Approach](books/aima-4e.pdf) | Russell, Norvig | 4e | `books/aima-4e.pdf` | — | 🟠 Local import |
| <!-- work: reinforcement-learning --> [Reinforcement Learning: An Introduction](books/reinforcement-learning-2e.pdf) | Sutton, Barto | 2e | `books/reinforcement-learning-2e.pdf` | — | 🟠 Local import |
| <!-- work: speech-language-processing --> [Speech and Language Processing](books/slp-3e-draft.pdf) | Jurafsky, Martin | 3e draft (2026) | `books/slp-3e-draft.pdf` | — | 🟠 Local import |
| <!-- work: pml-intro --> [Probabilistic Machine Learning: An Introduction](books/pml-intro.pdf) | Kevin P. Murphy | 2025 draft | `books/pml-intro.pdf` | [source](https://probml.github.io/pml-book/book1.html) | 🟢 Open |
| <!-- work: understanding-deep-learning --> [Understanding Deep Learning](books/understanding-deep-learning.pdf) | Simon J. D. Prince | v5.0.3 | `books/understanding-deep-learning.pdf` | [source](https://mitpress.mit.edu/9780262377102/understanding-deep-learning/) | 🔵 Open access |
| <!-- work: isl-python --> [An Introduction to Statistical Learning with Applications in Python](books/isl-python.pdf) | James, Witten, Hastie, Tibshirani, Taylor | 2023 | `books/isl-python.pdf` | [source](https://www.statlearning.com/) | 🔵 Official free |
| <!-- work: fairness-ml --> [Fairness and Machine Learning](books/fairness-ml.pdf) | Barocas, Hardt, Narayanan | 2023 | `books/fairness-ml.pdf` | [source](https://www.fairmlbook.org/) | 🟢 Open |
| <!-- work: attention --> [Attention Is All You Need](papers/attention-is-all-you-need.pdf) | Vaswani et al. | arXiv v7 | `papers/attention-is-all-you-need.pdf` | [source](https://arxiv.org/abs/1706.03762v7) | ⚪ arXiv terms |
| <!-- work: double-dqn-scheduling --> [Dynamic Operating System Scheduling Using Double DQN](papers/double-dqn-scheduling.pdf) | Sun et al. | arXiv v1 | `papers/double-dqn-scheduling.pdf` | [source](https://arxiv.org/abs/2503.23659v1) | ⚪ arXiv terms |

## Programming Languages & Formal Methods

| Book | Author(s) | Edition | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: dragon-book --> [Compilers: Principles, Techniques, and Tools](books/dragon-book-2e.pdf) | Aho, Lam, Sethi, Ullman | 2e | `books/dragon-book-2e.pdf` | — | 🟠 Local import |
| <!-- work: crafting-interpreters --> [Crafting Interpreters](books/crafting-interpreters.epub) | Robert Nystrom | 2021 | `books/crafting-interpreters.epub` | [source](https://craftinginterpreters.com/) | 🔵 Official free |
| <!-- work: plai --> [Programming Languages: Application and Interpretation](books/plai-3e.pdf) | Shriram Krishnamurthi | v3.2.5 | `books/plai-3e.pdf` | [source](https://www.plai.org/) | 🟢 Open |
| <!-- work: software-foundations --> [Software Foundations](books/software-foundations/) | Pierce et al. | 7 current volumes | `books/software-foundations/` (7 EPUBs) | [source](https://softwarefoundations.cis.upenn.edu/) | 🟢 Open |
| <!-- work: jls --> [The Java Language Specification](books/jls-26.pdf) | Gosling et al. | Java SE 26 | `books/jls-26.pdf` | [source](https://docs.oracle.com/javase/specs/jls/se26/html/) | ⚪ Oracle terms |
| <!-- work: jvms --> [The Java Virtual Machine Specification](books/jvms-26.pdf) | Lindholm et al. | Java SE 26 | `books/jvms-26.pdf` | [source](https://docs.oracle.com/javase/specs/jvms/se26/html/) | ⚪ Oracle terms |
| <!-- work: specifying-systems --> [Specifying Systems](books/specifying-systems.pdf) | Leslie Lamport | 2002 | `books/specifying-systems.pdf` | [source](https://lamport.azurewebsites.net/tla/book.html) | 🔵 Personal use |

## Computer Graphics & Vision

| Book | Author(s) | Edition | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: pbrt --> [Physically Based Rendering](books/pbrt-4e.epub) | Pharr, Jakob, Humphreys | 4e | `books/pbrt-4e.epub` | [source](https://www.pbr-book.org/4ed/) | 🔵 Official free |
| <!-- work: computer-vision --> [Computer Vision: Algorithms and Applications](books/computer-vision-2e.pdf) | Richard Szeliski | 2e | `books/computer-vision-2e.pdf` | [source](https://szeliski.org/Book/) | 🔵 Personalized copy |

## Ethics & Professional Practice

| Book | Author(s) | Edition | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: acm-code --> [ACM Code of Ethics and Professional Conduct](papers/acm-code-of-ethics.pdf) | Association for Computing Machinery | 2018 | `papers/acm-code-of-ethics.pdf` | [source](https://www.acm.org/code-of-ethics) | 🔵 Official free |


## Open Textbooks & Reference

| Book | Author(s) | Edition | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: books-book-of-proof-3e-pdf --> [Book of Proof, 3rd Edition](books/book-of-proof-3e.pdf) | Richard Hammack | 2018 | `books/book-of-proof-3e.pdf` | — | 🟢 Open license |
| <!-- work: books-computational-complexity-arora-barak-pdf --> [Computational Complexity: A Modern Approach (draft)](books/computational-complexity-arora-barak.pdf) | Sanjeev Arora and Boaz Barak | 2007 | `books/computational-complexity-arora-barak.pdf` | — | 🔵 Official free |
| <!-- work: books-computer-networks-6e-pdf --> [Computer Networks: A Systems Approach, Version 6.1](books/computer-networks-6e.pdf) | Larry Peterson and Bruce Davie | 2019 | `books/computer-networks-6e.pdf` | — | 🟢 Open license |
| <!-- work: books-linear-algebra-done-right-4e-pdf --> [Linear Algebra Done Right, 4th Edition (open access)](books/linear-algebra-done-right-4e.pdf) | Sheldon Axler | 2024 | `books/linear-algebra-done-right-4e.pdf` | — | 🟢 Open license |
| <!-- work: books-little-book-of-semaphores-pdf --> [The Little Book of Semaphores, 2nd Edition (2016 build)](books/little-book-of-semaphores.pdf) | Allen B. Downey | 2016 | `books/little-book-of-semaphores.pdf` | — | 🟢 Open license |
| <!-- work: books-mackay-information-theory-pdf --> [Information Theory, Inference, and Learning Algorithms](books/mackay-information-theory.pdf) | David J. C. MacKay | 2003 | `books/mackay-information-theory.pdf` | — | 🔵 Official free |
| <!-- work: books-readings-db-systems-5e-pdf --> [Readings in Database Systems, 5th Edition](books/readings-db-systems-5e.pdf) | Peter Bailis, Joseph M. Hellerstein, and Michael Stonebraker (eds.) | 2015 | `books/readings-db-systems-5e.pdf` | — | 🟢 Open license |
| <!-- work: books-riscv-spec-unprivileged-pdf --> [The RISC-V Instruction Set Manual, Volume I: Unprivileged Architecture](books/riscv-spec-unprivileged.pdf) | RISC-V International (editors: Andrew Waterman, Krste Asanović, et al.) | 2026 | `books/riscv-spec-unprivileged.pdf` | — | 🟢 Open license |
| <!-- work: books-theory-of-computation-maheshwari-pdf --> [Theory of Computation](books/theory-of-computation-maheshwari.pdf) | Anil Maheshwari and Michiel Smid | 2024 | `books/theory-of-computation-maheshwari.pdf` | — | 🟢 Open license |

| <!-- work: art-of-hpc --> [The Art of HPC (Vols. 1–4, current builds)](books/art-of-hpc/) | Victor Eijkhout | 2023–2026 builds | `books/art-of-hpc/` | [source](https://github.com/VictorEijkhout/TheArtofHPC_pdfs) | 🟢 Open license |

## Research Papers

| Paper | Author(s) | Year | Local | Source | Access |
|---|---|---:|---|---|---|
| <!-- work: papers-alexnet-neurips12-pdf --> [ImageNet Classification with Deep Convolutional Neural Networks (AlexNet)](papers/alexnet-neurips12.pdf) | Krizhevsky, Sutskever, Hinton | Not recorded | `papers/alexnet-neurips12.pdf` | — | ⚪ Source terms |
| <!-- work: papers-alphazero-pdf --> [Mastering Chess and Shogi by Self-Play with a General Reinforcement Learning Algorithm](papers/alphazero.pdf) | David Silver, Thomas Hubert, Julian Schrittwieser, Ioannis Antonoglou, Matthew Lai, Arthur Guez, Marc Lanctot, Laurent Sifre, Dharshan Kumaran, Thore Graepel, Timothy Lillicrap, Karen Simonyan, Demis Hassabis | 2017 | `papers/alphazero.pdf` | — | 🔵 Official free |
| <!-- work: papers-bert-pdf --> [BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding](papers/bert.pdf) | Jacob Devlin, Ming-Wei Chang, Kenton Lee, Kristina Toutanova | 2018 | `papers/bert.pdf` | — | 🔵 Official free |
| <!-- work: papers-bigtable-osdi06-pdf --> [Bigtable: A Distributed Storage System for Structured Data](papers/bigtable-osdi06.pdf) | Chang et al. | Not recorded | `papers/bigtable-osdi06.pdf` | — | 🔵 Official free |
| <!-- work: papers-bitcoin-whitepaper-pdf --> [Bitcoin: A Peer-to-Peer Electronic Cash System](papers/bitcoin-whitepaper.pdf) | Satoshi Nakamoto | Not recorded | `papers/bitcoin-whitepaper.pdf` | — | ⚪ Source terms |
| <!-- work: papers-borg-eurosys15-pdf --> [Large-Scale Cluster Management at Google with Borg](papers/borg-eurosys15.pdf) | Burns, Grant, Oppenheimer, Brewer | Not recorded | `papers/borg-eurosys15.pdf` | — | ⚪ Source terms |
| <!-- work: papers-chord-sigcomm01-pdf --> [A Scalable Peer-to-peer Lookup Service for Internet Applications (Chord)](papers/chord-sigcomm01.pdf) | Stoica et al. | Not recorded | `papers/chord-sigcomm01.pdf` | — | 🔵 Official free |
| <!-- work: papers-ddpm-pdf --> [Denoising Diffusion Probabilistic Models](papers/ddpm.pdf) | Jonathan Ho, Ajay Jain, Pieter Abbeel | 2020 | `papers/ddpm.pdf` | — | 🔵 Official free |
| <!-- work: papers-deep-residual-learning-pdf --> [Deep Residual Learning for Image Recognition](papers/deep-residual-learning.pdf) | Kaiming He, Xiangyu Zhang, Shaoqing Ren, Jian Sun | 2015 | `papers/deep-residual-learning.pdf` | — | 🔵 Official free |
| <!-- work: papers-dijkstra-ewd267-pdf --> [Notes on Structured Programming (EWD267)](papers/dijkstra-ewd267.pdf) | Edsger W. Dijkstra | Not recorded | `papers/dijkstra-ewd267.pdf` | — | ⚪ Source terms |
| <!-- work: papers-dynamo-sosp07-pdf --> [Dynamo: Amazon's Highly Available Key-value Store](papers/dynamo-sosp07.pdf) | DeCandia et al. | Not recorded | `papers/dynamo-sosp07.pdf` | — | 🔵 Official free |
| <!-- work: papers-end-to-end-args-1984-pdf --> [End-to-End Arguments in System Design](papers/end-to-end-args-1984.pdf) | Saltzer, Reed, Clark | Not recorded | `papers/end-to-end-args-1984.pdf` | — | 🔵 Official free |
| <!-- work: papers-gan-pdf --> [Generative Adversarial Networks](papers/gan.pdf) | Ian J. Goodfellow, Jean Pouget-Abadie, Mehdi Mirza, Bing Xu, David Warde-Farley, Sherjil Ozair, Aaron Courville, Yoshua Bengio | 2014 | `papers/gan.pdf` | — | 🔵 Official free |
| <!-- work: papers-gfs-sosp2003-pdf --> [The Google File System](papers/gfs-sosp2003.pdf) | Ghemawat, Gobioff, Leung | Not recorded | `papers/gfs-sosp2003.pdf` | — | 🔵 Official free |
| <!-- work: papers-kafka-netdb11-pdf --> [Kafka: a Distributed Messaging System for Log Processing](papers/kafka-netdb11.pdf) | Kreps, Narkhede, Rao | Not recorded | `papers/kafka-netdb11.pdf` | — | ⚪ Source terms |
| <!-- work: papers-lamport-time-clocks-1978-pdf --> [Time, Clocks, and the Ordering of Events in a Distributed System](papers/lamport-time-clocks-1978.pdf) | Leslie Lamport | Not recorded | `papers/lamport-time-clocks-1978.pdf` | — | 🔵 Official free |
| <!-- work: papers-mapreduce-osdi04-pdf --> [MapReduce: Simplified Data Processing on Large Clusters](papers/mapreduce-osdi04.pdf) | Dean, Ghemawat | Not recorded | `papers/mapreduce-osdi04.pdf` | — | 🔵 Official free |
| <!-- work: papers-paxos-simple-pdf --> [Paxos Made Simple](papers/paxos-simple.pdf) | Leslie Lamport | Not recorded | `papers/paxos-simple.pdf` | — | 🔵 Official free |
| <!-- work: papers-raft-atc14-pdf --> [In Search of an Understandable Consensus Algorithm (Raft)](papers/raft-atc14.pdf) | Ongaro, Ousterhout | Not recorded | `papers/raft-atc14.pdf` | — | 🔵 Official free |
| <!-- work: papers-shannon-1948-pdf --> [A Mathematical Theory of Communication](papers/shannon-1948.pdf) | Claude E. Shannon | Not recorded | `papers/shannon-1948.pdf` | — | ⚪ Source terms |
| <!-- work: papers-spanner-osdi2012-pdf --> [Spanner: Google's Globally-Distributed Database](papers/spanner-osdi2012.pdf) | Corbett et al. | Not recorded | `papers/spanner-osdi2012.pdf` | — | 🔵 Official free |
| <!-- work: papers-spark-rdd-nsdi12-pdf --> [Resilient Distributed Datasets: A Fault-Tolerant Abstraction for In-Memory Cluster Computing](papers/spark-rdd-nsdi12.pdf) | Zaharia et al. | Not recorded | `papers/spark-rdd-nsdi12.pdf` | — | 🔵 Official free |
| <!-- work: papers-turing-1936-pdf --> [On Computable Numbers, with an Application to the Entscheidungsproblem](papers/turing-1936.pdf) | Alan M. Turing | Not recorded | `papers/turing-1936.pdf` | — | ⚪ Source terms |
| <!-- work: papers-vae-pdf --> [Auto-Encoding Variational Bayes](papers/vae.pdf) | Diederik P Kingma, Max Welling | 2013 | `papers/vae.pdf` | — | 🔵 Official free |
| <!-- work: papers-word2vec-pdf --> [Efficient Estimation of Word Representations in Vector Space](papers/word2vec.pdf) | Tomas Mikolov, Kai Chen, Greg Corrado, Jeffrey Dean | 2013 | `papers/word2vec.pdf` | — | 🔵 Official free |
| <!-- work: papers-zookeeper-atc10-pdf --> [ZooKeeper: Wait-free Coordination for Internet-scale Systems](papers/zookeeper-atc10.pdf) | Hunt et al. | Not recorded | `papers/zookeeper-atc10.pdf` | — | ⚪ Source terms |

## Collection file index

The two collection rows above contain more than one artifact. Every file is
linked here so the catalog remains the only navigation page you need.

### MIT 6.006 — 20 lecture PDFs

| Lectures 01–10 | Lectures 11–20 |
|---|---|
| [Lecture 01](papers/mit-6006/lec-01.pdf) | [Lecture 11](papers/mit-6006/lec-11.pdf) |
| [Lecture 02](papers/mit-6006/lec-02.pdf) | [Lecture 12](papers/mit-6006/lec-12.pdf) |
| [Lecture 03](papers/mit-6006/lec-03.pdf) | [Lecture 13](papers/mit-6006/lec-13.pdf) |
| [Lecture 04](papers/mit-6006/lec-04.pdf) | [Lecture 14](papers/mit-6006/lec-14.pdf) |
| [Lecture 05](papers/mit-6006/lec-05.pdf) | [Lecture 15](papers/mit-6006/lec-15.pdf) |
| [Lecture 06](papers/mit-6006/lec-06.pdf) | [Lecture 16](papers/mit-6006/lec-16.pdf) |
| [Lecture 07](papers/mit-6006/lec-07.pdf) | [Lecture 17](papers/mit-6006/lec-17.pdf) |
| [Lecture 08](papers/mit-6006/lec-08.pdf) | [Lecture 18](papers/mit-6006/lec-18.pdf) |
| [Lecture 09](papers/mit-6006/lec-09.pdf) | [Lecture 19](papers/mit-6006/lec-19.pdf) |
| [Lecture 10](papers/mit-6006/lec-10.pdf) | [Lecture 20](papers/mit-6006/lec-20.pdf) |

### Software Foundations — 7 readable volumes

| Volume | Local book |
|---|---|
| Logical Foundations | [Read EPUB](books/software-foundations/logical-foundations.epub) |
| Programming Language Foundations | [Read EPUB](books/software-foundations/programming-language-foundations.epub) |
| Verified Functional Algorithms | [Read EPUB](books/software-foundations/verified-functional-algorithms.epub) |
| QuickChick | [Read EPUB](books/software-foundations/quickchick.epub) |
| Verifiable C | [Read EPUB](books/software-foundations/verifiable-c.epub) |
| Separation Logic Foundations | [Read EPUB](books/software-foundations/separation-logic-foundations.epub) |
| Security Foundations | [Read EPUB](books/software-foundations/security-foundations.epub) |

## Collection notes

- **Multi-artifact works:** MIT 6.006 contributes 20 lecture PDFs; Software
  Foundations contributes seven readable EPUB volumes; The Art of HPC contributes
  five volumes. The curated tables contain 83 works and 112 artifacts. Thirteen
  additional held-arrival records below bring the maintained local reader to 96
  works and 125 readable artifacts when those files are present. The retained
  Nand2Tetris software ZIP is the 126th canonical record, but is not a readable
  work or artifact.
- **Deduplication:** the complete OSTEP PDF replaces 68 chapter-level copies;
  the complete Crafting Interpreters EPUB replaces its sample and source bundle. The
  retained shelf has no repeated SHA-256 digest.
- **Metadata:** every artifact has title, path, source/access notes, byte count,
  and SHA-256 under `metadata/`. Unknown legacy provenance stays unknown.
- **Canonical integrity:** run `python3 scripts/fetch.py verify`, then
  `python3 scripts/fetch.py audit`. Regenerate the canonical manifest only after
  an intentional shelf change with `python3 scripts/fetch.py manifest`.

<!-- work: book:nand2tetris-projects -->
### [Nand2Tetris — Official Software Suite (projects 1–12)](books/nand2tetris-projects.zip)

- Type: course software suite
- Authors: Noam Nisan and Shimon Schocken
- Local path: `books/nand2tetris-projects.zip`
- Source: [official page](https://www.nand2tetris.org/)
- License: GPL v2 or later (official projects software; supplied freely for use with the Nand2Tetris courses)

<!-- work: url:00295b82ff725c52a71351a0bb1ee1bdb1584e594a62395d3fb382aefd0f4d42 -->
### [Algorithms](books/algorithms-erickson.pdf)

- Type: book
- Authors: Jeff Erickson
- Local path: `books/algorithms-erickson.pdf`
- Source: [official page](https://jeffe.cs.illinois.edu/teaching/algorithms/book/Algorithms-JeffE.pdf)
- License: CC BY-NC-SA 4.0 (author's open textbook, verify in preface)

<!-- work: url:b3129f44c4a26b534176bb0f83d85e1ed26a6cdf93ebebacb20104eab2d6bc00 -->
### [Dive into Deep Learning](books/dive-into-deep-learning.pdf)

- Type: book
- Authors: Zhang, Lipton, Li, Smola
- Local path: `books/dive-into-deep-learning.pdf`
- Source: [official page](https://d2l.ai/d2l-en.pdf)
- License: CC BY-NC-SA 4.0 (verify in front matter)

<!-- work: url:5d633e4514799a123616c565beeaa498d9900f615969273b320a969fb0c336a0 -->
### [Foundations of Databases](books/foundations-of-databases.pdf)

- Type: book
- Authors: Abiteboul, Hull, Vianu
- Local path: `books/foundations-of-databases.pdf`
- Source: [official page](http://webdam.inria.fr/Alice/pdfs/all.pdf)
- License: Free web edition hosted by authors (webdam.inria.fr)

<!-- work: url:89bfbed17259573dcdc1c1f0e14347030aa42902baba7e0a395fcd7493594aac -->
### [Homotopy Type Theory](books/hott-online.pdf)

- Type: book
- Authors: Univalent Foundations Program
- Local path: `books/hott-online.pdf`
- Source: [official page](https://hott.github.io/book/hott-online-82-g578b85c.pdf)
- License: CC BY-SA (HoTT Book official build, verify in colophon)

<!-- work: url:fa522a14f9b1631232ff6b34bc092686803b71cc8154cbf31c7ac523a75108dc -->
### [generatingfunctionology](books/generatingfunctionology.pdf)

- Type: book
- Authors: Herbert S. Wilf
- Local path: `books/generatingfunctionology.pdf`
- Source: [official page](https://www2.math.upenn.edu/~wilf/gfologyLinked2.pdf)
- License: Freely distributed by author (A K Peters 2nd ed.)

<!-- work: url:41baea09d066e0167ca0943968d44f7f07790be700440427f78c034910e5765d -->
### [Dapper, a Large-Scale Distributed Systems Tracing Infrastructure](papers/dapper-google-tr.pdf)

- Type: paper
- Authors: Sigelman et al. (Google)
- Local path: `papers/dapper-google-tr.pdf`
- Source: [official page](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/36356.pdf)
- License: Google Technical Report via Google Research archive

<!-- work: url:cd514fbdf07b1f96f9b32304c4bff62e9c1f048626439c9dd2c881bc09549801 -->
### [Zanzibar: Google's Consistent, Global Authorization System](papers/zanzibar-atc20.pdf)

- Type: paper
- Authors: Pang et al. (USENIX ATC 2020)
- Local path: `papers/zanzibar-atc20.pdf`
- Source: [official page](https://storage.googleapis.com/gweb-research2023-media/pubtools/5068.pdf)
- License: Publisher PDF via Google Research archive

<!-- work: url:389dfabdfa94bd21bb3ccebc5074a84c4faa0661c885ca3b3cbe70186f47a747 -->
### [Hints for Computer System Design](papers/lampson-hints-sosp83.pdf)

- Type: paper
- Authors: Butler W. Lampson (SOSP 1983)
- Local path: `papers/lampson-hints-sosp83.pdf`
- Source: [official page](https://www.microsoft.com/en-us/research/wp-content/uploads/1983/10/Hints-for-Computer-System-Design-SOSP-version.pdf)
- License: Author copy hosted by Microsoft Research

<!-- work: url:0c550af6f81215e1b4909f4e8e99e44c7bb18967835c0dbd559191a65d01a275 -->
### [Smashing the Stack for Fun and Profit](papers/smashing-stack-phrack49.pdf)

- Type: paper
- Authors: Aleph One (Phrack 49-14)
- Local path: `papers/smashing-stack-phrack49.pdf`
- Source: [official page](https://inst.eecs.berkeley.edu/~cs161/archive/fa08/papers/stack_smashing.pdf)
- License: UC Berkeley CS161 course mirror of Phrack article

<!-- work: url:40807dab08eb08477d6bd1ed22b91b4dcd6633550a4a62682ecbbd00c00d8b08 -->
### [The Byzantine Generals Problem](papers/byzantine-generals-toplas82.pdf)

- Type: paper
- Authors: Lamport, Shostak, Pease (ACM TOPLAS 1982)
- Local path: `papers/byzantine-generals-toplas82.pdf`
- Source: [official page](https://lamport.azurewebsites.net/pubs/byz.pdf)
- License: Author-hosted copy (Lamport publications site)

<!-- work: url:5de3d24deb279f5bc7669a90742876d2807200eabc9195bb6e8714b400b0532a -->
### [Handbook of Applied Cryptography, Chapter 1](papers/chap1.pdf)

- Type: paper
- Authors: Alfred J. Menezes, Paul C. van Oorschot, Scott A. Vanstone
- Local path: `papers/chap1.pdf`
- Source: [official page](https://cacr.uwaterloo.ca/hac/about/chap1.pdf)
- License: Freely available from authors' official site

<!-- work: url:8ab9d339a2c2781382e6aa4c3c472a94edfcc05d10e3eedf63cbaac9530e9932 -->
### [Reflections on Trusting Trust](papers/reflections-on-trusting-trust.pdf)

- Type: paper
- Authors: Ken Thompson
- Local path: `papers/reflections-on-trusting-trust.pdf`
- Source: [official page](https://www.cs.cmu.edu/~rdriley/487/papers/Thompson_1984_ReflectionsonTrustingTrust.pdf)
- License: Freely available (author-hosted copies; CACM 1984)

<!-- work: url:d9d788538f999a0320da8f115edc3d4cf8f39aacbd6d8fe0ed9fedf82b395647 -->
### [Scaling Memcache at Facebook](papers/scaling-memcache-at-facebook.pdf)

- Type: paper
- Authors: Nishtala et al.
- Local path: `papers/scaling-memcache-at-facebook.pdf`
- Source: [official page](https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf)
- License: Freely available from USENIX (NSDI '13)
