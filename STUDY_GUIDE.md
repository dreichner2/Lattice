# Computer Science Study Guide

This guide turns the shelf into a curriculum. The goal is not to read every
page in order; it is to combine one primary text, targeted references, and a
project at each stage until the ideas are usable without the book open.

## Pick your entry route

### Java-first route

Start here if Java is the language you want to build with:

1. [Think Java 2e](books/think-java-2e.pdf) — work every exercise and write small programs.
2. Build a command-line application with files, tests, errors, and collections.
3. Use the [MIT 6.006 lecture notes](papers/mit-6006/) while implementing each data structure in Java.
4. Read the [Java Language Specification](books/jls-26.pdf) only when you need exact language semantics.
5. Read the [Java Virtual Machine Specification](books/jvms-26.pdf) after you can write normal Java comfortably; pair
   it with a bytecode-disassembly or tiny-JVM project.
6. Continue into OSTEP, compilers, databases, and distributed systems.

The JLS and JVMS are specifications, not beginner textbooks. Keeping them as
references prevents the common mistake of trying to learn Java by reading a
language standard front to back.

### General route

1. [Think Python 2e](books/think-python-2e.pdf)
2. [Introduction to Computer Science](books/openstax-intro-cs.pdf)
3. [Structure and Interpretation of Computer Programs](books/sicp.pdf)
4. [MIT 6.006 lecture notes](papers/mit-6006/)
5. [Operating Systems: Three Easy Pieces](books/ostep.pdf)

Use this route when the language matters less than building broad foundations
quickly.

### Experienced-programmer route

Start with the first stage whose exit test you cannot pass. Most working
programmers get more value from algorithms, systems, compilers, and math than
from rereading another introductory syntax book.

## The core sequence

| Stage | Primary material | Build before moving on |
|---:|---|---|
| 1 | [Think Java 2e](books/think-java-2e.pdf) **or** [Think Python 2e](books/think-python-2e.pdf) | A tested CLI application that persists data |
| 2 | [SICP](books/sicp.pdf) | An interpreter for a small expression language |
| 3 | [Concrete Mathematics](books/concrete-math-2e.pdf) + [MIT 6.006](papers/mit-6006/) | A data-structure/algorithm library with benchmarks |
| 4 | [CLRS](books/clrs-4e.pdf) | Correct implementations plus written complexity arguments |
| 5 | [OSTEP](books/ostep.pdf) | A shell, allocator, thread pool, and small file-system exercise |
| 6 | [Crafting Interpreters](books/crafting-interpreters.epub) + [PLAI](books/plai-3e.pdf) | A language with parser, evaluator, closures, and errors |
| 7 | [Software Engineering at Google](books/software-engineering-google.epub) | A maintained team-style project with CI and design docs |
| 8 | Statistics + calculus + linear algebra | A reproducible analysis notebook or numerical library |
| 9 | [ISL with Python](books/isl-python.pdf) → deep learning/PML | An end-to-end model with honest evaluation |
| 10 | [Security Engineering](books/security-engineering-3e.pdf) + [ACM Code](papers/acm-code-of-ethics.pdf) | A threat model and security review of your own project |

## Stage 1 — Programming fluency

**Choose one primary language.** Java is a strong choice when you want explicit
types, mature tooling, backend development, Android lineage, and exposure to a
widely deployed VM.

Primary:

- [Think Java 2e](books/think-java-2e.pdf)
- or [Think Python 2e](books/think-python-2e.pdf)

References and second perspectives:

- [Introduction to Computer Science](books/openstax-intro-cs.pdf)
- [The C Programming Language](books/c-programming-language-1e.pdf) once pointers and memory are relevant
- [Programming Pearls](books/programming-pearls-2e.pdf) for compact problem-solving essays

Exit test:

- You can decompose a program into modules/classes, write tests, handle malformed
  input, use a debugger, read and write files, and explain the main data
  structures you chose.

Suggested build: a local study tracker that imports the catalog metadata,
supports search/tags/progress, and persists to SQLite or JSON.

## Stage 2 — Abstraction and program structure

Primary:

- [SICP](books/sicp.pdf)
- [SICP JavaScript](books/sicp-js.pdf) if JavaScript notation is more comfortable

Companion:

- [Programming Languages: Application and Interpretation](books/plai-3e.pdf)

Focus on recursion, higher-order procedures, state, environments, interpreters,
and the difference between a language's surface syntax and its evaluation
model.

Exit test: implement a small Lisp-like interpreter with lexical scope,
closures, conditionals, lists, useful errors, and a REPL.

## Stage 3 — Discrete math, data structures, and algorithms

Primary sequence:

1. [Concrete Mathematics](books/concrete-math-2e.pdf) for proof habits, sums, recurrence relations,
   number theory, and combinatorics.
2. [MIT 6.006 Lecture 1](papers/mit-6006/lec-01.pdf) through [Lecture 20](papers/mit-6006/lec-20.pdf) for a guided algorithms
   course.
3. [Introduction to Algorithms](books/clrs-4e.pdf) as the deeper reference and exercise bank.

Implement in Java if following the Java route:

- dynamic array, linked list, stack, queue, hash table;
- binary-search tree, AVL or red-black tree, heap, trie;
- union-find and graph representations;
- BFS, DFS, topological sort, Dijkstra, Bellman-Ford, and an MST algorithm;
- merge sort, quicksort, counting/radix sort;
- a dynamic-programming problem with reconstruction, not just the score.

Exit test: for each implementation, state the invariant, prove or justify
correctness, give time/space bounds, and demonstrate those bounds with a
benchmark that is not dominated by setup time.

## Stage 4 — Computer systems

Primary:

- [Operating Systems: Three Easy Pieces](books/ostep.pdf)
- [Distributed Systems](books/distributed-systems-4e.pdf) after the single-machine foundations

Supporting material:

- [The Art of Unix Programming](books/art-of-unix-programming.pdf)
- [The C Programming Language](books/c-programming-language-1e.pdf)
- [Security Engineering](books/security-engineering-3e.pdf)
- [RFC 791](papers/rfc-791.txt)

Build:

- a Unix-style shell with pipes, redirection, jobs, and exit statuses;
- a bounded thread pool and producer/consumer queue;
- a simple allocator or memory arena;
- a user-space cache with an explicit replacement policy;
- a small network service whose wire format you can document byte for byte.

Exit test: explain processes versus threads, virtual memory, page tables and
TLBs, scheduling, locking, deadlock, file systems, crash consistency, and the
path a network packet takes through your program and OS.

## Stage 5 — Programming languages, compilers, and verification

Recommended order:

1. [Crafting Interpreters](books/crafting-interpreters.epub)
2. [Programming Languages: Application and Interpretation](books/plai-3e.pdf)
3. [Compilers: Principles, Techniques, and Tools](books/dragon-book-2e.pdf)
4. [Software Foundations](books/software-foundations/)
5. [Specifying Systems](books/specifying-systems.pdf)

Java-specific references:

- [Java Language Specification](books/jls-26.pdf)
- [Java Virtual Machine Specification](books/jvms-26.pdf)

Build one substantial language tool: a tree-walk interpreter, bytecode VM,
compiler to WebAssembly/native code, static type checker, or program analyzer.
Then specify one non-trivial property and prove/test it with Software
Foundations, QuickChick, or TLA+.

Exit test: explain lexing, parsing, ASTs, name resolution, type checking,
closures, garbage collection, bytecode, optimization, and the gap between
testing a property and proving it.

## Stage 6 — Software engineering and design

Use these as competing perspectives, not scripture:

- [Software Engineering at Google](books/software-engineering-google.epub)
- [Design Patterns](books/design-patterns.pdf)
- [Refactoring](books/refactoring-1e.pdf)
- [The Pragmatic Programmer](books/pragmatic-programmer-1e.pdf)
- [Clean Code](books/clean-code.pdf)
- [The Mythical Man-Month](books/mythical-man-month.epub)

Build and maintain a project long enough to encounter migrations, dependency
upgrades, failing tests, operational logs, performance regressions, and a
design you need to change. Add CI, release notes, an architecture decision
record, and a documented rollback path.

Exit test: you can distinguish a local code-style preference from a design
property that affects correctness, operability, security, or team throughput.

## Stage 7 — Mathematics for advanced CS and ML

Suggested order:

1. [Introduction to Probability](books/introduction-probability-2e.pdf)
2. [OpenIntro Statistics](books/openintro-statistics-4e.pdf)
3. [Calculus Volume 1](books/openstax-calculus-1.pdf)
4. [Calculus Volume 2](books/openstax-calculus-2.pdf)
5. [Calculus Volume 3](books/openstax-calculus-3.pdf) as needed for multivariable/vector topics
6. [Mathematics for Machine Learning](books/math-for-ml.pdf)
7. [Convex Optimization](books/convex-optimization.pdf)

Do exercises with pencil and code. Numerically verify derivatives, gradients,
matrix identities, probability simulations, estimators, and optimization
algorithms; then explain where floating-point behavior breaks the ideal math.

Exit test: derive and implement linear/logistic regression, gradient descent,
regularization, basic estimators, confidence intervals, and cross-validation
without treating a library call as the explanation.

## Stage 8 — Artificial intelligence and machine learning

Recommended branches:

### Broad AI

- [Artificial Intelligence: A Modern Approach](books/aima-4e.pdf)
- search, planning, uncertainty, decision making, and multi-agent systems

### Statistical machine learning

- [An Introduction to Statistical Learning with Applications in Python](books/isl-python.pdf)
- [Probabilistic Machine Learning: An Introduction](books/pml-intro.pdf)
- [Reinforcement Learning](books/reinforcement-learning-2e.pdf)

### Deep learning and language

- [Understanding Deep Learning](books/understanding-deep-learning.pdf)
- [Speech and Language Processing](books/slp-3e-draft.pdf)
- [Attention Is All You Need](papers/attention-is-all-you-need.pdf)

### Responsible ML

- [Fairness and Machine Learning](books/fairness-ml.pdf)
- [ACM Code of Ethics](papers/acm-code-of-ethics.pdf)

### Computer vision

- [Computer Vision: Algorithms and Applications](books/computer-vision-2e.pdf)

Build at least one project where the hard part is evaluation rather than model
training. Preserve a clean train/validation/test boundary, compare against a
simple baseline, inspect failures, state uncertainty, and document foreseeable
misuse. [Double-DQN scheduling](papers/double-dqn-scheduling.pdf) is a useful case study linking RL
back to systems, but it is not a substitute for the systems fundamentals.

## Stage 9 — Graphics and vision (optional specialization)

- [Physically Based Rendering](books/pbrt-4e.epub)
- [Computer Vision: Algorithms and Applications](books/computer-vision-2e.pdf)

Implement a small path tracer before leaning on a large engine. The useful
milestones are ray/shape intersections, BVH acceleration, materials, direct
lighting, Monte Carlo integration, importance sampling, and image-quality
tests.

## Video lectures (free, in-app)

Choose **Video lectures** in the app sidebar to browse **58 complete course
tracks and 1,452 unique lectures** across 12 subjects. Search reaches individual
lecture titles, not just course names. Use the **Source** filter to narrow the
hall to MIT, Harvard, Carnegie Mellon, or an individual instructor. Select a
course to open its searchable queue in the in-app player; completion marks and
the last position in each course stay locally on this Mac.

Good curriculum pairings include:

| Course track | Fits stage | Pair with |
| --- | --- | --- |
| MIT OCW 6.006 — Introduction to Algorithms | 3 | [6.006 notes](papers/mit-6006/) and CLRS |
| CMU 15-445 — Database Systems | 4 | the database projects and papers shelf |
| MIT 6.S081 — Operating System Engineering | 4 | [OSTEP](books/ostep.pdf) |
| MIT 6.824 — Distributed Systems | 4 | [Distributed Systems](books/distributed-systems-4e.pdf) |
| MIT 6.001 — SICP | 5 | [SICP](books/sicp.pdf) |
| Harvard CS50's Introduction to Cybersecurity | 7 | systems and security papers |
| Karpathy — Neural Networks: Zero to Hero | 8 | the ML and foundational-papers shelves |

The full collection also includes programming, mathematics, software practice,
computer engineering, programming languages, AI/ML, graphics, computer vision,
robotics, and computing ethics. Streams remain on their official publisher;
the app stores only a link catalog and provides both exact-YouTube and official
course-page fallbacks. See the [source and licensing record](notes/provenance/free-video-lectures-2026-08-21.md).

## Known shelf gaps

The catalog is broad, but it is not literally all of computer science. These
areas still need a dedicated primary text or course before the shelf can claim
balanced undergraduate-plus depth:

- automata and computability theory (complexity is now covered by the shelved
  Arora–Barak draft; Sipser remains purchase-only);
- human-computer interaction;
- testing, programming-language security, and modern cryptography as dedicated
  subjects;
- a free primary database text (the CMU 15-445 video track above carries the
  lecture material meanwhile).

Treat this as an honest boundary, not a defect to hide. The
[catalog](CATALOG.md) lists what is physically present; a recommendation is not
counted as owned until its artifact and metadata both pass verification.

## A practical weekly rhythm

- **Three sessions:** read actively and solve exercises.
- **Two sessions:** implement the current stage project.
- **One session:** write a short explanation, proof, benchmark, or postmortem.
- **One review:** revisit mistakes and choose the next concrete milestone.

Move on when you can pass the stage's exit test, not when you reach the final
page. Revisit the books as references while building larger systems.
