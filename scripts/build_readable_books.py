#!/usr/bin/env python3
"""Convert the library's official web/source bundles into readable EPUB 3 books.

The source archives are treated as data. This script extracts only published
reading material into an isolated work directory, sanitizes website chrome,
builds a searchable EPUB with Pandoc, and validates the resulting package. It
does not delete or replace any source archive; cleanup happens only after all
books have independently passed validation.

Runtime requirements:
  * Pandoc 3.x
  * lxml
  * Pillow
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import textwrap
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

try:
    from lxml import etree, html
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:  # pragma: no cover - environment preflight
    raise SystemExit(
        "build_readable_books.py requires lxml and Pillow; run it with the "
        "Codex bundled Python runtime or install those two packages."
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_ROOT = REPO_ROOT / "work" / "readable-books"
PANDOC = shutil.which("pandoc")

SAFE_IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}
DISALLOWED_EPUB_SUFFIXES = {
    ".c",
    ".dart",
    ".h",
    ".java",
    ".tgz",
    ".v",
    ".zip",
}


@dataclass(frozen=True)
class BookSpec:
    slug: str
    archive: str
    output: str
    archive_root: str
    book_root: str
    selection: str
    title: str
    author: str
    cover_author: str
    year: str
    rights: str
    source_url: str
    identifier: str
    palette: tuple[str, str, str]
    minimum_spine_items: int
    minimum_text_chars: int


SOFTWARE_FOUNDATIONS_AUTHOR = (
    "Benjamin C. Pierce, Arthur Azevedo de Amorim, Chris Casinghino, "
    "Marco Gaboardi, Michael Greenberg, Cătălin Hrițcu, Vilhelm Sjöberg, "
    "Brent Yorgey, Andrew W. Appel, Arthur Charguéraud, and contributors"
)


BOOKS: tuple[BookSpec, ...] = (
    BookSpec(
        slug="crafting-interpreters",
        archive="books/crafting-interpreters.zip",
        output="books/crafting-interpreters.epub",
        archive_root="craftinginterpreters-4a840f70f69c6ddd17cfef4f6964f8e1bcd8c3d4",
        book_root="site",
        selection="crafting",
        title="Crafting Interpreters",
        author="Robert Nystrom",
        cover_author="Robert Nystrom",
        year="2021",
        rights="Book text and site: CC BY-NC-ND 4.0",
        source_url="https://craftinginterpreters.com/",
        identifier="crafting-interpreters-4a840f70",
        palette=("#111827", "#0f766e", "#5eead4"),
        minimum_spine_items=25,
        minimum_text_chars=500_000,
    ),
    BookSpec(
        slug="software-engineering-google",
        archive="books/software-engineering-google.zip",
        output="books/software-engineering-google.epub",
        archive_root="abseil.github.io-e9e24835cb889fe25251cb9ec6d51b79233e358d",
        book_root="resources/swe-book/html",
        selection="swe-google",
        title="Software Engineering at Google",
        author="Titus Winters, Tom Manshreck, and Hyrum Wright",
        cover_author="Winters · Manshreck · Wright",
        year="2020",
        rights="Book text: CC BY-NC-ND 4.0",
        source_url="https://abseil.io/resources/swe-book",
        identifier="software-engineering-google-e9e24835",
        palette=("#172554", "#1d4ed8", "#93c5fd"),
        minimum_spine_items=25,
        minimum_text_chars=600_000,
    ),
    BookSpec(
        slug="pbrt-4e",
        archive="books/pbrt-4e.zip",
        output="books/pbrt-4e.epub",
        archive_root="pbr-book-website-b56160a8e4ac0cc8bdd051e8181aa6692b127151",
        book_root="4ed",
        selection="pbrt",
        title="Physically Based Rendering",
        author="Matt Pharr, Wenzel Jakob, and Greg Humphreys",
        cover_author="Pharr · Jakob · Humphreys",
        year="2023",
        rights="Fourth-edition online book: CC BY-NC-ND 4.0",
        source_url="https://www.pbr-book.org/4ed/",
        identifier="pbrt-fourth-edition-b56160a8",
        palette=("#18181b", "#b91c1c", "#fca5a5"),
        # Pandoc keeps each top-level PBRT chapter as one spine document while
        # retaining all 166 section pages in the nested navigation tree.
        minimum_spine_items=20,
        minimum_text_chars=1_500_000,
    ),
    BookSpec(
        slug="logical-foundations",
        archive="books/software-foundations/logical-foundations.tgz",
        output="books/software-foundations/logical-foundations.epub",
        archive_root="lf",
        book_root=".",
        selection="software-foundations",
        title="Logical Foundations",
        author=SOFTWARE_FOUNDATIONS_AUTHOR,
        cover_author="Benjamin C. Pierce et al.",
        year="2026",
        rights="MIT License",
        source_url="https://softwarefoundations.cis.upenn.edu/lf-current/",
        identifier="software-foundations-lf-7.1",
        palette=("#052e16", "#15803d", "#86efac"),
        minimum_spine_items=15,
        minimum_text_chars=250_000,
    ),
    BookSpec(
        slug="programming-language-foundations",
        archive="books/software-foundations/programming-language-foundations.tgz",
        output="books/software-foundations/programming-language-foundations.epub",
        archive_root="plf",
        book_root=".",
        selection="software-foundations",
        title="Programming Language Foundations",
        author=SOFTWARE_FOUNDATIONS_AUTHOR,
        cover_author="Benjamin C. Pierce et al.",
        year="2026",
        rights="MIT License",
        source_url="https://softwarefoundations.cis.upenn.edu/plf-current/",
        identifier="software-foundations-plf-7.0",
        palette=("#2e1065", "#7e22ce", "#d8b4fe"),
        minimum_spine_items=15,
        minimum_text_chars=250_000,
    ),
    BookSpec(
        slug="verified-functional-algorithms",
        archive="books/software-foundations/verified-functional-algorithms.tgz",
        output="books/software-foundations/verified-functional-algorithms.epub",
        archive_root="vfa",
        book_root=".",
        selection="software-foundations",
        title="Verified Functional Algorithms",
        author=SOFTWARE_FOUNDATIONS_AUTHOR,
        cover_author="Andrew W. Appel et al.",
        year="2026",
        rights="MIT License",
        source_url="https://softwarefoundations.cis.upenn.edu/vfa-current/",
        identifier="software-foundations-vfa-2.0",
        palette=("#422006", "#b45309", "#fcd34d"),
        minimum_spine_items=12,
        minimum_text_chars=180_000,
    ),
    BookSpec(
        slug="quickchick",
        archive="books/software-foundations/quickchick.tgz",
        output="books/software-foundations/quickchick.epub",
        archive_root="qc",
        book_root=".",
        selection="software-foundations",
        title="QuickChick: Property-Based Testing in Rocq",
        author=SOFTWARE_FOUNDATIONS_AUTHOR,
        cover_author="Benjamin C. Pierce et al.",
        year="2026",
        rights="MIT License",
        source_url="https://softwarefoundations.cis.upenn.edu/qc-current/",
        identifier="software-foundations-quickchick-2.0",
        palette=("#164e63", "#0891b2", "#67e8f9"),
        minimum_spine_items=6,
        minimum_text_chars=70_000,
    ),
    BookSpec(
        slug="verifiable-c",
        archive="books/software-foundations/verifiable-c.tgz",
        output="books/software-foundations/verifiable-c.epub",
        archive_root="vc",
        book_root=".",
        selection="software-foundations",
        title="Verifiable C",
        author=SOFTWARE_FOUNDATIONS_AUTHOR,
        cover_author="Andrew W. Appel et al.",
        year="2026",
        rights="MIT License",
        source_url="https://softwarefoundations.cis.upenn.edu/vc-current/",
        identifier="software-foundations-vc-2.0",
        palette=("#3f0d12", "#b91c1c", "#fecaca"),
        minimum_spine_items=15,
        minimum_text_chars=150_000,
    ),
    BookSpec(
        slug="separation-logic-foundations",
        archive="books/software-foundations/separation-logic-foundations.tgz",
        output="books/software-foundations/separation-logic-foundations.epub",
        archive_root="slf",
        book_root=".",
        selection="software-foundations",
        title="Separation Logic Foundations",
        author=SOFTWARE_FOUNDATIONS_AUTHOR,
        cover_author="Arthur Charguéraud et al.",
        year="2026",
        rights="MIT License",
        source_url="https://softwarefoundations.cis.upenn.edu/slf-current/",
        identifier="software-foundations-slf-3.0",
        palette=("#312e81", "#4f46e5", "#c7d2fe"),
        minimum_spine_items=12,
        minimum_text_chars=150_000,
    ),
    BookSpec(
        slug="security-foundations",
        archive="books/software-foundations/security-foundations.tgz",
        output="books/software-foundations/security-foundations.epub",
        archive_root="secf",
        book_root=".",
        selection="software-foundations",
        title="Security Foundations",
        author=SOFTWARE_FOUNDATIONS_AUTHOR,
        cover_author="Benjamin C. Pierce et al.",
        year="2026",
        rights="MIT License",
        source_url="https://softwarefoundations.cis.upenn.edu/secf-current/",
        identifier="software-foundations-security-1.0",
        palette=("#1c1917", "#a16207", "#fde68a"),
        minimum_spine_items=4,
        minimum_text_chars=70_000,
    ),
)


@dataclass
class PageDocument:
    source: Path
    relative: PurePosixPath
    page_id: str
    root: html.HtmlElement
    id_map: dict[str, str]


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "page"


def within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and bool(path.parts) and ".." not in path.parts


def wanted_archive_member(spec: BookSpec, name: str) -> bool:
    root = spec.archive_root.rstrip("/") + "/"
    if not name.startswith(root):
        return False
    relative = name[len(root) :]
    if spec.selection == "crafting":
        return relative.startswith("site/") or relative == "LICENSE"
    if spec.selection == "swe-google":
        return relative.startswith("resources/swe-book/html/")
    if spec.selection == "pbrt":
        return relative.startswith("4ed/") or relative == "LICENSE.txt"
    if spec.selection == "software-foundations":
        return (
            relative.endswith(".html")
            or relative.startswith("common/")
            or relative == "LICENSE"
        )
    raise ValueError(f"Unknown selection: {spec.selection}")


def extract_reading_material(spec: BookSpec, destination: Path) -> Path:
    archive_path = REPO_ROOT / spec.archive
    if not archive_path.is_file():
        raise FileNotFoundError(f"Missing source archive: {archive_path}")
    destination.mkdir(parents=True, exist_ok=True)
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            members = [
                member
                for member in archive.infolist()
                if safe_archive_name(member.filename)
                and wanted_archive_member(spec, member.filename)
            ]
            if not members:
                raise ValueError(f"No readable members found in {archive_path.name}")
            archive.extractall(destination, members=members)
    else:
        with tarfile.open(archive_path, "r:gz") as archive:
            members = [
                member
                for member in archive.getmembers()
                if safe_archive_name(member.name)
                and wanted_archive_member(spec, member.name)
            ]
            if not members:
                raise ValueError(f"No readable members found in {archive_path.name}")
            archive.extractall(destination, members=members, filter="data")

    root = destination / spec.archive_root / spec.book_root
    if not root.is_dir():
        raise FileNotFoundError(f"Expected extracted book root is missing: {root}")
    return root.resolve()


def parse_html(path: Path) -> html.HtmlElement:
    parser = html.HTMLParser(encoding="utf-8", recover=True, remove_comments=True)
    return html.parse(str(path), parser=parser).getroot()


def resolve_source_path(
    spec: BookSpec, book_root: Path, current: Path, href_path: str
) -> Path | None:
    decoded = urllib.parse.unquote(href_path).replace("\\", "/")
    if not decoded:
        return current.resolve()
    if decoded.startswith("/"):
        if spec.selection == "pbrt" and decoded.startswith("/4ed/"):
            candidate = book_root / decoded.removeprefix("/4ed/")
        else:
            return None
    else:
        candidate = current.parent / decoded
    candidate = candidate.resolve()
    return candidate if within(candidate, book_root) else None


def toc_pages(spec: BookSpec, book_root: Path) -> list[Path]:
    toc = book_root / ("contents.html" if spec.selection in {"crafting", "pbrt"} else "toc.html")
    if not toc.is_file():
        raise FileNotFoundError(f"Missing table of contents: {toc}")
    tree = parse_html(toc)
    if spec.selection == "crafting":
        links = tree.xpath(
            "//article[contains(concat(' ', normalize-space(@class), ' '), ' contents ')]//a/@href"
        )
    else:
        links = tree.xpath("//a/@href")

    pages: list[Path] = []
    seen: set[Path] = set()
    if spec.selection == "swe-google":
        for name in ("copyright.html",):
            path = (book_root / name).resolve()
            if path.is_file():
                pages.append(path)
                seen.add(path)

    for href in links:
        parsed = urllib.parse.urlsplit(str(href))
        if parsed.scheme or parsed.netloc or not parsed.path.lower().endswith(".html"):
            continue
        candidate = resolve_source_path(spec, book_root, toc, parsed.path)
        if candidate is None or not candidate.is_file() or candidate in seen:
            continue
        if candidate == toc.resolve() or candidate.name in {"coqindex.html", "deps.html"}:
            continue
        if candidate.stem.endswith("Test"):
            continue
        pages.append(candidate)
        seen.add(candidate)

    if spec.selection == "swe-google":
        author_bio = (book_root / "author_bio.html").resolve()
        if author_bio.is_file() and author_bio not in seen:
            pages.append(author_bio)
    if not pages:
        raise ValueError(f"No reading-order pages found for {spec.title}")
    return pages


def content_fragment(spec: BookSpec, tree: html.HtmlElement) -> html.HtmlElement:
    wrapper = html.Element("div")
    wrapper.set("class", "book-page")
    if spec.selection == "crafting":
        candidates = tree.xpath("//article")
        nodes = list(candidates[0]) if candidates else tree.xpath("//body/*")
    elif spec.selection == "software-foundations":
        candidates = tree.xpath("//*[@id='main']")
        nodes = list(candidates[0]) if candidates else tree.xpath("//body/*")
    elif spec.selection == "pbrt":
        candidates = tree.xpath(
            "//*[contains(concat(' ', normalize-space(@class), ' '), ' maincontainer ')]"
        )
        if candidates:
            # PBRT's published pages place the book text in a sequence of
            # Bootstrap columns. Pull the contents of those columns into
            # reading order and leave the empty grid/sidebar wrappers behind.
            columns = candidates[0].xpath(
                ".//*[contains(concat(' ', normalize-space(@class), ' '), "
                "' pretext-layout-root ')]"
            )
            nodes = [child for column in columns for child in list(column)]
        else:
            nodes = tree.xpath("//body/*")
    else:
        body_nodes = tree.xpath("//body/*")
        if spec.selection == "swe-google":
            # Each chapter is wrapped in one site-specific outer <section>.
            # Keeping that wrapper prevents Pandoc from splitting on the
            # chapter heading, so unwrap only this outer layer.
            nodes = [
                child
                for body_node in body_nodes
                for child in (list(body_node) if body_node.tag.lower() == "section" else [body_node])
            ]
        else:
            nodes = body_nodes
    for node in nodes:
        wrapper.append(copy.deepcopy(node))
    return wrapper


def drop_website_chrome(root: html.HtmlElement) -> None:
    for node in list(
        root.xpath(
            ".//script|.//nav|.//footer|.//form|.//iframe|.//noscript|"
            ".//button|.//input|.//source"
        )
    ):
        node.drop_tree()
    for node in list(root.xpath(".//*[@class]")):
        classes = set(str(node.get("class", "")).split())
        if classes & {"gcse-search", "leftcolumn", "scrim"}:
            node.drop_tree()
            continue
        if "pretext-layout-root" in classes and not "".join(node.itertext()).strip() and len(node) == 0:
            node.drop_tree()
    for node in root.iter():
        for attribute in list(node.attrib):
            lower = attribute.lower()
            if (
                not re.fullmatch(r"[A-Za-z_:][A-Za-z0-9_.:-]*", attribute)
                or (node.tag.lower() == "span" and lower == "href")
                or lower.startswith("on")
                or lower.startswith("data-")
                or lower in {"contenteditable", "srcset"}
            ):
                del node.attrib[attribute]
        if "style" in node.attrib:
            # PBRT's MathJax SVGs use one narrowly scoped inline style to
            # align each formula with the surrounding baseline.  Preserve
            # only that safe declaration; all other site styling is dropped.
            style = str(node.get("style", "")).strip()
            vertical_alignment = re.fullmatch(
                r"vertical-align\s*:\s*(-?(?:\d+(?:\.\d+)?|\.\d+)ex)\s*;?",
                style,
                flags=re.IGNORECASE,
            )
            if node.tag.lower() == "svg" and vertical_alignment:
                node.set("style", f"vertical-align: {vertical_alignment.group(1)};")
            else:
                del node.attrib["style"]


def safe_xml_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value).strip("-.")
    if not cleaned or not re.match(r"[A-Za-z_]", cleaned):
        cleaned = "id-" + cleaned
    return cleaned


def normalize_page_headings(root: html.HtmlElement) -> None:
    """Keep one level-one heading per source chapter.

    Some generated HTML books use H1 for both the chapter and each nested
    section. Pandoc then splits footnotes away from their references. When a
    source page has multiple H1 elements, retain the first as the chapter title
    and demote every later heading by one level, preserving the hierarchy and
    keeping chapter-local notes and anchors together.
    """
    headings = list(root.xpath(".//h1|.//h2|.//h3|.//h4|.//h5|.//h6"))
    if sum(1 for heading in headings if heading.tag.lower() == "h1") < 2:
        return
    first_h1_seen = False
    for heading in headings:
        level = int(heading.tag[-1])
        if level == 1 and not first_h1_seen:
            first_h1_seen = True
            continue
        heading.tag = f"h{min(6, level + 1)}"


def prepare_documents(spec: BookSpec, book_root: Path, pages: list[Path]) -> list[PageDocument]:
    documents: list[PageDocument] = []
    used_ids: set[str] = set()
    for source in pages:
        relative = PurePosixPath(source.relative_to(book_root).as_posix())
        page_id = safe_xml_id("page-" + slugify(str(relative.with_suffix(""))))
        if page_id in used_ids:
            suffix = hashlib.sha1(str(relative).encode()).hexdigest()[:8]
            page_id = f"{page_id}-{suffix}"
        used_ids.add(page_id)
        tree = parse_html(source)
        root = content_fragment(spec, tree)
        root.set("id", page_id)
        drop_website_chrome(root)
        normalize_page_headings(root)

        id_map: dict[str, str] = {}
        local_ids: set[str] = {page_id}
        for node in root.xpath(".//*[@id] | .//*[@name]"):
            # Inline SVGs are later materialized as independent image files.
            # Their MathJax glyph IDs intentionally repeat between equations,
            # and their local <use> references must remain paired with those
            # original IDs inside each standalone SVG.
            if node.xpath("ancestor-or-self::svg"):
                continue
            old_id = str(node.get("id") or node.get("name") or "").strip()
            if not old_id:
                continue
            base_candidate = safe_xml_id(f"{page_id}--{old_id}")
            candidate = base_candidate
            duplicate_number = 2
            while candidate in used_ids or candidate in local_ids:
                candidate = f"{base_candidate}-{duplicate_number}"
                duplicate_number += 1
            id_map.setdefault(old_id, candidate)
            local_ids.add(candidate)
            used_ids.add(candidate)
            node.set("id", candidate)
            node.attrib.pop("name", None)

        # Pandoc's paragraph/list AST nodes do not carry arbitrary HTML IDs.
        # Move those targets to a tiny adjacent span so footnotes and other
        # local references survive EPUB conversion as working anchors.
        id_preserving_tags = {"a", "div", "section", "span", "h1", "h2", "h3", "h4", "h5", "h6"}
        for node in list(root.xpath(".//*[@id]")):
            if node.xpath("ancestor-or-self::svg"):
                continue
            if node.tag.lower() in id_preserving_tags:
                continue
            identifier = str(node.attrib.pop("id"))
            anchor = html.Element("span")
            anchor.set("id", identifier)
            anchor.text = "\u00a0"
            parent = node.getparent()
            if parent is not None:
                parent.insert(parent.index(node), anchor)

        if not root.xpath(".//h1|.//h2"):
            title_nodes = tree.xpath("//title")
            heading = html.Element("h1")
            heading.text = (
                "".join(title_nodes[0].itertext()).strip() if title_nodes else source.stem
            )
            root.insert(0, heading)
        documents.append(PageDocument(source, relative, page_id, root, id_map))
    return documents


def source_web_url(spec: BookSpec, current: PageDocument, href: str) -> str:
    base = urllib.parse.urljoin(spec.source_url.rstrip("/") + "/", current.relative.as_posix())
    return urllib.parse.urljoin(base, href)


def rewrite_links_and_assets(
    spec: BookSpec, book_root: Path, documents: list[PageDocument]
) -> None:
    by_source = {document.source.resolve(): document for document in documents}
    for document in documents:
        for node in list(document.root.xpath(".//*[@href]")):
            href = str(node.get("href", "")).strip()
            if not href:
                node.attrib.pop("href", None)
                continue
            parsed = urllib.parse.urlsplit(href)
            if parsed.scheme in {"http", "https", "mailto"} or parsed.netloc:
                continue
            target = resolve_source_path(spec, book_root, document.source, parsed.path)
            if target is not None and target.suffix.lower() in SAFE_IMAGE_SUFFIXES:
                if node.xpath(".//img"):
                    node.drop_tag()
                else:
                    node.set("href", source_web_url(spec, document, href))
                continue
            target_document = by_source.get(target.resolve()) if target is not None else None
            if target_document is not None:
                if parsed.fragment:
                    anchor = target_document.id_map.get(parsed.fragment, target_document.page_id)
                else:
                    anchor = target_document.page_id
                node.set("href", f"#{anchor}")
            elif not parsed.path and parsed.fragment:
                anchor = document.id_map.get(parsed.fragment, document.page_id)
                node.set("href", f"#{anchor}")
            elif parsed.path:
                node.set("href", source_web_url(spec, document, href))
            else:
                node.attrib.pop("href", None)

        for node in list(document.root.xpath(".//img[@src]")):
            src = str(node.get("src", "")).strip()
            parsed = urllib.parse.urlsplit(src)
            if parsed.scheme == "data":
                continue
            if parsed.scheme or parsed.netloc:
                node.drop_tree()
                continue
            asset = resolve_source_path(spec, book_root, document.source, parsed.path)
            if asset is not None and asset.suffix.lower() not in SAFE_IMAGE_SUFFIXES:
                fallback = asset.with_suffix(".png")
                asset = fallback if fallback.is_file() else None
            if asset is None or not asset.is_file():
                alt = node.get("alt") or ""
                replacement = html.Element("span")
                replacement.set("class", "missing-figure")
                replacement.text = f"[Figure: {alt}]" if alt else "[Figure unavailable]"
                node.getparent().replace(node, replacement)
                continue
            node.set("src", asset.resolve().as_posix())


def materialize_inline_svgs(
    documents: list[PageDocument], destination: Path
) -> int:
    """Turn inline SVGs into EPUB-friendly image resources.

    Pandoc already extracts inline SVG, but an HTML parse lowercases SVG's
    case-sensitive ``viewBox`` attribute and a generic ebook image rule makes
    inline equations behave like block figures.  Writing explicit resources
    here preserves MathJax's glyph references, intrinsic dimensions, baseline
    alignment, and accessible spoken-math title.
    """
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    for document in documents:
        for svg in list(document.root.xpath(".//*[local-name()='svg']")):
            count += 1
            if "viewbox" in svg.attrib:
                svg.set("viewBox", svg.attrib.pop("viewbox"))

            titles = [" ".join(value.split()) for value in svg.xpath(".//title/text()")]
            alt = next((value for value in titles if value), "Mathematical expression")
            style = str(svg.get("style", "")).strip()
            classes = {
                class_name
                for ancestor in svg.iterancestors()
                for class_name in str(ancestor.get("class", "")).split()
            }
            image_class = "math-display" if "displaymath" in classes else "math-inline"

            resource = destination / f"formula-{count:05d}.svg"
            theme = html.Element("style")
            theme.set("type", "text/css")
            theme.text = (
                ":root { color: #0f172a; } "
                "@media (prefers-color-scheme: dark) { :root { color: #f8fafc; } }"
            )
            svg.insert(0, theme)
            resource.write_text(
                etree.tostring(svg, encoding="unicode", method="xml", with_tail=False),
                encoding="utf-8",
            )

            image = html.Element("img")
            image.set("src", resource.resolve().as_posix())
            image.set("alt", alt)
            image.set("class", image_class)
            if style:
                image.set("style", style)
            image.tail = svg.tail
            parent = svg.getparent()
            if parent is None:
                raise ValueError("Inline SVG has no parent element")
            parent.replace(svg, image)
    return count


EBOOK_CSS = r"""
:root { color-scheme: light dark; }
body {
  font-family: Charter, "Iowan Old Style", Georgia, serif;
  line-height: 1.55;
  margin: 0 5%;
  orphans: 2;
  widows: 2;
}
h1, h2, h3, h4 {
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
  line-height: 1.15;
  page-break-after: avoid;
}
h1 { margin-top: 1.5em; }
h2 { margin-top: 1.4em; }
p { margin: 0.55em 0; }
a { color: #2563eb; text-decoration: none; }
img, svg { height: auto; max-width: 100%; }
img { display: block; margin: 1em auto; }
img.math-inline {
  display: inline;
  margin: 0 0.04em;
  max-width: none;
}
img.math-display { display: block; margin: 0.8em auto; }
figure { break-inside: avoid; margin: 1.25em 0; text-align: center; }
figcaption { color: #64748b; font-size: 0.88em; }
pre, code, .inlinecode {
  font-family: "SFMono-Regular", Menlo, Consolas, monospace;
}
pre {
  background: #f1f5f9;
  border-left: 0.22em solid #94a3b8;
  font-size: 0.82em;
  line-height: 1.38;
  overflow-wrap: anywhere;
  padding: 0.8em;
  white-space: pre-wrap;
}
code, .inlinecode { overflow-wrap: anywhere; }
blockquote {
  border-left: 0.24em solid #94a3b8;
  color: #475569;
  margin-left: 0;
  padding-left: 1em;
}
aside {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-radius: 0.4em;
  font-size: 0.9em;
  margin: 1em 0;
  padding: 0.75em 1em;
}
table { border-collapse: collapse; display: table; max-width: 100%; }
th, td { border: 1px solid #cbd5e1; padding: 0.35em 0.5em; }
.book-page { margin: 0; padding: 0; }
.number { color: #64748b; font-family: sans-serif; font-weight: 700; }
.subtitle { display: block; font-size: 0.62em; font-weight: 400; margin-top: 0.25em; }
.missing-figure { color: #64748b; font-style: italic; }
@media (prefers-color-scheme: dark) {
  pre, aside { background: #172033; }
  blockquote, figcaption, .number, .missing-figure { color: #a8b4c7; }
  th, td, aside { border-color: #475569; }
  a { color: #93c5fd; }
}
""".strip()


def font_path(bold: bool = False) -> Path | None:
    candidates = (
        [
            Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
            Path("/System/Library/Fonts/Supplemental/Helvetica.ttc"),
        ]
        if bold
        else [
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
            Path("/System/Library/Fonts/Supplemental/Helvetica.ttc"),
        ]
    )
    return next((path for path in candidates if path.is_file()), None)


def load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = font_path(bold)
    return ImageFont.truetype(str(path), size) if path else ImageFont.load_default()


def wrap_to_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def make_cover(spec: BookSpec, destination: Path) -> None:
    width, height = 1600, 2560
    image = Image.new("RGB", (width, height), spec.palette[0])
    draw = ImageDraw.Draw(image)
    accent = spec.palette[1]
    highlight = spec.palette[2]
    for y in range(height):
        alpha = y / max(1, height - 1)
        shade = int(10 + 20 * alpha)
        draw.line((0, y, width, y), fill=(shade, shade + 3, shade + 10))
    draw.rectangle((0, 0, 94, height), fill=accent)
    draw.rounded_rectangle((1160, 155, 1490, 485), radius=80, outline=highlight, width=8)
    draw.line((1160, 485, 1490, 155), fill=highlight, width=8)
    draw.text((170, 175), "CS LIBRARY  •  READABLE EDITION", font=load_font(34, bold=True), fill=highlight)

    max_title_width = 1180
    title_font = load_font(152, bold=True)
    lines = wrap_to_width(draw, spec.title, title_font, max_title_width)
    while (len(lines) > 5 or max(draw.textlength(line, font=title_font) for line in lines) > max_title_width) and getattr(title_font, "size", 80) > 86:
        title_font = load_font(getattr(title_font, "size", 152) - 6, bold=True)
        lines = wrap_to_width(draw, spec.title, title_font, max_title_width)
    line_height = int(getattr(title_font, "size", 110) * 1.08)
    top = 690
    for line in lines:
        draw.text((170, top), line, font=title_font, fill="#f8fafc")
        top += line_height

    draw.rectangle((170, top + 90, 610, top + 102), fill=accent)
    author_font = load_font(54)
    author_lines = wrap_to_width(draw, spec.cover_author, author_font, 1180)
    author_top = top + 180
    for line in author_lines:
        draw.text((170, author_top), line, font=author_font, fill="#dbeafe")
        author_top += 72
    draw.text((170, 2310), spec.year, font=load_font(42, bold=True), fill=highlight)
    draw.text((170, 2380), "OFFLINE • SEARCHABLE • COMPLETE TEXT", font=load_font(28, bold=True), fill="#cbd5e1")
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="JPEG", quality=92, optimize=True, progressive=True)


def write_sanitized_documents(documents: list[PageDocument], destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    output: list[Path] = []
    for number, document in enumerate(documents, 1):
        path = destination / f"{number:03d}-{slugify(document.source.stem)}.html"
        # Keep headings at the document's top level. Pandoc deliberately avoids
        # splitting EPUB chapters at headings nested inside a generic Div, so a
        # wrapper here would collapse an entire part of a book into one file.
        # The standalone span retains the stable cross-page target without
        # changing the source's heading hierarchy.
        children = "".join(
            html.tostring(child, encoding="unicode", method="html")
            for child in document.root
        )
        payload = f'<span id="{document.page_id}"></span>\n{children}'
        path.write_text(payload, encoding="utf-8")
        output.append(path)
    return output


def append_license_document(
    spec: BookSpec, book_root: Path, destination: Path, documents: list[Path]
) -> None:
    """Append a bundled license notice when redistribution requires it."""
    if spec.selection != "software-foundations":
        return
    source = book_root / "LICENSE"
    if not source.is_file():
        raise FileNotFoundError(f"Bundled license is missing: {source}")
    section = html.Element("section")
    heading = etree.SubElement(section, "h1")
    heading.text = "License"
    introduction = etree.SubElement(section, "p")
    introduction.text = "This readable edition preserves the license bundled with the source release."
    notice = etree.SubElement(section, "pre")
    notice.set("class", "license-notice")
    notice.text = source.read_text(encoding="utf-8").strip()
    path = destination / "999-license.html"
    path.write_text(
        "".join(
            html.tostring(child, encoding="unicode", method="html")
            for child in section
        ),
        encoding="utf-8",
    )
    documents.append(path)


def build_epub(spec: BookSpec, work_root: Path, *, force: bool) -> dict[str, int]:
    if not PANDOC:
        raise SystemExit("Pandoc is not installed or not available on PATH.")
    output = REPO_ROOT / spec.output
    if output.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite {output}; pass --force to rebuild")

    spec_work = (work_root / spec.slug).resolve()
    if not within(spec_work, work_root):
        raise ValueError(f"Unsafe work directory: {spec_work}")
    if spec_work.exists():
        shutil.rmtree(spec_work)
    extracted = spec_work / "extracted"
    book_root = extract_reading_material(spec, extracted)
    pages = toc_pages(spec, book_root)
    documents = prepare_documents(spec, book_root, pages)
    rewrite_links_and_assets(spec, book_root, documents)
    materialize_inline_svgs(documents, spec_work / "inline-svg")

    sanitized = write_sanitized_documents(documents, spec_work / "sanitized")
    append_license_document(spec, book_root, spec_work / "sanitized", sanitized)
    css = spec_work / "ebook.css"
    css.write_text(EBOOK_CSS + "\n", encoding="utf-8")
    cover = spec_work / "cover.jpg"
    make_cover(spec, cover)
    temporary_output = spec_work / f"{spec.slug}.epub"
    command = [
        PANDOC,
        *[str(path) for path in sanitized],
        "--from=html",
        "--to=epub3",
        f"--output={temporary_output}",
        f"--metadata=title:{spec.title}",
        f"--metadata=author:{spec.author}",
        f"--metadata=date:{spec.year}",
        "--metadata=lang:en-US",
        f"--metadata=rights:{spec.rights}",
        f"--metadata=identifier:{spec.identifier}",
        "--toc",
        "--toc-depth=2",
        "--split-level=1",
        f"--epub-cover-image={cover}",
        f"--css={css}",
        "--wrap=none",
    ]
    result = subprocess.run(
        command,
        cwd=book_root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    (spec_work / "pandoc.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Pandoc failed for {spec.title}:\n{result.stderr[-4000:]}")
    missing_resource_lines = [
        line
        for line in result.stderr.splitlines()
        if "Could not fetch resource" in line or "not found" in line.lower()
    ]
    if missing_resource_lines:
        raise RuntimeError(
            f"Pandoc reported missing resources for {spec.title}:\n"
            + "\n".join(missing_resource_lines[:20])
        )

    required_text = (
        "Permission is hereby granted"
        if spec.selection == "software-foundations"
        else None
    )
    stats = validate_epub(temporary_output, required_text=required_text)
    if stats["spine_items"] < spec.minimum_spine_items:
        raise ValueError(
            f"{spec.title} has only {stats['spine_items']} spine items; "
            f"expected at least {spec.minimum_spine_items}"
        )
    if stats["text_chars"] < spec.minimum_text_chars:
        raise ValueError(
            f"{spec.title} has only {stats['text_chars']} text characters; "
            f"expected at least {spec.minimum_text_chars}"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    staged = output.with_name(output.name + ".part")
    shutil.copy2(temporary_output, staged)
    os.replace(staged, output)
    return stats


def archive_member_path(base: PurePosixPath, href: str) -> PurePosixPath:
    decoded = urllib.parse.unquote(urllib.parse.urlsplit(href).path)
    combined = base / PurePosixPath(decoded)
    parts: list[str] = []
    for part in combined.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return PurePosixPath(*parts)


def validate_epub(path: Path, *, required_text: str | None = None) -> dict[str, int]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not infos or infos[0].filename != "mimetype":
            raise ValueError(f"{path.name}: mimetype must be the first EPUB member")
        if infos[0].compress_type != zipfile.ZIP_STORED:
            raise ValueError(f"{path.name}: mimetype must be stored without compression")
        if archive.read("mimetype") != b"application/epub+zip":
            raise ValueError(f"{path.name}: invalid EPUB mimetype")
        damaged = archive.testzip()
        if damaged:
            raise ValueError(f"{path.name}: damaged ZIP member {damaged}")
        names = {info.filename for info in infos if not info.is_dir()}
        disallowed = sorted(
            name for name in names if PurePosixPath(name).suffix.lower() in DISALLOWED_EPUB_SUFFIXES
        )
        if disallowed:
            raise ValueError(f"{path.name}: source/build files leaked into EPUB: {disallowed[:5]}")

        container = etree.fromstring(archive.read("META-INF/container.xml"))
        rootfiles = container.xpath("//*[local-name()='rootfile']/@full-path")
        if len(rootfiles) != 1:
            raise ValueError(f"{path.name}: expected one EPUB rootfile")
        opf_name = str(rootfiles[0])
        package = etree.fromstring(archive.read(opf_name))
        manifest_items = package.xpath("//*[local-name()='manifest']/*[local-name()='item']")
        manifest: dict[str, str] = {
            str(item.get("id")): str(item.get("href")) for item in manifest_items
        }
        opf_dir = PurePosixPath(opf_name).parent
        missing_manifest = [
            href
            for href in manifest.values()
            if archive_member_path(opf_dir, href).as_posix() not in names
        ]
        if missing_manifest:
            raise ValueError(f"{path.name}: missing manifest members: {missing_manifest[:5]}")

        spine_refs = package.xpath("//*[local-name()='spine']/*[local-name()='itemref']/@idref")
        if not spine_refs or any(str(ref) not in manifest for ref in spine_refs):
            raise ValueError(f"{path.name}: invalid or empty EPUB spine")

        xhtml_names = sorted(
            name for name in names if PurePosixPath(name).suffix.lower() in {".xhtml", ".html"}
        )
        text_chars = 0
        found_required_text = required_text is None
        image_refs = 0
        link_refs = 0
        broken_refs: list[str] = []
        math_svg_names: set[str] = set()
        documents: dict[str, etree._Element] = {}
        ids_by_document: dict[str, set[str]] = {}
        for name in xhtml_names:
            document = etree.fromstring(archive.read(name))
            documents[name] = document
            identifiers = [str(value) for value in document.xpath("//*[@id]/@id")]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"{path.name}: duplicate XHTML identifiers in {name}")
            ids_by_document[name] = set(identifiers)
            document_text = "".join(document.itertext()).strip()
            text_chars += len(document_text)
            if required_text and required_text in document_text:
                found_required_text = True
            base = PurePosixPath(name).parent
            for image in document.xpath("//*[local-name()='img']"):
                src = str(image.get("src", ""))
                parsed = urllib.parse.urlsplit(str(src))
                if parsed.scheme or parsed.netloc:
                    broken_refs.append(f"external image {src}")
                    continue
                image_refs += 1
                target = archive_member_path(base, str(src)).as_posix()
                if target not in names:
                    broken_refs.append(f"{name} -> {src}")
                classes = set(str(image.get("class", "")).split())
                if classes & {"math-inline", "math-display"}:
                    math_svg_names.add(target)
        for name, document in documents.items():
            base = PurePosixPath(name).parent
            for href in document.xpath("//*[local-name()='a']/@href"):
                parsed = urllib.parse.urlsplit(str(href))
                if parsed.scheme or parsed.netloc:
                    continue
                if not parsed.path and not parsed.fragment:
                    continue
                link_refs += 1
                target = (
                    name
                    if not parsed.path
                    else archive_member_path(base, parsed.path).as_posix()
                )
                if target not in names:
                    broken_refs.append(f"{name} -> {href}")
                    continue
                if parsed.fragment and target in ids_by_document:
                    anchor = urllib.parse.unquote(parsed.fragment)
                    if anchor not in ids_by_document[target]:
                        broken_refs.append(f"{name} -> {href} (missing anchor)")

        svg_names = sorted(
            name for name in names if PurePosixPath(name).suffix.lower() == ".svg"
        )
        for name in svg_names:
            svg = etree.fromstring(archive.read(name))
            if any("viewbox" in element.attrib for element in svg.iter()):
                broken_refs.append(f"{name} uses invalid lowercase viewbox")
            nodes_with_ids = list(svg.xpath("//*[@id]"))
            identifiers = [str(element.get("id")) for element in nodes_with_ids]
            if len(identifiers) != len(set(identifiers)):
                broken_refs.append(f"{name} has duplicate SVG identifiers")
                continue
            identifier_nodes = {
                str(element.get("id")): element for element in nodes_with_ids
            }
            if svg.xpath("//*[local-name()='span']"):
                broken_refs.append(f"{name} contains non-SVG span anchors")
            if name in math_svg_names:
                svg_styles = " ".join(svg.xpath("//*[local-name()='style']/text()"))
                if "prefers-color-scheme" not in svg_styles:
                    broken_refs.append(f"{name} lacks light/dark math colors")
            for href in svg.xpath("//@*[local-name()='href']"):
                href = str(href)
                if not href.startswith("#"):
                    continue
                target = identifier_nodes.get(urllib.parse.unquote(href[1:]))
                if target is None:
                    broken_refs.append(f"{name} -> {href} (missing SVG target)")
                elif etree.QName(target).localname == "span":
                    broken_refs.append(f"{name} -> {href} (non-graphic SVG target)")
        if broken_refs:
            raise ValueError(f"{path.name}: broken internal references: {broken_refs[:8]}")
        if not found_required_text:
            raise ValueError(f"{path.name}: required notice is missing: {required_text}")
        return {
            "members": len(names),
            "spine_items": len(spine_refs),
            "xhtml_files": len(xhtml_names),
            "images": image_refs,
            "links": link_refs,
            "text_chars": text_chars,
            "bytes": path.stat().st_size,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "slugs",
        nargs="*",
        help="Optional book slugs; omit to build all ten readable books",
    )
    parser.add_argument("--force", action="store_true", help="Replace existing EPUB outputs")
    parser.add_argument(
        "--work-root",
        type=Path,
        default=DEFAULT_WORK_ROOT,
        help="Isolated extraction and conversion directory",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing EPUB outputs without rebuilding them",
    )
    return parser


def selected_specs(slugs: Iterable[str]) -> list[BookSpec]:
    by_slug = {spec.slug: spec for spec in BOOKS}
    requested = list(slugs)
    unknown = sorted(set(requested) - set(by_slug))
    if unknown:
        raise SystemExit("Unknown book slug(s): " + ", ".join(unknown))
    return [by_slug[slug] for slug in requested] if requested else list(BOOKS)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    specs = selected_specs(args.slugs)
    work_root = args.work_root.resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    if args.validate_only:
        for spec in specs:
            required_text = (
                "Permission is hereby granted"
                if spec.selection == "software-foundations"
                else None
            )
            stats = validate_epub(REPO_ROOT / spec.output, required_text=required_text)
            print(
                f"PASS {spec.output}: {stats['spine_items']} sections, "
                f"{stats['images']} figures, {stats['text_chars']:,} text characters, "
                f"{stats['bytes'] / 1024 / 1024:.1f} MiB"
            )
        return 0

    for index, spec in enumerate(specs, 1):
        print(f"[{index}/{len(specs)}] Building {spec.title}...", flush=True)
        stats = build_epub(spec, work_root, force=args.force)
        print(
            f"PASS {spec.output}: {stats['spine_items']} sections, "
            f"{stats['images']} figures, {stats['text_chars']:,} text characters, "
            f"{stats['bytes'] / 1024 / 1024:.1f} MiB",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
