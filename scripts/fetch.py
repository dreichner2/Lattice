#!/usr/bin/env python3
"""Build and audit a local Lattice collection from authorized sources.

The standard-library-only CLI searches arXiv, downloads official RFC text,
fetches curated books and course sets, imports an exact authorized URL, and
verifies the local shelf against its tracked metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
ARXIV_API = "https://export.arxiv.org/api/query"
RFC_TEXT_URL = "https://www.rfc-editor.org/rfc/rfc{number}.txt"
USER_AGENT = "cs-library-fetch/2.0 (personal open-access study library)"
ATOM = {"atom": "http://www.w3.org/2005/Atom"}
READABLE_PAYLOAD_SUFFIXES = frozenset({".pdf", ".epub", ".txt"})
SYNCED_SIDECAR_SUFFIX = ".library.json"

OPEN_BOOKS: dict[str, dict[str, Any]] = {
    "intro-cs": {
        "title": "Introduction to Computer Science",
        "authors": "OpenStax contributors",
        "year": "2024",
        "license": (
            "CC BY-NC-SA 4.0; OpenStax additionally prohibits LLM training or "
            "ingestion without permission"
        ),
        "source": "OpenStax",
        "page_url": "https://openstax.org/details/books/introduction-computer-science",
        "download_url": (
            "https://assets.openstax.org/oscms-prodcms/media/documents/"
            "Introduction_To_Computer_Science_-_WEB.pdf"
        ),
        "filename": "openstax-intro-cs.pdf",
    },
    "sicp": {
        "title": "Structure and Interpretation of Computer Programs",
        "authors": "Harold Abelson and Gerald Jay Sussman",
        "year": "1996",
        "license": "Free to use (MIT 6.001)",
        "source": "MIT course mirror",
        "page_url": "https://web.mit.edu/6.001/6.037/sicp.pdf",
        "download_url": "https://web.mit.edu/6.001/6.037/sicp.pdf",
    },
    "think-python": {
        "title": "Think Python 2e",
        "authors": "Allen B. Downey",
        "year": "2015",
        "license": "CC BY-NC-SA 4.0 (Green Tea Press)",
        "source": "Green Tea Press",
        "page_url": "https://greenteapress.com/thinkpython2/thinkpython2.pdf",
        "download_url": "https://greenteapress.com/thinkpython2/thinkpython2.pdf",
        "filename": "think-python-2e.pdf",
    },
    "think-java": {
        "title": "Think Java, 2nd Edition",
        "authors": "Allen B. Downey and Chris Mayfield",
        "year": "2020",
        "license": "CC BY-NC-SA 4.0",
        "source": "Green Tea Press",
        "page_url": "https://greenteapress.com/wp/think-java-2e/",
        "download_url": "https://greenteapress.com/thinkjava7/thinkjava2.pdf",
        "filename": "think-java-2e.pdf",
    },
    "jls": {
        "title": "The Java Language Specification, Java SE 26 Edition",
        "authors": (
            "James Gosling, Bill Joy, Guy Steele, Gilad Bracha, Alex Buckley, "
            "Daniel Smith, and Gavin Bierman"
        ),
        "year": "2026",
        "license": "Oracle Limited License Grant in Appendix A; all rights reserved",
        "source": "Oracle Java SE specifications",
        "catalog_type": "language specification",
        "page_url": "https://docs.oracle.com/javase/specs/jls/se26/html/",
        "download_url": "https://docs.oracle.com/javase/specs/jls/se26/jls26.pdf",
        "filename": "jls-26.pdf",
    },
    "jvms": {
        "title": "The Java Virtual Machine Specification, Java SE 26 Edition",
        "authors": (
            "Tim Lindholm, Frank Yellin, Gilad Bracha, Alex Buckley, and Daniel Smith"
        ),
        "year": "2026",
        "license": "Oracle Limited License Grant in Appendix A; all rights reserved",
        "source": "Oracle Java SE specifications",
        "catalog_type": "virtual-machine specification",
        "page_url": "https://docs.oracle.com/javase/specs/jvms/se26/html/",
        "download_url": "https://docs.oracle.com/javase/specs/jvms/se26/jvms26.pdf",
        "filename": "jvms-26.pdf",
    },
    "openintro-stats": {
        "title": "OpenIntro Statistics, 4th Edition",
        "authors": (
            "David M. Diez, Mine Cetinkaya-Rundel, and Christopher D. Barr"
        ),
        "year": "2019",
        "license": "CC BY-SA 3.0 (book content; branding exclusions apply)",
        "source": "OpenIntro",
        "page_url": "https://www.openintro.org/book/os/",
        "download_url": "https://www.openintro.org/go/?id=os4_tablet",
    },
    "calculus-1": {
        "title": "Calculus Volume 1",
        "authors": "Gilbert Strang and Edwin Herman",
        "year": "2016",
        "license": (
            "CC BY-NC-SA 4.0; OpenStax additionally prohibits LLM training or "
            "ingestion without permission"
        ),
        "source": "OpenStax",
        "page_url": "https://openstax.org/details/books/calculus-volume-1",
        "download_url": (
            "https://assets.openstax.org/oscms-prodcms/media/documents/"
            "CalculusVolume1-OP.pdf"
        ),
        "filename": "openstax-calculus-1.pdf",
    },
    "calculus-2": {
        "title": "Calculus Volume 2",
        "authors": "Gilbert Strang and Edwin Herman",
        "year": "2016",
        "license": (
            "CC BY-NC-SA 4.0; OpenStax additionally prohibits LLM training or "
            "ingestion without permission"
        ),
        "source": "OpenStax",
        "page_url": "https://openstax.org/details/books/calculus-volume-2",
        "download_url": (
            "https://assets.openstax.org/oscms-prodcms/media/documents/"
            "calculus-volume-2_-_WEB.pdf"
        ),
        "filename": "openstax-calculus-2.pdf",
    },
    "calculus-3": {
        "title": "Calculus Volume 3",
        "authors": "Gilbert Strang and Edwin Herman",
        "year": "2016",
        "license": (
            "CC BY-NC-SA 4.0; OpenStax additionally prohibits LLM training or "
            "ingestion without permission"
        ),
        "source": "OpenStax",
        "page_url": "https://openstax.org/details/books/calculus-volume-3",
        "download_url": (
            "https://assets.openstax.org/oscms-prodcms/media/documents/"
            "CalculusVolume3-OP.pdf"
        ),
        "filename": "openstax-calculus-3.pdf",
    },
    "math-for-ml": {
        "title": "Mathematics for Machine Learning",
        "authors": "Marc Peter Deisenroth, A. Aldo Faisal, and Cheng Soon Ong",
        "year": "2020",
        "license": "Copyright; publisher-authorized free PDF (no open reuse license stated)",
        "source": "Authors' official companion site / Cambridge University Press",
        "page_url": "https://mml-book.github.io/",
        "download_url": "https://mml-book.github.io/book/mml-book.pdf",
        "filename": "math-for-ml.pdf",
    },
    "convex-optimization": {
        "title": "Convex Optimization",
        "authors": "Stephen Boyd and Lieven Vandenberghe",
        "year": "2004",
        "license": "Copyright Cambridge University Press; authorized free web copy",
        "source": "Authors' Stanford book page / Cambridge University Press",
        "page_url": "https://web.stanford.edu/~boyd/cvxbook/",
        "download_url": "https://web.stanford.edu/~boyd/cvxbook/bv_cvxbook.pdf",
    },
    "crafting-interpreters": {
        "title": "Crafting Interpreters — Complete Web Book and Code Source",
        "authors": "Robert Nystrom",
        "year": "2021",
        "license": "Book/site CC BY-NC-ND 4.0; interpreter source code MIT",
        "source": "Author's official GitHub repository, commit 4a840f70",
        "catalog_type": "complete web-book source archive",
        "page_url": "https://craftinginterpreters.com/",
        "download_url": (
            "https://codeload.github.com/munificent/craftinginterpreters/zip/"
            "4a840f70f69c6ddd17cfef4f6964f8e1bcd8c3d4"
        ),
        "filename": "crafting-interpreters.zip",
        "expected": "zip",
        "included_path": (
            "craftinginterpreters-4a840f70f69c6ddd17cfef4f6964f8e1bcd8c3d4/book/"
        ),
    },
    "plai": {
        "title": "Programming Languages: Application and Interpretation, 3rd Edition",
        "authors": "Shriram Krishnamurthi",
        "year": "2025",
        "version": "3.2.5",
        "license": "CC BY-NC-SA 4.0",
        "source": "Author's official PLAI site",
        "page_url": "https://www.plai.org/",
        "download_url": "https://www.plai.org/3/5/plai-v325.pdf",
    },
    "specifying-systems": {
        "title": "Specifying Systems",
        "authors": "Leslie Lamport",
        "year": "2002",
        "license": "Copyright Pearson; download and one printed copy for personal use only",
        "source": "Author's official TLA+ book page / Pearson",
        "page_url": "https://lamport.azurewebsites.net/tla/book.html",
        "download_url": "https://lamport.azurewebsites.net/tla/book-21-07-04.pdf",
    },
    "security-engineering": {
        "title": "Security Engineering, 3rd Edition",
        "authors": "Ross Anderson",
        "year": "2020",
        "license": "Copyright; author/publisher-authorized free online edition",
        "source": "Author's University of Cambridge archive",
        "page_url": "https://www.cl.cam.ac.uk/archive/rja14/book.html",
        "download_url": "https://www.cl.cam.ac.uk/archive/rja14/Papers/SEv3.pdf",
    },
    "software-engineering-google": {
        "title": "Software Engineering at Google — Complete Official HTML Source",
        "authors": "Titus Winters, Tom Manshreck, and Hyrum Wright (curators)",
        "year": "2020",
        "license": (
            "Book subdirectory CC BY-NC-ND 4.0; other repository content may differ"
        ),
        "source": "Official Abseil site source, commit e9e24835",
        "catalog_type": "complete web-book source archive",
        "page_url": "https://abseil.io/resources/swe-book",
        "download_url": (
            "https://codeload.github.com/abseil/abseil.github.io/zip/"
            "e9e24835cb889fe25251cb9ec6d51b79233e358d"
        ),
        "filename": "software-engineering-google.zip",
        "expected": "zip",
        "included_path": (
            "abseil.github.io-e9e24835cb889fe25251cb9ec6d51b79233e358d/"
            "resources/swe-book/"
        ),
    },
    "pml": {
        "title": "Probabilistic Machine Learning: An Introduction",
        "authors": "Kevin P. Murphy",
        "year": "2025",
        "version": "2025-04-18 draft",
        "license": "CC BY-NC-ND 4.0",
        "source": "Author's official book site and GitHub release",
        "page_url": "https://probml.github.io/pml-book/book1.html",
        "download_url": (
            "https://github.com/probml/pml-book/releases/latest/download/book1.pdf"
        ),
        "filename": "pml-intro.pdf",
    },
    "understanding-deep-learning": {
        "title": "Understanding Deep Learning",
        "authors": "Simon J. D. Prince",
        "year": "2026",
        "version": "5.0.3 (2026-02-09 correction)",
        "license": "MIT Press open-access edition; see the PDF for exact reuse terms",
        "source": "Author's official GitHub release / MIT Press open-access edition",
        "page_url": (
            "https://mitpress.mit.edu/9780262377102/understanding-deep-learning/"
        ),
        "download_url": (
            "https://github.com/udlbook/udlbook/releases/download/v5.0.3/"
            "UnderstandingDeepLearning_02_09_26_C.pdf"
        ),
    },
    "isl-python": {
        "title": "An Introduction to Statistical Learning with Applications in Python",
        "authors": (
            "Gareth James, Daniela Witten, Trevor Hastie, Robert Tibshirani, "
            "and Jonathan Taylor"
        ),
        "year": "2023",
        "license": "Copyright Springer; official free PDF for personal study",
        "source": "Authors' official Statistical Learning site",
        "page_url": "https://www.statlearning.com/",
        "download_url": (
            "https://drive.google.com/uc?export=download&"
            "id=1ajFkHO6zjrdGNqhqW1jKBZdiNGh_8YQ1"
        ),
        "filename": "isl-python.pdf",
    },
    "pbrt": {
        "title": "Physically Based Rendering, 4th Edition — Official Website Source",
        "authors": "Matt Pharr, Wenzel Jakob, and Greg Humphreys",
        "year": "2023",
        "license": "Book text CC BY-NC-ND 4.0; software/source components vary",
        "source": "Authors' official website repository, commit b56160a8",
        "catalog_type": "complete web-book source archive",
        "page_url": "https://www.pbr-book.org/4ed/",
        "download_url": (
            "https://codeload.github.com/mmp/pbr-book-website/zip/"
            "b56160a8e4ac0cc8bdd051e8181aa6692b127151"
        ),
        "filename": "pbrt-4e.zip",
        "expected": "zip",
        "included_path": (
            "pbr-book-website-b56160a8e4ac0cc8bdd051e8181aa6692b127151/4ed/"
        ),
    },
    "fairness-ml": {
        "title": "Fairness and Machine Learning: Limitations and Opportunities",
        "authors": "Solon Barocas, Moritz Hardt, and Arvind Narayanan",
        "year": "2023",
        "license": "CC BY-NC-ND 4.0",
        "source": "Authors' official book site / MIT Press",
        "page_url": "https://www.fairmlbook.org/",
        "download_url": "https://www.fairmlbook.org/pdf/fairmlbook.pdf",
        "filename": "fairness-ml.pdf",
    },
    "acm-code": {
        "title": "ACM Code of Ethics and Professional Conduct",
        "authors": "Association for Computing Machinery",
        "year": "2018",
        "license": "Copyright ACM; official freely accessible professional standard",
        "source": "Association for Computing Machinery",
        "catalog_type": "professional standard",
        "dest": "papers",
        "page_url": "https://www.acm.org/code-of-ethics",
        "download_url": (
            "https://www.acm.org/binaries/content/assets/about/"
            "acm-code-of-ethics-and-professional-conduct.pdf"
        ),
    },
    "redbook": {
        "title": "Readings in Database Systems, 5th Edition",
        "authors": "Peter Bailis, Joseph M. Hellerstein, and Michael Stonebraker (eds.)",
        "year": "2015",
        "license": "CC BY-NC-SA 4.0",
        "source": "Authors' official book site (redbook.io)",
        "page_url": "http://www.redbook.io/",
        "download_url": "http://www.redbook.io/pdf/redbook-5th-edition.pdf",
        "filename": "readings-db-systems-5e.pdf",
    },
    "networks-book": {
        "title": "Computer Networks: A Systems Approach, Version 6.1",
        "authors": "Larry Peterson and Bruce Davie",
        "year": "2019",
        "license": "CC BY 4.0",
        "source": "Authors' official GitHub repository (systemsapproach/book), release v6.1",
        "page_url": "https://github.com/systemsapproach/book",
        "download_url": (
            "https://github.com/systemsapproach/book/releases/download/"
            "v6.1/book.pdf"
        ),
        "filename": "computer-networks-6e.pdf",
    },
    "semaphores": {
        "title": "The Little Book of Semaphores, 2nd Edition (2016 build)",
        "authors": "Allen B. Downey",
        "year": "2016",
        "license": "CC BY-NC-SA 4.0",
        "source": "Green Tea Press (author's official site)",
        "page_url": "https://greenteapress.com/semaphores/",
        "download_url": (
            "http://greenteapress.com/semaphores/LittleBookOfSemaphores.pdf"
        ),
        "filename": "little-book-of-semaphores.pdf",
    },
    "theory-of-computation": {
        "title": "Theory of Computation",
        "authors": "Anil Maheshwari and Michiel Smid",
        "year": "2024",
        "license": "CC BY-SA 4.0",
        "source": "Authors' official page at Carleton University",
        "page_url": "https://cglab.ca/~michiel/TheoryOfComputation/",
        "download_url": (
            "https://cglab.ca/~michiel/TheoryOfComputation/"
            "TheoryOfComputation.pdf"
        ),
        "filename": "theory-of-computation-maheshwari.pdf",
    },
    "arora-barak": {
        "title": "Computational Complexity: A Modern Approach (draft)",
        "authors": "Sanjeev Arora and Boaz Barak",
        "year": "2007",
        "license": "Author-provided free draft from the book's official site",
        "source": "Princeton University book site (authors' official)",
        "page_url": "https://theory.cs.princeton.edu/complexity/",
        "download_url": "https://theory.cs.princeton.edu/complexity/book.pdf",
        "filename": "computational-complexity-arora-barak.pdf",
    },
    "mackay-itila": {
        "title": "Information Theory, Inference, and Learning Algorithms",
        "authors": "David J. C. MacKay",
        "year": "2003",
        "license": "Author-provided free PDF from the book's official site (Cambridge University Press print)",
        "source": "Author's official book site (inference.org.uk)",
        "page_url": "https://www.inference.org.uk/mackay/itila/",
        "download_url": "https://www.inference.org.uk/itprnn/book.pdf",
        "filename": "mackay-information-theory.pdf",
    },
    "ladr-4e": {
        "title": "Linear Algebra Done Right, 4th Edition (open access)",
        "authors": "Sheldon Axler",
        "year": "2024",
        "license": "CC BY-NC 4.0 (Springer open-access edition)",
        "source": "Author's official book site (linear.axler.net)",
        "page_url": "https://linear.axler.net/",
        "download_url": "https://linear.axler.net/LADR4e.pdf",
        "filename": "linear-algebra-done-right-4e.pdf",
    },
    "book-of-proof": {
        "title": "Book of Proof, 3rd Edition",
        "authors": "Richard Hammack",
        "year": "2018",
        "license": "CC BY-NC-ND 4.0",
        "source": "Author's official site (GitHub Pages mirror of vcu.edu original)",
        "page_url": "https://richardhammack.github.io/BookOfProof/",
        "download_url": (
            "https://richardhammack.github.io/BookOfProof/Main.pdf"
        ),
        "filename": "book-of-proof-3e.pdf",
    },
    "nand2tetris-projects": {
        "title": "Nand2Tetris — Official Software Suite (projects 1–12)",
        "authors": "Noam Nisan and Shimon Schocken",
        "year": "2017",
        "license": (
            "GPL v2 or later (official projects software; supplied freely "
            "for use with the Nand2Tetris courses)"
        ),
        "source": "Official nand2tetris.org download (Google Drive, interstitial-free direct link)",
        "catalog_type": "course software suite",
        "page_url": "https://www.nand2tetris.org/",
        "download_url": (
            "https://drive.google.com/uc?export=download&"
            "id=1stcWUSeAixCRHWOjc9sgBhq5voSLvun8"
        ),
        "filename": "nand2tetris-projects.zip",
        "expected": "zip",
    },
    "riscv-spec": {
        "title": "The RISC-V Instruction Set Manual, Volume I: Unprivileged Architecture",
        "authors": "RISC-V International (editors: Andrew Waterman, Krste Asanović, et al.)",
        "year": "2026",
        "license": "CC BY 4.0",
        "source": "Official riscv/riscv-isa-manual GitHub release riscv-isa-release-b3967cd-2026-08-20",
        "page_url": (
            "https://github.com/riscv/riscv-isa-manual/releases/tag/"
            "riscv-isa-release-b3967cd-2026-08-20"
        ),
        "download_url": (
            "https://github.com/riscv/riscv-isa-manual/releases/download/"
            "riscv-isa-release-b3967cd-2026-08-20/riscv-spec.pdf"
        ),
        "filename": "riscv-spec-unprivileged.pdf",
    },
}

# Preserve commands documented before the filename cleanup while keeping the
# displayed keys short and memorable.
BOOK_ALIASES = {
    "openstax-introduction-computer-science": "intro-cs",
    "think-python-2": "think-python",
    "think-python-2e": "think-python",
    "think-java-2": "think-java",
    "think-java-2e": "think-java",
    "java-language-specification-se26": "jls",
    "jls-26": "jls",
    "java-virtual-machine-specification-se26": "jvms",
    "jvms-26": "jvms",
    "openintro-statistics-4e": "openintro-stats",
    "openstax-calculus-volume-1": "calculus-1",
    "openstax-calculus-volume-2": "calculus-2",
    "openstax-calculus-volume-3": "calculus-3",
    "mathematics-for-machine-learning": "math-for-ml",
    "crafting-interpreters-complete-source": "crafting-interpreters",
    "plai-3e": "plai",
    "security-engineering-3e": "security-engineering",
    "software-engineering-at-google-source": "software-engineering-google",
    "probabilistic-machine-learning-introduction": "pml",
    "introduction-statistical-learning-python": "isl-python",
    "physically-based-rendering-website-source": "pbrt",
    "fairness-and-machine-learning": "fairness-ml",
    "acm-code-of-ethics": "acm-code",
}

MIT6006_BASE = "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/"
MIT6006_PDFS: list[str] = [
    "477c78e0af2df61fa205bcc6cb613ceb_MIT6_006S20_lec1.pdf",
    "79a07dc1cb47d76dae2ffedc701e3d2b_MIT6_006S20_lec2.pdf",
    "6d1ae5278d02bbecb5c4428928b24194_MIT6_006S20_lec3.pdf",
    "ce9e94705b914598ce78a00a70a1f734_MIT6_006S20_lec4.pdf",
    "78a3c3444de1ff837f81e52991c24a86_MIT6_006S20_lec5.pdf",
    "376714cc85c6c784d90eec9c575ec027_MIT6_006S20_lec6.pdf",
    "a2c80596cf4a2b5fbc854afdd2f23dcb_MIT6_006S20_lec7.pdf",
    "40d4851e550507ca14dc778b9b2266cc_MIT6_006S20_lec8.pdf",
    "196a95604877d326c6586e60477b59d4_MIT6_006S20_lec9.pdf",
    "f3e349e0eb3288592289d2c81e0c4f4d_MIT6_006S20_lec10.pdf",
    "aa57a9785adf925bc85c1920f53755a0_MIT6_006S20_lec11.pdf",
    "2430d7903a5529451d80c17f89a41fe8_MIT6_006S20_lec12.pdf",
    "d819e7f4568aced8d5b59e03db6c7b67_MIT6_006S20_lec13.pdf",
    "7d7d5c35490f41b7b037cafbda7019ad_MIT6_006S20_lec14.pdf",
    "9eb3e9a51a7b5b60b0f67c2277f8b0ee_MIT6_006S20_lec15.pdf",
    "28461a74f81101874a13d9679a40584d_MIT6_006S20_lec16.pdf",
    "665523227a175e9e9ce26ea8d3e5b51c_MIT6_006S20_lec17.pdf",
    "f62798df9d8020e1c92130bd76a26f20_MIT6_006S20_lec18.pdf",
    "fda666a4db1dc65b3d71be08115502bd_MIT6_006S20_lec19.pdf",
    "aa4f264093faf990054cc4820553bb46_MIT6_006S20_lec20.pdf",
]
MIT6006_FILES = {
    f"lec-{number:02d}.pdf": MIT6006_BASE + source_name
    for number, source_name in enumerate(MIT6006_PDFS, 1)
}
MIT6006_COMPONENTS = {
    filename: {"title": f"MIT 6.006 — Lecture {number:02d}"}
    for number, filename in enumerate(MIT6006_FILES, 1)
}

BOOK_SETS: dict[str, dict[str, Any]] = {
    "mit-6006": {
        "title": "MIT 6.006 Introduction to Algorithms, Lecture Notes (Spring 2020)",
        "authors": "MIT OpenCourseWare",
        "year": "2020",
        "license": "CC BY-NC-SA 4.0 (MIT OCW)",
        "page_url": MIT6006_BASE,
        "dest": "papers",
        "prefix": "mit-6006",
        "components": MIT6006_COMPONENTS,
        "files": MIT6006_FILES,
    },
    "software-foundations": {
        "title": "Software Foundations (Volumes 1–7, current release sources)",
        "authors": (
            "Benjamin C. Pierce, Arthur Azevedo de Amorim, Chris Casinghino, "
            "Marco Gaboardi, Michael Greenberg, Cătălin Hrițcu, Vilhelm Sjöberg, "
            "Brent Yorgey, Andrew W. Appel, Arthur Charguéraud, and contributors"
        ),
        "year": "2026",
        "license": (
            "Official free electronic textbook sources; author-of-record copyright; "
            "no broad redistribution license stated on the release pages"
        ),
        "page_url": "https://softwarefoundations.cis.upenn.edu/",
        "dest": "books",
        "prefix": "software-foundations",
        "components": {
            "logical-foundations.tgz": {
                "title": "Logical Foundations",
                "version": "7.1 (2026-08-16; Rocq 9.0.0 or later)",
            },
            "programming-language-foundations.tgz": {
                "title": "Programming Language Foundations",
                "version": "7.0 (2026-01-07; Rocq 9.0.0 or later)",
            },
            "verified-functional-algorithms.tgz": {
                "title": "Verified Functional Algorithms",
                "version": "2.0 (2026-01-07; Rocq 9.0.0 or later)",
            },
            "quickchick.tgz": {
                "title": "QuickChick: Property-Based Testing in Rocq",
                "version": "2.0 (2026-01-07; Rocq 9.0.0 or later)",
            },
            "verifiable-c.tgz": {
                "title": "Verifiable C",
                "version": "2.0 (2026-01-07; Rocq 9.0.0)",
            },
            "separation-logic-foundations.tgz": {
                "title": "Separation Logic Foundations",
                "version": "3.0 (2026-01-07; Rocq 9.0.0 or later)",
            },
            "security-foundations.tgz": {
                "title": "Security Foundations",
                "version": "1.0 (2026-01-07; Rocq 9.0.0 or later)",
            },
        },
        "files": {
            "logical-foundations.tgz": (
                "https://softwarefoundations.cis.upenn.edu/lf-current/lf.tgz"
            ),
            "programming-language-foundations.tgz": (
                "https://softwarefoundations.cis.upenn.edu/plf-current/plf.tgz"
            ),
            "verified-functional-algorithms.tgz": (
                "https://softwarefoundations.cis.upenn.edu/vfa-current/vfa.tgz"
            ),
            "quickchick.tgz": (
                "https://softwarefoundations.cis.upenn.edu/qc-current/qc.tgz"
            ),
            "verifiable-c.tgz": (
                "https://softwarefoundations.cis.upenn.edu/vc-current/vc.tgz"
            ),
            "separation-logic-foundations.tgz": (
                "https://softwarefoundations.cis.upenn.edu/slf-current/slf.tgz"
            ),
            "security-foundations.tgz": (
                "https://softwarefoundations.cis.upenn.edu/secf-current/secf.tgz"
            ),
        },
    },
    "art-of-hpc": {
        "title": "The Art of HPC (Vols. 1–4, current PDF builds)",
        "authors": "Victor Eijkhout",
        "year": "2023–2026",
        "license": "CC BY 4.0 (per repository README)",
        "page_url": "https://github.com/VictorEijkhout/TheArtofHPC_pdfs",
        "dest": "books",
        "prefix": "art-of-hpc",
        "components": {
            "vol1-intro-to-hpc.pdf": {
                "title": "Introduction to High Performance Computing",
                "version": "build 2026-01-29",
            },
            "vol2-parallel-programming.pdf": {
                "title": "Parallel Programming in MPI, OpenMP, and PETSc (draft)",
                "version": "build 2026-01-29",
            },
            "vol3-scientific-programming.pdf": {
                "title": "Introduction to Scientific Programming",
                "version": "build 2026-01-09",
            },
            "vol3-programming-projects.pdf": {
                "title": "Programming Projects with C, PETSc, and Trilinos",
                "version": "build 2023-08-16",
            },
            "vol4-hpc-tutorials.pdf": {
                "title": "High Performance Computing Tutorials (draft)",
                "version": "build 2026-01-29",
            },
        },
        "files": {
            "vol1-intro-to-hpc.pdf": (
                "https://raw.githubusercontent.com/VictorEijkhout/TheArtofHPC_pdfs/"
                "main/vol1/EijkhoutIntroToHPC.pdf"
            ),
            "vol2-parallel-programming.pdf": (
                "https://raw.githubusercontent.com/VictorEijkhout/TheArtofHPC_pdfs/"
                "main/vol2/EijkhoutParallelProgramming.pdf"
            ),
            "vol3-scientific-programming.pdf": (
                "https://raw.githubusercontent.com/VictorEijkhout/TheArtofHPC_pdfs/"
                "main/vol3/EijkhoutIntroSciProgramming-book.pdf"
            ),
            "vol3-programming-projects.pdf": (
                "https://raw.githubusercontent.com/VictorEijkhout/TheArtofHPC_pdfs/"
                "main/vol3/EijkhoutProgrammingProjects-book.pdf"
            ),
            "vol4-hpc-tutorials.pdf": (
                "https://raw.githubusercontent.com/VictorEijkhout/TheArtofHPC_pdfs/"
                "main/vol4/EijkhoutHPCtutorials.pdf"
            ),
        },
    },
}

SET_ALIASES = {"mit-6006-algorithms-lectures": "mit-6006"}


class FetchError(RuntimeError):
    """A concise user-facing fetch or validation failure."""


def collapse(value: str) -> str:
    return " ".join((value or "").split())


def slugify(value: str, max_length: int = 70) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug[:max_length].rstrip("-") or "untitled")


def normalize_arxiv_id(value: str) -> str:
    candidate = value.strip()
    candidate = re.sub(r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/", "", candidate)
    candidate = re.sub(r"\.pdf$", "", candidate)
    modern = r"\d{4}\.\d{4,5}(?:v\d+)?"
    legacy = r"[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?"
    if not re.fullmatch(rf"(?:{modern}|{legacy})", candidate, flags=re.I):
        raise FetchError(f"Invalid arXiv identifier: {value}")
    return candidate


def request_bytes(url: str, timeout: int = 60) -> tuple[bytes, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/atom+xml,text/plain,application/json,*/*;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(), response.headers.get_content_type(), response.geturl()
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} from {url}") from exc
    except urllib.error.URLError as exc:
        raise FetchError(f"Could not reach {url}: {exc.reason}") from exc


def arxiv_query(
    *, search_query: str | None = None, id_list: str | None = None, limit: int = 10
) -> bytes:
    params: dict[str, str | int] = {"start": 0, "max_results": max(1, min(limit, 50))}
    if search_query:
        escaped = collapse(search_query).replace('"', "")
        params["search_query"] = f'all:"{escaped}"'
        params["sortBy"] = "relevance"
        params["sortOrder"] = "descending"
    if id_list:
        params["id_list"] = id_list
    url = ARXIV_API + "?" + urllib.parse.urlencode(params)
    payload, content_type, _ = request_bytes(url, timeout=60)
    valid_type = content_type in {"application/atom+xml", "application/xml", "text/xml"}
    if not valid_type and not payload.lstrip().startswith(b"<?xml"):
        raise FetchError(f"arXiv returned unexpected content type: {content_type}")
    return payload


def parse_arxiv_feed(payload: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise FetchError(f"arXiv returned invalid Atom XML: {exc}") from exc
    records: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ATOM):
        identifier_url = collapse(entry.findtext("atom:id", default="", namespaces=ATOM))
        arxiv_id = identifier_url.rsplit("/abs/", 1)[-1]
        title = collapse(entry.findtext("atom:title", default="", namespaces=ATOM))
        summary = collapse(entry.findtext("atom:summary", default="", namespaces=ATOM))
        published = collapse(entry.findtext("atom:published", default="", namespaces=ATOM))
        authors = [
            collapse(node.findtext("atom:name", default="", namespaces=ATOM))
            for node in entry.findall("atom:author", ATOM)
        ]
        pdf_url = ""
        for link in entry.findall("atom:link", ATOM):
            if link.attrib.get("type") == "application/pdf" or link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href", "")
                break
        if pdf_url.startswith("http://"):
            pdf_url = "https://" + pdf_url.removeprefix("http://")
        if title and arxiv_id:
            records.append(
                {
                    "id": arxiv_id,
                    "title": title,
                    "authors": [author for author in authors if author],
                    "published": published,
                    "summary": summary,
                    "abstract_url": identifier_url.replace("http://", "https://", 1),
                    "pdf_url": pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
                }
            )
    return records


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_download(prefix: bytes, content_type: str, expected: str) -> None:
    if not prefix:
        raise FetchError("Downloaded file is empty")
    lower = prefix[:1024].lower()
    if b"<html" in lower or b"<!doctype html" in lower:
        raise FetchError("Source returned an HTML page instead of the requested file")
    if expected == "pdf" and not prefix.startswith(b"%PDF-"):
        raise FetchError(f"Expected PDF bytes, received {content_type}")
    if expected == "epub" and not prefix.startswith(b"PK\x03\x04"):
        raise FetchError(f"Expected EPUB/ZIP bytes, received {content_type}")
    if expected == "zip" and not prefix.startswith(b"PK\x03\x04"):
        raise FetchError(f"Expected ZIP bytes, received {content_type}")
    if expected == "tgz" and not prefix.startswith(b"\x1f\x8b"):
        raise FetchError(f"Expected gzip-compressed tar bytes, received {content_type}")
    if expected == "rfc" and b"request for comments" not in lower and not re.search(rb"rfc[:\s]*\d{3,4}", lower):
        raise FetchError("RFC text did not contain an RFC header")


def stream_download(
    url: str, destination: Path, *, expected: str, overwrite: bool = False
) -> dict[str, Any]:
    if destination.exists() and not overwrite:
        raise FetchError(f"Destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".part", dir=destination.parent
    )
    digest = hashlib.sha256()
    total = 0
    final_url = url
    content_type = "application/octet-stream"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            response = urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as exc:
            raise FetchError(f"HTTP {exc.code} from {url}") from exc
        except urllib.error.URLError as exc:
            raise FetchError(f"Could not reach {url}: {exc.reason}") from exc
        with os.fdopen(descriptor, "wb") as output, response:
            content_type = response.headers.get_content_type()
            final_url = response.geturl()
            first = response.read(128 * 1024)
            validate_download(first, content_type, expected)
            digest.update(first)
            output.write(first)
            total += len(first)
            while True:
                chunk = response.read(128 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                output.write(chunk)
                total += len(chunk)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return {
        "path": str(destination),
        "bytes": total,
        "sha256": digest.hexdigest(),
        "url": final_url,
        "content_type": content_type,
    }


def metadata_path(destination: Path) -> Path:
    """Return the tracked metadata path for a local library payload."""
    relative = destination.resolve().relative_to(REPO_ROOT.resolve())
    return REPO_ROOT / "metadata" / relative.with_suffix(".json")


def save_metadata(destination: Path, metadata: dict[str, Any]) -> Path:
    relative = destination.resolve().relative_to(REPO_ROOT.resolve())
    values = dict(metadata)
    title = values.pop("title", destination.stem)
    values.pop("path", None)
    values["downloaded_at"] = datetime.now(timezone.utc).isoformat()
    document = {"title": title, "path": relative.as_posix(), **values}
    record_path = metadata_path(destination)
    atomic_text(record_path, json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    return record_path


def append_catalog(
    identifier: str, title: str, kind: str, path: Path, metadata: dict[str, Any]
) -> None:
    catalog = REPO_ROOT / "CATALOG.md"
    marker = f"<!-- work: {identifier} -->"
    existing = catalog.read_text(encoding="utf-8") if catalog.exists() else "# Lattice Catalog\n"
    local_path = path.relative_to(REPO_ROOT).as_posix()
    # Manual shelf organization may use a friendlier work identifier than the
    # downloader. The local target is the stable duplicate boundary.
    if marker in existing or f"]({local_path})" in existing:
        return
    authors = metadata.get("authors") or metadata.get("author") or "Unknown"
    if isinstance(authors, list):
        authors = ", ".join(authors)
    source_url = str(metadata.get("source_url", "")).strip()
    source = f"[official page]({source_url})" if source_url else "Not recorded"
    entry = (
        f"\n{marker}\n### [{title}]({local_path})\n\n"
        f"- Type: {kind}\n"
        f"- Authors: {authors}\n"
        f"- Local path: `{local_path}`\n"
        f"- Source: {source}\n"
        f"- License: {metadata.get('license', 'See source record')}\n"
    )
    atomic_text(catalog, existing.rstrip() + "\n" + entry)


def default_paper_filename(record: dict[str, Any]) -> str:
    return f"{slugify(str(record['title']), 48)}.pdf"


def cmd_search(args: argparse.Namespace) -> int:
    records = parse_arxiv_feed(arxiv_query(search_query=args.query, limit=args.limit))
    if args.json:
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return 0 if records else 1
    if not records:
        print(f"No arXiv results for: {args.query}")
        return 1
    for index, record in enumerate(records, 1):
        authors = ", ".join(record["authors"][:4]) or "Unknown"
        print(f"{index}. {record['title']}")
        print(f"   arXiv:{record['id']} — {authors} — {record['published'][:10]}")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    arxiv_id = normalize_arxiv_id(args.arxiv_id)
    records = parse_arxiv_feed(arxiv_query(id_list=arxiv_id, limit=1))
    if not records:
        raise FetchError(f"arXiv record not found: {arxiv_id}")
    record = records[0]
    destination = REPO_ROOT / "papers" / (args.filename or default_paper_filename(record))
    if destination.suffix.lower() != ".pdf":
        destination = destination.with_suffix(".pdf")
    result = stream_download(
        record["pdf_url"], destination, expected="pdf", overwrite=args.overwrite
    )
    metadata = {
        **record,
        "source": "arXiv",
        "source_url": record["abstract_url"],
        "license": "See the license field on the arXiv record",
        "sha256": result["sha256"],
        "bytes": result["bytes"],
    }
    sidecar = save_metadata(destination, metadata)
    append_catalog(f"arxiv:{record['id']}", record["title"], "paper", destination, metadata)
    print(f"Saved: {destination}")
    print(f"Metadata: {sidecar}")
    print(f"SHA-256: {result['sha256']}")
    return 0


def cmd_book(args: argparse.Namespace) -> int:
    if not args.key:
        for key, record in OPEN_BOOKS.items():
            print(f"{key}: {record['title']} ({record['license']})")
        print()
        print("Book/lecture sets (chapter or lecture by chapter):")
        for key, record in BOOK_SETS.items():
            print(f"  {key}: {record['title']} ({len(record['files'])} files)")
        return 0
    key = BOOK_ALIASES.get(args.key, SET_ALIASES.get(args.key, args.key))
    if key in OPEN_BOOKS:
        record = OPEN_BOOKS[key]
        destination = (
            REPO_ROOT
            / record.get("dest", "books")
            / record.get("filename", f"{key}.pdf")
        )
        result = stream_download(
            record["download_url"],
            destination,
            expected=record.get("expected", "pdf"),
            overwrite=args.overwrite,
        )
        metadata = {
            **record,
            "source": record.get("source", "Publisher open edition"),
            "source_url": record["page_url"],
            "sha256": result["sha256"],
            "bytes": result["bytes"],
        }
        sidecar = save_metadata(destination, metadata)
        append_catalog(
            f"book:{key}",
            record["title"],
            record.get("catalog_type", "book"),
            destination,
            metadata,
        )
        print(f"Saved: {destination}")
        print(f"Metadata: {sidecar}")
        print(f"SHA-256: {result['sha256']}")
        return 0
    if key in BOOK_SETS:
        return cmd_set_download(key, args.overwrite)
    raise FetchError(f"Unknown curated book key: {args.key}")


def _set_file_metadata(
    record: dict[str, Any],
    filename: str,
    url: str,
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    path = (
        REPO_ROOT / record["dest"] / record["key"] / filename
        if result is None
        else Path(result["path"])
    )
    if result is None:
        payload = path.read_bytes()
        result = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "url": url,
            "content_type": "application/octet-stream",
        }
    component = record.get("components", {}).get(filename, {})
    metadata = {
        "title": component.get("title", record["title"] + f" — {filename}"),
        "authors": record["authors"],
        "year": record["year"],
        "source": "Open courseware / open textbook set",
        "source_url": record["page_url"],
        "file_url": url,
        "license": record["license"],
        "sha256": result["sha256"],
        "bytes": result["bytes"],
    }
    if component.get("version"):
        metadata["version"] = component["version"]
    return metadata


def cmd_set_download(set_key: str, overwrite: bool) -> int:
    record = dict(BOOK_SETS[set_key])
    record["key"] = set_key
    folder = REPO_ROOT / record["dest"] / set_key
    saved = 0
    failed: list[str] = []
    for filename, url in record["files"].items():
        destination = folder / filename
        sidecar = metadata_path(destination)
        try:
            if destination.exists() and sidecar.exists() and not overwrite:
                saved += 1
                continue
            if destination.exists() and sidecar.exists():
                result = None  # already present: rehash for a consistent sidecar
            elif destination.exists():
                result = None  # present without sidecar: keep file, add metadata
            else:
                result = stream_download(
                    url,
                    destination,
                    expected=expected_kind_for_filename(filename),
                    overwrite=True,
                )
            save_metadata(destination, _set_file_metadata(record, filename, url, result))
            saved += 1
        except FetchError as exc:
            failed.append(f"{filename}: {exc}")
            continue
    if not failed:
        append_catalog(
            f"set:{set_key}",
            record["title"],
            "set",
            folder,
            {
                "authors": record["authors"],
                "source_url": record["page_url"],
                "license": record["license"],
                "file_count": len(record["files"]),
            },
        )
    print(
        f"Set '{set_key}': {saved}/{len(record['files'])} files in {folder}"
        + (f" ({len(failed)} failed)" if failed else "")
    )
    if failed:
        for line in failed:
            print(f"skipped {line}", file=sys.stderr)
    return 0 if not failed else 1


def cmd_sets(_args: argparse.Namespace) -> int:
    for key, record in BOOK_SETS.items():
        print(f"{key}: {record['title']} — {len(record['files'])} files, {record['page_url']}")
    return 0


def cmd_rfc(args: argparse.Namespace) -> int:
    if args.number < 1:
        raise FetchError("RFC number must be positive")
    url = RFC_TEXT_URL.format(number=args.number)
    destination = REPO_ROOT / "papers" / f"rfc-{args.number}.txt"
    result = stream_download(url, destination, expected="rfc", overwrite=args.overwrite)
    title = f"RFC {args.number}"
    metadata = {
        "title": title,
        "authors": "RFC Editor record",
        "source": "RFC Editor",
        "source_url": url,
        "license": "See the RFC document and RFC Editor terms",
        "sha256": result["sha256"],
        "bytes": result["bytes"],
    }
    sidecar = save_metadata(destination, metadata)
    append_catalog(f"rfc:{args.number}", title, "standard", destination, metadata)
    print(f"Saved: {destination}")
    print(f"Metadata: {sidecar}")
    return 0


def expected_kind_for_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "pdf"
    if suffix == ".epub":
        return "epub"
    if suffix == ".zip":
        return "zip"
    if suffix == ".tgz" or filename.lower().endswith(".tar.gz"):
        return "tgz"
    return "file"


def cmd_url(args: argparse.Namespace) -> int:
    parsed = urllib.parse.urlparse(args.url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise FetchError("URL must be a public HTTP(S) URL")
    filename = args.filename or Path(parsed.path).name
    if not filename:
        raise FetchError("Use --filename when the URL has no filename")
    destination = REPO_ROOT / args.dest / filename
    result = stream_download(
        args.url,
        destination,
        expected=expected_kind_for_filename(filename),
        overwrite=args.overwrite,
    )
    metadata = {
        "title": args.title,
        "authors": args.author or "Unknown",
        "source": "User-supplied exact URL",
        "source_url": result["url"],
        "license": args.license,
        "sha256": result["sha256"],
        "bytes": result["bytes"],
    }
    sidecar = save_metadata(destination, metadata)
    append_catalog(
        f"url:{result['sha256']}",
        args.title,
        "book" if args.dest == "books" else "paper",
        destination,
        metadata,
    )
    print(f"Saved: {destination}")
    print(f"Metadata: {sidecar}")
    return 0


def library_payloads() -> list[Path]:
    payloads: list[Path] = []
    for folder in ("books", "papers", "lectures"):
        root = REPO_ROOT / folder
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if (
                not path.is_file()
                or path.name.startswith(".")
                or path.suffix.lower() not in READABLE_PAYLOAD_SUFFIXES
            ):
                continue
            payloads.append(path)
    return payloads


def synced_metadata_path(payload: Path) -> Path:
    return payload.with_name(payload.name + SYNCED_SIDECAR_SUFFIX)


def existing_metadata_path(payload: Path) -> Path:
    tracked = metadata_path(payload)
    return tracked if tracked.is_file() else synced_metadata_path(payload)


def load_canonical_inventory() -> tuple[
    dict[str, tuple[Path, dict[str, Any]]], list[str]
]:
    """Load the canonical payload inventory from tracked metadata only.

    Adjacent ``.library.json`` files belong to private Syncthing imports. They
    remain usable by ``list`` and ``verify``, but they must not silently change
    the repository's canonical artifact set or checksum manifest.
    """
    inventory: dict[str, tuple[Path, dict[str, Any]]] = {}
    issues: list[str] = []
    metadata_root = REPO_ROOT / "metadata"
    record_paths = sorted(metadata_root.rglob("*.json")) if metadata_root.is_dir() else []

    for record_path in record_paths:
        display_path = record_path.relative_to(REPO_ROOT)
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"invalid metadata {display_path}: {exc}")
            continue
        if not isinstance(record, dict):
            issues.append(f"invalid metadata {display_path}: expected a JSON object")
            continue

        relative = record.get("path")
        if not isinstance(relative, str) or not relative:
            issues.append(f"metadata missing path: {display_path}")
            continue
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or not relative_path.parts
            or relative_path.parts[0] not in {"books", "papers", "lectures"}
            or relative_path.as_posix() != relative
        ):
            issues.append(f"metadata has invalid payload path: {display_path}: {relative}")
            continue

        expected_record = metadata_root / relative_path.with_suffix(".json")
        if record_path != expected_record:
            issues.append(
                f"misplaced metadata: {display_path} "
                f"(expected {expected_record.relative_to(REPO_ROOT)})"
            )
        if relative in inventory:
            issues.append(f"duplicate metadata path: {relative}")
            continue
        inventory[relative] = (REPO_ROOT / relative_path, record)

    return inventory, issues


_CATALOG_WORK_ENTRY_RE = re.compile(
    r"<!--\s*work:\s*[^>]+-->\s*(?:###\s*)?\[([^\]]+)\]\(([^)]+)\)"
)


def catalog_readable_work_count(catalog: str) -> int:
    """Count logical reader works, not repeated catalog representations."""
    identities: set[str] = set()
    for title, target in _CATALOG_WORK_ENTRY_RE.findall(catalog):
        local_target = target.split("#", 1)[0].split("?", 1)[0].rstrip("/")
        suffix = Path(local_target).suffix.lower()
        if suffix and suffix not in READABLE_PAYLOAD_SUFFIXES:
            continue
        identity = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
        identities.add(identity or local_target.casefold())
    return len(identities)


def cmd_list(_args: argparse.Namespace) -> int:
    payloads = library_payloads()
    for path in payloads:
        record_path = existing_metadata_path(path)
        title = path.name
        if record_path.exists():
            try:
                title = json.loads(record_path.read_text(encoding="utf-8")).get("title") or title
            except (OSError, json.JSONDecodeError):
                title += " (invalid metadata)"
        else:
            title += " (no metadata)"
        print(f"{path.relative_to(REPO_ROOT)}: {title}")
    if not payloads:
        print("Library contains no downloaded items yet.")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    checked = 0
    failed = 0
    for path in library_payloads():
        checked += 1
        relative = path.relative_to(REPO_ROOT)
        problems: list[str] = []
        record_path = existing_metadata_path(path)
        metadata: dict[str, Any] = {}
        if not record_path.exists():
            problems.append("missing metadata record")
        else:
            try:
                metadata = json.loads(record_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"invalid metadata: {exc}")

        if metadata.get("path") != relative.as_posix():
            problems.append("metadata path does not match payload")

        expected_bytes = metadata.get("bytes")
        if not isinstance(expected_bytes, int):
            problems.append("missing or invalid byte count")
        elif expected_bytes != path.stat().st_size:
            problems.append(f"byte count mismatch ({expected_bytes} != {path.stat().st_size})")

        expected_digest = metadata.get("sha256")
        if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            problems.append("missing or invalid SHA-256")
        elif file_sha256(path) != expected_digest:
            problems.append("SHA-256 mismatch")

        try:
            with path.open("rb") as handle:
                prefix = handle.read(1024)
            if not prefix:
                problems.append("empty file")
            elif path.suffix.lower() == ".pdf" and not prefix.startswith(b"%PDF-"):
                problems.append("invalid PDF signature")
            elif path.suffix.lower() == ".epub":
                with zipfile.ZipFile(path) as archive:
                    if archive.testzip() is not None:
                        problems.append("damaged EPUB archive")
                    elif archive.read("mimetype") != b"application/epub+zip":
                        problems.append("invalid EPUB mimetype")
            elif path.suffix.lower() == ".zip":
                with zipfile.ZipFile(path) as archive:
                    if not archive.infolist():
                        problems.append("empty ZIP archive")
                    elif archive.testzip() is not None:
                        problems.append("damaged ZIP archive")
            elif path.suffix.lower() == ".tgz" or path.name.lower().endswith(".tar.gz"):
                with tarfile.open(path, "r:gz") as archive:
                    if not archive.getmembers():
                        problems.append("empty gzip-compressed tar archive")
        except (OSError, KeyError, tarfile.TarError, zipfile.BadZipFile) as exc:
            problems.append(f"content validation failed: {exc}")

        if problems:
            failed += 1
            print(f"FAIL {relative}: {'; '.join(problems)}")
        elif args.verbose:
            print(f"PASS {relative}")

    if not checked:
        print("Library contains no downloaded items to verify.")
        return 0
    print(f"Verified {checked} items: {checked - failed} passed, {failed} failed.")
    return 1 if failed else 0


def cmd_audit(_args: argparse.Namespace) -> int:
    """Audit the tracked canonical inventory and catalog bookkeeping."""
    inventory, issues = load_canonical_inventory()
    readable_payloads = library_payloads()

    # A readable payload with an adjacent sidecar is a private shared import,
    # not a repository-curated artifact. Only truly unrecorded files are gaps.
    for path in readable_payloads:
        relative = path.relative_to(REPO_ROOT).as_posix()
        if relative not in inventory and not synced_metadata_path(path).is_file():
            issues.append(f"payload has no metadata: {relative}")

    by_digest: dict[str, list[str]] = {}
    actual_digests: dict[str, str] = {}
    for relative, (path, record) in sorted(inventory.items()):
        if not path.is_file():
            issues.append(f"metadata points to missing payload: {relative}")
            continue
        if len(path.name) > 100:
            issues.append(f"filename is longer than 100 characters: {relative}")
        if not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*\.(?:pdf|epub|zip|tgz|txt)", path.name
        ):
            issues.append(f"filename is not normalized kebab-case: {relative}")

        digest = file_sha256(path)
        actual_digests[relative] = digest
        by_digest.setdefault(digest, []).append(relative)
        expected_digest = record.get("sha256")
        if not isinstance(expected_digest, str) or not re.fullmatch(
            r"[0-9a-f]{64}", expected_digest
        ):
            issues.append(f"metadata has missing or invalid SHA-256: {relative}")
        elif digest != expected_digest:
            issues.append(f"metadata SHA-256 mismatch: {relative}")
        expected_bytes = record.get("bytes")
        if not isinstance(expected_bytes, int):
            issues.append(f"metadata has missing or invalid byte count: {relative}")
        elif path.stat().st_size != expected_bytes:
            issues.append(f"metadata byte count mismatch: {relative}")

    duplicate_groups = [paths for paths in by_digest.values() if len(paths) > 1]
    for paths in duplicate_groups:
        issues.append("exact duplicate payloads: " + ", ".join(sorted(paths)))

    manifest_path = REPO_ROOT / "manifests" / "library.sha256"
    manifest_digests: dict[str, str] = {}
    if not manifest_path.exists():
        issues.append("missing canonical manifest: manifests/library.sha256")
    else:
        for number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match:
                issues.append(f"invalid manifest line {number}")
                continue
            digest, relative = match.groups()
            if relative in manifest_digests:
                issues.append(f"duplicate manifest path: {relative}")
            manifest_digests[relative] = digest
        if manifest_digests != actual_digests:
            issues.append("canonical manifest does not match the local payload set")

    catalog = (REPO_ROOT / "CATALOG.md").read_text(encoding="utf-8")
    works = catalog_readable_work_count(catalog)
    readable_artifacts = sum(
        Path(relative).suffix.lower() in READABLE_PAYLOAD_SUFFIXES
        for relative in inventory
    )
    print(
        f"Library audit: {works} readable works, {readable_artifacts} readable artifacts, "
        f"{len(inventory)} canonical records, {len(duplicate_groups)} exact duplicates."
    )
    for issue in issues:
        print(f"FAIL {issue}")
    if not issues:
        print("Audit passed: metadata is complete and every filename is short and normalized.")
    return 1 if issues else 0


def cmd_manifest(_args: argparse.Namespace) -> int:
    """Regenerate the tracked canonical manifest in stable path order."""
    inventory, issues = load_canonical_inventory()
    if issues:
        raise FetchError("cannot build manifest: " + "; ".join(issues))
    missing = [relative for relative, (path, _record) in inventory.items() if not path.is_file()]
    if missing:
        raise FetchError("cannot build manifest; missing payloads: " + ", ".join(sorted(missing)))
    lines = [
        f"{file_sha256(inventory[relative][0])}  {relative}"
        for relative in sorted(inventory)
    ]
    destination = REPO_ROOT / "manifests" / "library.sha256"
    atomic_text(destination, "\n".join(lines) + ("\n" if lines else ""))
    print(f"Wrote {len(lines)} entries to {destination.relative_to(REPO_ROOT)}.")
    return 0


def cmd_self_test(_args: argparse.Namespace) -> int:
    fixture = b'''<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <title>Attention Is All You Need</title>
    <published>2017-06-12T17:57:34Z</published>
    <summary>A transformer architecture.</summary>
    <author><name>Ashish Vaswani</name></author>
    <link title="pdf" href="http://arxiv.org/pdf/1706.03762v7" type="application/pdf" />
  </entry>
</feed>'''
    record = parse_arxiv_feed(fixture)[0]
    checks: list[tuple[str, bool]] = [
        ("arXiv ID validation", normalize_arxiv_id("https://arxiv.org/abs/1706.03762") == "1706.03762"),
        ("Atom title parsing", record["title"] == "Attention Is All You Need"),
        ("HTTPS PDF normalization", record["pdf_url"].startswith("https://arxiv.org/pdf/")),
        ("short paper filename", default_paper_filename(record) == "attention-is-all-you-need.pdf"),
        (
            "central metadata path",
            metadata_path(REPO_ROOT / "books" / "sicp.pdf")
            == REPO_ROOT / "metadata" / "books" / "sicp.json",
        ),
        (
            "OpenStax filename",
            OPEN_BOOKS["intro-cs"]["filename"] == "openstax-intro-cs.pdf",
        ),
        ("SICP manifest", "sicp" in OPEN_BOOKS),
        (
            "MIT 6.006 normalized set",
            list(BOOK_SETS["mit-6006"]["files"])[0] == "lec-01.pdf"
            and len(BOOK_SETS["mit-6006"]["files"]) == 20,
        ),
        ("Think Java manifest", "think-java" in OPEN_BOOKS),
        (
            "Java SE 26 specifications",
            "jls" in OPEN_BOOKS and "jvms" in OPEN_BOOKS,
        ),
        (
            "complete Crafting Interpreters archive",
            OPEN_BOOKS["crafting-interpreters"]["expected"] == "zip",
        ),
        (
            "PBRT website archive",
            OPEN_BOOKS["pbrt"]["expected"] == "zip",
        ),
        ("Software Foundations set", len(BOOK_SETS["software-foundations"]["files"]) == 7),
        ("ZIP kind detection", expected_kind_for_filename("book.zip") == "zip"),
        ("TGZ kind detection", expected_kind_for_filename("volume.tgz") == "tgz"),
    ]
    for label, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {label}")
    return 0 if all(passed for _, passed in checks) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    search = subparsers.add_parser("search", help="Search official arXiv metadata")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=cmd_search)

    download = subparsers.add_parser("download", help="Download an arXiv PDF by identifier")
    download.add_argument("arxiv_id")
    download.add_argument("--filename")
    download.add_argument("--overwrite", action="store_true")
    download.set_defaults(func=cmd_download)

    book = subparsers.add_parser("book", help="List or download a curated open textbook or set")
    book.add_argument("key", nargs="?")
    book.add_argument("--overwrite", action="store_true")
    book.set_defaults(func=cmd_book)

    sets = subparsers.add_parser("sets", help="List downloadable chapter/lecture sets")
    sets.set_defaults(func=cmd_sets)

    rfc = subparsers.add_parser("rfc", help="Download official RFC text")
    rfc.add_argument("number", type=int)
    rfc.add_argument("--overwrite", action="store_true")
    rfc.set_defaults(func=cmd_rfc)

    exact_url = subparsers.add_parser("url", help="Import an exact lawful public URL")
    exact_url.add_argument("url")
    exact_url.add_argument("--title", required=True)
    exact_url.add_argument("--license", required=True)
    exact_url.add_argument("--author")
    exact_url.add_argument("--filename")
    exact_url.add_argument("--dest", choices=["books", "papers"], default="papers")
    exact_url.add_argument("--overwrite", action="store_true")
    exact_url.set_defaults(func=cmd_url)

    listing = subparsers.add_parser("list", help="List downloaded local material")
    listing.set_defaults(func=cmd_list)

    verify = subparsers.add_parser("verify", help="Verify local files against metadata hashes")
    verify.add_argument("--verbose", action="store_true")
    verify.set_defaults(func=cmd_verify)

    audit = subparsers.add_parser(
        "audit", help="Check metadata coverage, duplicate content, and filename hygiene"
    )
    audit.set_defaults(func=cmd_audit)

    manifest = subparsers.add_parser(
        "manifest", help="Regenerate manifests/library.sha256 from local payloads"
    )
    manifest.set_defaults(func=cmd_manifest)

    self_test = subparsers.add_parser("self-test", help="Run deterministic offline tests")
    self_test.set_defaults(func=cmd_self_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except FetchError as exc:
        print(f"fetch.py: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("fetch.py: cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
