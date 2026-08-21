#!/usr/bin/env python3
"""Serve the CS library as a private, local-only virtual bookshelf.

The server binds to loopback, derives its curated inventory from CATALOG.md,
and discovers newly added readable files under books/ and papers/. It never
uploads or copies a book. macOS file actions are token-protected and restricted
to files currently present inside the local library.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import posixpath
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree


REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = REPO_ROOT / "ui"
CATALOG_PATH = REPO_ROOT / "CATALOG.md"
METADATA_ROOT = REPO_ROOT / "metadata"
ALLOWED_DOCUMENTS = frozenset(
    {
        "README.md",
        "CATALOG.md",
        "STUDY_GUIDE.md",
        "LIBRARY_RULES.md",
        "manifests/library.sha256",
        "notes/provenance/library-cleanup-2026-08-20.md",
        "notes/provenance/cs-books-import-2026-08-20.md",
        "notes/provenance/free-study-expansion-2026-08-20.md",
        "notes/provenance/readable-editions-2026-08-21.md",
    }
)
WORK_CELL = re.compile(
    r"<!-- work: (?P<id>[^>]+) -->\s*"
    r"\[(?P<title>[^]]+)]\((?P<path>[^)]+)\)"
)
SOURCE_LINK = re.compile(r"\[[^]]+]\((?P<url>https?://[^)]+)\)")
RANGE_HEADER = re.compile(r"bytes=(?P<start>\d*)-(?P<end>\d*)$")
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MATERIAL_LABELS = {
    "book": "Books",
    "lecture": "Lectures",
    "course-volume": "Course volumes",
    "paper": "Papers",
    "specification": "Specifications",
    "standard": "Standards",
}
READABLE_SUFFIXES = frozenset({".epub", ".pdf", ".txt"})
WATCH_INTERVAL_SECONDS = 0.65
PROTOCOL_VERSION = 2
EPUB_XML_LIMIT = 8 * 1024 * 1024
EPUB_RESOURCE_LIMIT = 256 * 1024 * 1024
EPUB_ENTRY_LIMIT = 20_000
EPUB_TOTAL_LIMIT = 1024 * 1024 * 1024
EPUB_COMPRESSION_RATIO_LIMIT = 200
EPUB_ACTIVE_SUFFIXES = frozenset({".js", ".mjs", ".wasm"})
EPUB_DOCUMENT_TYPES = frozenset({"application/xhtml+xml", "text/html"})
EPUB_OPS_NAMESPACE = "http://www.idpf.org/2007/ops"


def library_identity(root: Path) -> str:
    """Return the same stable canonical-root identity used by the native app."""
    canonical = root.expanduser().resolve()
    return hashlib.sha256(f"cs-library:{canonical}".encode("utf-8")).hexdigest()


def slugify(value: str) -> str:
    """Return a compact URL/CSS-safe shelf identifier."""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "shelf"


def _read_metadata(root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    metadata_root = root / "metadata"
    for record_path in sorted(metadata_root.rglob("*.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid metadata record {record_path}: {exc}") from exc
        relative = record.get("path")
        if not isinstance(relative, str) or not relative:
            raise ValueError(f"Metadata record has no payload path: {record_path}")
        if relative in records:
            raise ValueError(f"Duplicate metadata payload path: {relative}")
        records[relative] = record
    return records


def _file_record(root: Path, path: str, metadata: dict[str, Any]) -> dict[str, Any]:
    payload = root / path
    exists = payload.is_file()
    suffix = payload.suffix.lower().lstrip(".") or "file"
    stat = payload.stat() if exists else None
    return {
        "title": metadata.get("title") or _display_title(path),
        "path": path,
        "format": suffix.upper(),
        "bytes": stat.st_size if stat else int(metadata.get("bytes") or 0),
        "sha256": metadata.get("sha256") or "",
        "license": metadata.get("license") or "Not recorded",
        "sourceUrl": metadata.get("source_url") or metadata.get("page_url") or "",
        "fileUrl": metadata.get("file_url") or metadata.get("download_url") or "",
        "version": metadata.get("version") or metadata.get("edition") or "",
        "downloadedAt": metadata.get("downloaded_at") or "",
        "exists": exists,
        "cataloged": bool(metadata),
        "modifiedNs": stat.st_mtime_ns if stat else 0,
    }


def _discover_payload_paths(root: Path) -> set[str]:
    """Return readable, in-repository payload paths currently on disk."""
    resolved_root = root.resolve()
    discovered: set[str] = set()
    for shelf_name in ("books", "papers"):
        shelf = root / shelf_name
        if not shelf.is_dir():
            continue
        for candidate in shelf.rglob("*"):
            if (
                not candidate.is_file()
                or candidate.suffix.lower() not in READABLE_SUFFIXES
                or any(part.startswith(".") for part in candidate.relative_to(root).parts)
            ):
                continue
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.is_relative_to(resolved_root):
                discovered.add(candidate.relative_to(root).as_posix())
    return discovered


def _display_title(path: str) -> str:
    """Turn a tidy shelf filename into a readable temporary display title."""
    words = re.sub(r"[-_]+", " ", Path(path).stem).split()
    small_words = {"a", "an", "and", "at", "for", "in", "of", "on", "the", "to"}
    initialisms = {"ai", "api", "cs", "gpu", "jls", "jvm", "jvms", "mit", "ml", "rfc", "sql"}
    rendered: list[str] = []
    for index, word in enumerate(words):
        lowered = word.lower()
        if lowered in initialisms:
            rendered.append(lowered.upper())
        elif index and lowered in small_words:
            rendered.append(lowered)
        elif re.fullmatch(r"\d+e", lowered):
            rendered.append(lowered)
        else:
            rendered.append(lowered.capitalize())
    return " ".join(rendered) or "New local book"


def _metadata_authors(metadata: dict[str, Any]) -> str:
    value = metadata.get("authors") or metadata.get("author") or "Added locally"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _classify_work(work_id: str, local_path: str) -> str:
    if work_id == "mit-6006":
        return "lecture"
    if work_id == "software-foundations":
        return "course-volume"
    if work_id in {"jls", "jvms"}:
        return "specification"
    if work_id in {"rfc-791", "acm-code"}:
        return "standard"
    if local_path.startswith("papers/"):
        return "paper"
    return "book"


def build_library(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Build the curated catalog plus any readable files newly added on disk."""
    catalog_path = root / "CATALOG.md"
    metadata = _read_metadata(root)
    physical_paths = _discover_payload_paths(root)
    current_subject = ""
    works: list[dict[str, Any]] = []
    subjects: list[dict[str, Any]] = []
    subject_ids: set[str] = set()

    for raw_line in catalog_path.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("## "):
            heading = raw_line.removeprefix("## ").strip()
            if heading in {"Collection file index", "Collection notes", "Jump to a shelf"}:
                current_subject = ""
            else:
                current_subject = heading
            continue
        if "<!-- work:" not in raw_line:
            continue
        # fetch.py appends detailed Markdown records whose marker is on its own
        # line. They are not curated shelf rows; their readable payloads are
        # discovered below and shown under New arrivals until manually shelved.
        if not raw_line.lstrip().startswith("|"):
            continue
        if not current_subject:
            raise ValueError(f"Catalog work appears outside a shelf: {raw_line}")

        cells = [cell.strip() for cell in raw_line.strip().strip("|").split("|")]
        if len(cells) != 6:
            raise ValueError(f"Expected six catalog columns: {raw_line}")
        title_cell, authors, edition, _local_cell, source_cell, access = cells
        match = WORK_CELL.search(title_cell)
        if not match:
            raise ValueError(f"Could not parse catalog work row: {raw_line}")

        work_id = match.group("id")
        title = match.group("title")
        local_path = urllib.parse.unquote(match.group("path"))
        source_match = SOURCE_LINK.search(source_cell)
        source_url = source_match.group("url") if source_match else ""
        subject_id = slugify(current_subject)
        if subject_id not in subject_ids:
            subject_ids.add(subject_id)
            subjects.append({"id": subject_id, "name": current_subject})

        if local_path.endswith("/"):
            file_paths = sorted(
                {path for path in metadata if path.startswith(local_path)}
                | {path for path in physical_paths if path.startswith(local_path)}
            )
        else:
            file_paths = [local_path] if local_path in metadata or local_path in physical_paths else []
        if not file_paths:
            raise ValueError(f"Catalog work has no matching metadata: {work_id}")

        files = [_file_record(root, path, metadata.get(path, {})) for path in file_paths]
        formats = sorted({file["format"] for file in files})
        material_type = _classify_work(work_id, local_path)
        works.append(
            {
                "id": work_id,
                "title": title,
                "authors": authors,
                "edition": edition,
                "subject": current_subject,
                "subjectId": subject_id,
                "localPath": local_path,
                "sourceUrl": source_url,
                "access": access,
                "files": files,
                "fileCount": len(files),
                "totalBytes": sum(int(file["bytes"]) for file in files),
                "formats": formats,
                "materialType": material_type,
                "materialLabel": MATERIAL_LABELS[material_type],
                "isCollection": len(files) > 1,
                "isAvailable": all(file["exists"] for file in files),
                "availableFileCount": sum(1 for file in files if file["exists"]),
                "cataloged": True,
            }
        )

    linked_paths = {file["path"] for work in works for file in work["files"]}
    new_arrival_paths = sorted(physical_paths - linked_paths)
    if new_arrival_paths:
        new_subject = {"id": "new-arrivals", "name": "New arrivals"}
        subjects.append(new_subject)
        for path in new_arrival_paths:
            record = metadata.get(path, {})
            file = _file_record(root, path, record)
            work_id = "local-" + hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
            material_type = "paper" if path.startswith("papers/") else "book"
            title = str(record.get("title") or _display_title(path))
            authors = _metadata_authors(record)
            edition = str(record.get("edition") or record.get("version") or "New arrival")
            works.append(
                {
                    "id": work_id,
                    "title": title,
                    "authors": authors,
                    "edition": edition,
                    "subject": new_subject["name"],
                    "subjectId": new_subject["id"],
                    "localPath": path,
                    "sourceUrl": file["sourceUrl"],
                    "access": "Local file awaiting catalog details",
                    "files": [file],
                    "fileCount": 1,
                    "totalBytes": int(file["bytes"]),
                    "formats": [file["format"]],
                    "materialType": material_type,
                    "materialLabel": MATERIAL_LABELS[material_type],
                    "isCollection": False,
                    "isAvailable": True,
                    "availableFileCount": 1,
                    "cataloged": False,
                }
            )

    materials: list[dict[str, Any]] = []
    for work in works:
        for file in work["files"]:
            if not file["exists"]:
                continue
            materials.append(
                {
                    **file,
                    "id": f"{work['id']}::{file['path']}",
                    "workId": work["id"],
                    "workTitle": work["title"],
                    "authors": work["authors"],
                    "edition": work["edition"],
                    "subject": work["subject"],
                    "subjectId": work["subjectId"],
                    "sourceUrl": work["sourceUrl"] or file["sourceUrl"],
                    "access": work["access"],
                    "materialType": work["materialType"],
                    "materialLabel": work["materialLabel"],
                    "workCataloged": work["cataloged"],
                }
            )

    artifact_count = len(materials)
    indexed_count = sum(len(work["files"]) for work in works)
    present_count = artifact_count
    manifest_path = root / "manifests" / "library.sha256"
    manifest_count = (
        len(manifest_path.read_text(encoding="utf-8").splitlines())
        if manifest_path.exists()
        else 0
    )
    material_counts = {
        material_type: sum(
            1 for material in materials if material["materialType"] == material_type
        )
        for material_type in MATERIAL_LABELS
    }
    return {
        "name": "CS Library",
        "works": works,
        "materials": materials,
        "materialTypes": [
            {"id": material_type, "name": label, "count": material_counts[material_type]}
            for material_type, label in MATERIAL_LABELS.items()
        ],
        "subjects": subjects,
        "stats": {
            "works": len(works),
            "artifacts": artifact_count,
            "indexedArtifacts": indexed_count,
            "present": present_count,
            "subjects": len(subjects),
            "bytes": sum(int(material["bytes"]) for material in materials),
            "manifestEntries": manifest_count,
            "materialCounts": material_counts,
            "allPresent": indexed_count == present_count,
            "missing": indexed_count - present_count,
            "newArrivals": len(new_arrival_paths),
        },
        "builtAt": datetime.now(timezone.utc).isoformat(),
    }


def library_snapshot(root: Path) -> tuple[tuple[str, int, int], ...]:
    """Return a cheap filesystem fingerprint used by the live shelf watcher."""
    candidates: set[Path] = {root / "CATALOG.md", root / "manifests" / "library.sha256"}
    for relative in ALLOWED_DOCUMENTS:
        candidates.add(root / relative)
    metadata_root = root / "metadata"
    if metadata_root.is_dir():
        candidates.update(metadata_root.rglob("*.json"))
    for relative in _discover_payload_paths(root):
        candidates.add(root / relative)

    snapshot: list[tuple[str, int, int]] = []
    for candidate in sorted(candidates):
        try:
            stat = candidate.stat()
            relative = candidate.relative_to(root).as_posix()
        except (OSError, ValueError):
            continue
        snapshot.append((relative, stat.st_mtime_ns, stat.st_size))
    return tuple(snapshot)


def resolve_payload(root: Path, relative: str, allowed_paths: set[str] | frozenset[str]) -> Path:
    """Resolve a cataloged payload without permitting traversal or symlink escape."""
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("Invalid payload path")
    normalized = pure.as_posix()
    if normalized not in allowed_paths:
        raise ValueError("Payload is not cataloged")
    candidate = (root / normalized).resolve()
    resolved_root = root.resolve()
    if not candidate.is_relative_to(resolved_root) or not candidate.is_file():
        raise ValueError("Payload is unavailable")
    return candidate


def parse_byte_range(value: str, size: int) -> tuple[int, int]:
    """Parse one RFC 9110 byte range and return inclusive offsets."""
    match = RANGE_HEADER.fullmatch(value.strip())
    if not match or size < 1:
        raise ValueError("Invalid byte range")
    start_text, end_text = match.group("start"), match.group("end")
    if not start_text and not end_text:
        raise ValueError("Empty byte range")
    if not start_text:
        suffix = int(end_text)
        if suffix < 1:
            raise ValueError("Invalid suffix range")
        return max(0, size - suffix), size - 1
    start = int(start_text)
    end = int(end_text) if end_text else size - 1
    if start >= size or end < start:
        raise ValueError("Unsatisfiable byte range")
    return start, min(end, size - 1)


def _xml_name(element: ElementTree.Element) -> str:
    """Return an XML element's local name without depending on its namespace."""
    return element.tag.rsplit("}", 1)[-1]


def _xml_text(element: ElementTree.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _first_xml(root: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((element for element in root.iter() if _xml_name(element) == name), None)


def _epub_fallback_label(entry: str, index: int) -> str:
    stem = PurePosixPath(entry).stem.lower()
    special = {
        "cover": "Cover",
        "title": "Title page",
        "title_page": "Title page",
        "titlepage": "Title page",
        "nav": "Contents",
        "toc": "Contents",
        "notice": "Edition notes",
        "copyright": "Copyright",
    }
    if stem in special:
        return special[stem]
    page = re.fullmatch(r"page[_-]?(\d+)", stem)
    if page:
        return f"Page {int(page.group(1)) + 1}"
    cleaned = " ".join(word for word in re.split(r"[-_]+", stem) if word)
    if cleaned and not re.fullmatch(r"ch\d+", stem):
        return cleaned.title()
    return f"Section {index + 1}"


def normalize_epub_entry(value: str) -> str:
    """Normalize one EPUB-internal path while rejecting archive traversal."""
    if not value or "\x00" in value:
        raise ValueError("Invalid EPUB resource path")
    decoded = urllib.parse.unquote(value).replace("\\", "/")
    pure = PurePosixPath(decoded)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("Invalid EPUB resource path")
    normalized = posixpath.normpath(decoded)
    if normalized in {"", "."} or normalized.startswith("../"):
        raise ValueError("Invalid EPUB resource path")
    return normalized


def _epub_target(
    base_directory: str,
    href: str,
    *,
    current_entry: str = "",
) -> tuple[str, str]:
    """Resolve an EPUB href to an archive entry and optional fragment."""
    parsed = urllib.parse.urlsplit(href)
    if parsed.scheme or parsed.netloc:
        raise ValueError("External EPUB target")
    raw_path = urllib.parse.unquote(parsed.path).replace("\\", "/")
    if raw_path.startswith("/"):
        raise ValueError("Invalid EPUB target")
    joined = posixpath.join(base_directory, raw_path) if raw_path else current_entry
    return normalize_epub_entry(joined), urllib.parse.unquote(parsed.fragment)


def encode_epub_key(relative: str) -> str:
    return base64.urlsafe_b64encode(relative.encode("utf-8")).decode("ascii").rstrip("=")


def decode_epub_key(value: str) -> str:
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid EPUB key")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid EPUB key") from exc
    if encode_epub_key(decoded) != value:
        raise ValueError("Invalid EPUB key")
    return decoded


def _epub_url(book_key: str, entry: str, fragment: str = "") -> str:
    url = f"/epub/{book_key}/{urllib.parse.quote(entry, safe='/')}"
    if fragment:
        url += f"#{urllib.parse.quote(fragment, safe='-._~!$&\'()*+,;=:@/?')}"
    return url


def _epub_archive_entries(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries: dict[str, zipfile.ZipInfo] = {}
    total_size = 0
    for info in archive.infolist():
        if info.is_dir():
            continue
        if len(entries) >= EPUB_ENTRY_LIMIT:
            raise ValueError("EPUB contains too many resources")
        try:
            normalized = normalize_epub_entry(info.filename)
        except ValueError:
            raise ValueError("EPUB contains an unsafe resource path") from None
        if normalized in entries:
            raise ValueError(f"EPUB contains a duplicate resource: {normalized}")
        unix_mode = (info.external_attr >> 16) & 0o170000
        if unix_mode == 0o120000:
            raise ValueError(f"EPUB contains a symbolic link: {normalized}")
        if info.flag_bits & 0x1:
            raise ValueError(f"EPUB contains an encrypted resource: {normalized}")
        if PurePosixPath(normalized).suffix.lower() in EPUB_ACTIVE_SUFFIXES:
            raise ValueError(f"EPUB contains unsupported active content: {normalized}")
        total_size += info.file_size
        if total_size > EPUB_TOTAL_LIMIT:
            raise ValueError("EPUB expands beyond the safe size limit")
        ratio = info.file_size / max(info.compress_size, 1)
        if info.file_size > EPUB_XML_LIMIT and ratio > EPUB_COMPRESSION_RATIO_LIMIT:
            raise ValueError(f"EPUB resource has an unsafe compression ratio: {normalized}")
        entries[normalized] = info
    return entries


def _read_epub_xml(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    name: str,
) -> ElementTree.Element:
    info = entries.get(name)
    if info is None or info.file_size > EPUB_XML_LIMIT or info.flag_bits & 0x1:
        raise ValueError(f"EPUB metadata resource is unavailable: {name}")
    try:
        return ElementTree.fromstring(archive.read(info))
    except (ElementTree.ParseError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid EPUB XML resource: {name}") from exc


def _epub_nav_items(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    nav_entry: str,
) -> list[dict[str, Any]]:
    root = _read_epub_xml(archive, entries, nav_entry)
    toc_nav = None
    for candidate in root.iter():
        if _xml_name(candidate) != "nav":
            continue
        nav_type = candidate.attrib.get(f"{{{EPUB_OPS_NAMESPACE}}}type", "")
        nav_type = nav_type or candidate.attrib.get("epub:type", "")
        if "toc" in nav_type.split() or candidate.attrib.get("role") == "doc-toc":
            toc_nav = candidate
            break
    if toc_nav is None:
        return []
    root_list = next((child for child in toc_nav.iter() if _xml_name(child) == "ol"), None)
    if root_list is None:
        return []

    nav_directory = posixpath.dirname(nav_entry)
    items: list[dict[str, Any]] = []

    def visit(ordered_list: ElementTree.Element, depth: int) -> None:
        for list_item in ordered_list:
            if _xml_name(list_item) != "li":
                continue
            anchor = next((child for child in list_item.iter() if _xml_name(child) == "a"), None)
            if anchor is not None and anchor.attrib.get("href"):
                try:
                    entry, fragment = _epub_target(
                        nav_directory,
                        anchor.attrib["href"],
                        current_entry=nav_entry,
                    )
                except ValueError:
                    entry, fragment = "", ""
                label = _xml_text(anchor)
                if entry in entries and label:
                    items.append(
                        {
                            "label": label,
                            "entry": entry,
                            "fragment": fragment,
                            "depth": min(depth, 5),
                        }
                    )
            for child in list_item:
                if _xml_name(child) == "ol":
                    visit(child, depth + 1)

    visit(root_list, 0)
    return items


def _epub_ncx_items(
    archive: zipfile.ZipFile,
    entries: dict[str, zipfile.ZipInfo],
    ncx_entry: str,
) -> list[dict[str, Any]]:
    root = _read_epub_xml(archive, entries, ncx_entry)
    ncx_directory = posixpath.dirname(ncx_entry)
    items: list[dict[str, Any]] = []

    def visit(parent: ElementTree.Element, depth: int) -> None:
        for point in parent:
            if _xml_name(point) != "navPoint":
                continue
            label_element = next(
                (element for element in point.iter() if _xml_name(element) == "navLabel"),
                None,
            )
            content = next(
                (element for element in point if _xml_name(element) == "content"),
                None,
            )
            if content is not None and content.attrib.get("src"):
                try:
                    entry, fragment = _epub_target(
                        ncx_directory,
                        content.attrib["src"],
                        current_entry=ncx_entry,
                    )
                except ValueError:
                    entry, fragment = "", ""
                label = _xml_text(label_element)
                if entry in entries and label:
                    items.append(
                        {
                            "label": label,
                            "entry": entry,
                            "fragment": fragment,
                            "depth": min(depth, 5),
                        }
                    )
            visit(point, depth + 1)

    nav_map = next((element for element in root.iter() if _xml_name(element) == "navMap"), None)
    if nav_map is not None:
        visit(nav_map, 0)
    return items


def parse_epub_package(path: Path, relative: str) -> tuple[dict[str, Any], dict[str, str]]:
    """Read EPUB package/navigation metadata without extracting the archive."""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("The EPUB archive is invalid") from exc

    with archive:
        entries = _epub_archive_entries(archive)
        container = _read_epub_xml(archive, entries, "META-INF/container.xml")
        rootfile = next(
            (
                element.attrib.get("full-path", "")
                for element in container.iter()
                if _xml_name(element) == "rootfile" and element.attrib.get("full-path")
            ),
            "",
        )
        try:
            opf_entry = normalize_epub_entry(rootfile)
        except ValueError as exc:
            raise ValueError("The EPUB package document is missing") from exc
        package_root = _read_epub_xml(archive, entries, opf_entry)
        opf_directory = posixpath.dirname(opf_entry)

        metadata_element = _first_xml(package_root, "metadata")
        title = ""
        creators: list[str] = []
        language = ""
        cover_id = ""
        if metadata_element is not None:
            for element in metadata_element:
                name = _xml_name(element)
                if name == "title" and not title:
                    title = _xml_text(element)
                elif name == "creator" and _xml_text(element):
                    creators.append(_xml_text(element))
                elif name == "language" and not language:
                    language = _xml_text(element)
                elif name == "meta" and element.attrib.get("name") == "cover":
                    cover_id = element.attrib.get("content", "")

        manifest_element = _first_xml(package_root, "manifest")
        manifest: dict[str, dict[str, str]] = {}
        media_types: dict[str, str] = {}
        if manifest_element is not None:
            for element in manifest_element:
                if _xml_name(element) != "item" or not element.attrib.get("id"):
                    continue
                try:
                    entry, _fragment = _epub_target(opf_directory, element.attrib.get("href", ""))
                except ValueError:
                    continue
                if entry not in entries:
                    continue
                item = {
                    "id": element.attrib["id"],
                    "entry": entry,
                    "mediaType": element.attrib.get("media-type", ""),
                    "properties": element.attrib.get("properties", ""),
                }
                manifest[item["id"]] = item
                if item["mediaType"]:
                    media_types[entry] = item["mediaType"]

        spine_element = _first_xml(package_root, "spine")
        spine_entries: list[str] = []
        progression = "ltr"
        ncx_id = ""
        if spine_element is not None:
            progression = spine_element.attrib.get("page-progression-direction", "ltr")
            if progression not in {"ltr", "rtl"}:
                progression = "ltr"
            ncx_id = spine_element.attrib.get("toc", "")
            for element in spine_element:
                if _xml_name(element) != "itemref":
                    continue
                item = manifest.get(element.attrib.get("idref", ""))
                if not item or item["mediaType"] not in EPUB_DOCUMENT_TYPES:
                    continue
                if item["entry"] not in spine_entries:
                    spine_entries.append(item["entry"])
        if not spine_entries:
            spine_entries = [
                item["entry"]
                for item in manifest.values()
                if item["mediaType"] in EPUB_DOCUMENT_TYPES
            ]
        if not spine_entries:
            raise ValueError("The EPUB has no readable spine")

        nav_item = next(
            (item for item in manifest.values() if "nav" in item["properties"].split()),
            None,
        )
        toc = _epub_nav_items(archive, entries, nav_item["entry"]) if nav_item else []
        if not toc:
            ncx_item = manifest.get(ncx_id) or next(
                (item for item in manifest.values() if item["mediaType"] == "application/x-dtbncx+xml"),
                None,
            )
            if ncx_item:
                toc = _epub_ncx_items(archive, entries, ncx_item["entry"])

        spine_index = {entry: index for index, entry in enumerate(spine_entries)}
        labels: dict[str, str] = {}
        for item in toc:
            item["spineIndex"] = spine_index.get(item["entry"], -1)
            labels.setdefault(item["entry"], item["label"])

        book_key = encode_epub_key(relative)
        chapters = [
            {
                "index": index,
                "label": labels.get(entry) or _epub_fallback_label(entry, index),
                "entry": entry,
                "url": _epub_url(book_key, entry),
            }
            for index, entry in enumerate(spine_entries)
        ]
        for item in toc:
            item["url"] = _epub_url(book_key, item["entry"], item["fragment"])

        cover_item = next(
            (item for item in manifest.values() if "cover-image" in item["properties"].split()),
            manifest.get(cover_id),
        )
        package = {
            "path": relative,
            "bookKey": book_key,
            "title": title or path.stem,
            "authors": creators,
            "language": language,
            "progression": progression,
            "coverUrl": _epub_url(book_key, cover_item["entry"]) if cover_item else "",
            "chapters": chapters,
            "toc": toc,
        }
        return package, media_types


class LibraryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        root: Path = REPO_ROOT,
        *,
        ui_root: Path | None = None,
        parent_pid: int | None = None,
    ):
        self.root = root.resolve()
        default_ui = self.root / "ui" if (self.root / "ui" / "index.html").is_file() else UI_ROOT
        self.ui_root = (ui_root or default_ui).resolve()
        if not (self.root / "CATALOG.md").is_file() or not (self.root / "metadata").is_dir():
            raise ValueError(f"Not a CS Library root: {self.root}")
        if not (self.ui_root / "index.html").is_file():
            raise ValueError(f"CS Library UI is missing: {self.ui_root}")
        self.library_id = library_identity(self.root)
        self.parent_pid = parent_pid
        self.library = build_library(self.root)
        self.allowed_paths = frozenset(file["path"] for file in self.library["materials"])
        self._epub_cache: dict[
            str,
            tuple[tuple[int, int], dict[str, Any], dict[str, str]],
        ] = {}
        self._epub_lock = threading.RLock()
        self.action_token = secrets.token_urlsafe(32)
        self.revision = 1
        self.last_change = {
            "revision": self.revision,
            "added": [],
            "removed": [],
            "updated": [],
            "at": self.library["builtAt"],
        }
        self.last_refresh_error = ""
        self._snapshot = library_snapshot(self.root)
        self._state_condition = threading.Condition(threading.RLock())
        self._watcher_stop = threading.Event()
        super().__init__(address, LibraryRequestHandler)
        self._watcher = threading.Thread(
            target=self._watch_library,
            name="cs-library-watcher",
            daemon=True,
        )
        self._watcher.start()
        self._parent_watcher: threading.Thread | None = None
        if parent_pid is not None:
            self._parent_watcher = threading.Thread(
                target=self._watch_parent,
                name="cs-library-parent-watcher",
                daemon=True,
            )
            self._parent_watcher.start()

    def epub_package(
        self,
        relative: str,
    ) -> tuple[dict[str, Any], dict[str, str], Path]:
        path = resolve_payload(self.root, relative, self.allowed_paths)
        if path.suffix.lower() != ".epub":
            raise ValueError("The requested file is not an EPUB")
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        with self._epub_lock:
            cached = self._epub_cache.get(relative)
            if cached and cached[0] == signature:
                return cached[1], cached[2], path
        package, media_types = parse_epub_package(path, relative)
        with self._epub_lock:
            self._epub_cache[relative] = (signature, package, media_types)
        return package, media_types, path

    def library_payload(self) -> dict[str, Any]:
        with self._state_condition:
            payload = dict(self.library)
            payload["actionToken"] = self.action_token
            payload["revision"] = self.revision
            payload["change"] = dict(self.last_change)
            return payload

    def health_payload(self) -> dict[str, Any]:
        with self._state_condition:
            return {
                "app": "cs-library",
                "protocolVersion": PROTOCOL_VERSION,
                "libraryId": self.library_id,
                "root": str(self.root),
                "status": "ok",
                "revision": self.revision,
                "watching": not self._watcher_stop.is_set(),
                "refreshError": self.last_refresh_error,
            }

    def _watch_parent(self) -> None:
        assert self.parent_pid is not None
        while not self._watcher_stop.wait(1.0):
            try:
                os.kill(self.parent_pid, 0)
            except ProcessLookupError:
                threading.Thread(target=self.shutdown, daemon=True).start()
                return
            except PermissionError:
                continue

    def wait_for_revision(self, revision: int, timeout: float) -> tuple[int, dict[str, Any]]:
        with self._state_condition:
            if self.revision <= revision and not self._watcher_stop.is_set():
                self._state_condition.wait(timeout)
            return self.revision, dict(self.last_change)

    def _watch_library(self) -> None:
        while not self._watcher_stop.wait(WATCH_INTERVAL_SECONDS):
            snapshot = library_snapshot(self.root)
            if snapshot == self._snapshot:
                continue
            try:
                refreshed = build_library(self.root)
            except (OSError, ValueError) as exc:
                with self._state_condition:
                    self.last_refresh_error = str(exc)
                continue

            with self._state_condition:
                previous = {item["path"]: item for item in self.library["materials"]}
                current = {item["path"]: item for item in refreshed["materials"]}
                self.revision += 1
                updated = sorted(
                    path
                    for path in previous.keys() & current.keys()
                    if (
                        previous[path].get("bytes"),
                        previous[path].get("modifiedNs"),
                    )
                    != (current[path].get("bytes"), current[path].get("modifiedNs"))
                )
                self.library = refreshed
                self.allowed_paths = frozenset(current)
                self.last_change = {
                    "revision": self.revision,
                    "added": sorted(current.keys() - previous.keys()),
                    "removed": sorted(previous.keys() - current.keys()),
                    "updated": updated,
                    "at": refreshed["builtAt"],
                }
                self.last_refresh_error = ""
                self._snapshot = snapshot
                self._state_condition.notify_all()

    def server_close(self) -> None:
        self._watcher_stop.set()
        with self._state_condition:
            self._state_condition.notify_all()
        super().server_close()
        if self._watcher.is_alive() and threading.current_thread() is not self._watcher:
            self._watcher.join(timeout=2)
        if self._parent_watcher and self._parent_watcher.is_alive() and threading.current_thread() is not self._parent_watcher:
            self._parent_watcher.join(timeout=2)

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Ignore routine disconnects from closed tabs and native app windows."""
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


class LibraryRequestHandler(BaseHTTPRequestHandler):
    server: LibraryHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "CSLibrary/1.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]").lower()
        return host in LOOPBACK_HOSTS

    def _security_headers(self, *, frame_policy: str = "DENY") -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", frame_policy)

    def _send_bytes(
        self,
        status: HTTPStatus,
        payload: bytes,
        content_type: str,
        *,
        cache: str = "no-store",
        head_only: bool = False,
        page_policy: bool = False,
    ) -> None:
        self.send_response(status)
        self._security_headers()
        if page_policy:
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
            )
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def _send_json(self, status: HTTPStatus, value: Any, *, head_only: bool = False) -> None:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(
            status,
            payload,
            "application/json; charset=utf-8",
            head_only=head_only,
            page_policy=True,
        )

    def _reject_bad_host(self) -> bool:
        if self._valid_host():
            return False
        self._send_json(HTTPStatus.FORBIDDEN, {"error": "Loopback host required"})
        return True

    def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._route_get(head_only=True)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._route_get(head_only=False)

    def _route_get(self, *, head_only: bool) -> None:
        if self._reject_bad_host():
            return
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                self.server.health_payload(),
                head_only=head_only,
            )
            return
        if request_path == "/api/library":
            self._send_json(HTTPStatus.OK, self.server.library_payload(), head_only=head_only)
            return
        if request_path == "/api/epub":
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            relative = query.get("path", [""])[0]
            try:
                package, _media_types, _path = self.server.epub_package(relative)
            except (OSError, ValueError, zipfile.BadZipFile) as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._send_json(HTTPStatus.OK, package, head_only=head_only)
            return
        if request_path == "/api/events":
            if head_only:
                self._send_bytes(HTTPStatus.OK, b"", "text/event-stream", head_only=True)
            else:
                self._serve_events()
            return
        if request_path.startswith("/content/"):
            self._serve_payload(request_path.removeprefix("/content/"), head_only=head_only)
            return
        if request_path.startswith("/epub/"):
            self._serve_epub_resource(request_path.removeprefix("/epub/"), head_only=head_only)
            return
        if request_path.startswith("/document/"):
            name = urllib.parse.unquote(request_path.removeprefix("/document/"))
            if name not in ALLOWED_DOCUMENTS:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Document not found"})
                return
            path = self.server.root / name
            if not path.is_file():
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Document not found"})
                return
            content_type = (
                "text/plain; charset=utf-8"
                if path.suffix.lower() == ".sha256"
                else "text/markdown; charset=utf-8"
            )
            self._send_bytes(
                HTTPStatus.OK,
                path.read_bytes(),
                content_type,
                head_only=head_only,
                page_policy=True,
            )
            return

        static_files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        if request_path == "/favicon.ico":
            self._send_bytes(HTTPStatus.NO_CONTENT, b"", "image/x-icon", head_only=head_only)
            return
        static = static_files.get(request_path)
        if static:
            filename, content_type = static
            self._send_bytes(
                HTTPStatus.OK,
                (self.server.ui_root / filename).read_bytes(),
                content_type,
                cache="no-cache",
                head_only=head_only,
                page_policy=True,
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def _serve_events(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        once = query.get("once") == ["1"]
        try:
            last_revision = int(self.headers.get("Last-Event-ID", "0") or 0)
        except ValueError:
            last_revision = 0
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "close" if once else "keep-alive")
        self.end_headers()

        def emit(event: str, revision: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            message = f"id: {revision}\nevent: {event}\ndata: {body}\n\n".encode("utf-8")
            self.wfile.write(message)
            self.wfile.flush()

        try:
            revision, _change = self.server.wait_for_revision(last_revision, 0)
            emit("library-ready", revision, {"revision": revision})
            if once:
                self.close_connection = True
                return
            last_revision = revision
            while not self.server._watcher_stop.is_set():
                revision, change = self.server.wait_for_revision(last_revision, 15)
                if revision > last_revision:
                    emit("library-changed", revision, change)
                    last_revision = revision
                else:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _serve_payload(self, encoded_path: str, *, head_only: bool) -> None:
        try:
            relative = urllib.parse.unquote(encoded_path)
            path = resolve_payload(self.server.root, relative, self.server.allowed_paths)
        except ValueError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return

        size = path.stat().st_size
        start, end, status = 0, size - 1, HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header:
            try:
                start, end = parse_byte_range(range_header, size)
                status = HTTPStatus.PARTIAL_CONTENT
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self._security_headers()
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix.lower() == ".epub":
            content_type = "application/epub+zip"
        elif path.suffix.lower() == ".tgz":
            content_type = "application/gzip"
        content_length = end - start + 1
        self.send_response(status)
        self._security_headers(frame_policy="SAMEORIGIN")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(content_length))
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if head_only:
            return
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = content_length
            while remaining:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _serve_epub_resource(self, route: str, *, head_only: bool) -> None:
        book_key, separator, encoded_entry = route.partition("/")
        try:
            if not separator:
                raise ValueError("EPUB resource not found")
            relative = decode_epub_key(book_key)
            entry = normalize_epub_entry(urllib.parse.unquote(encoded_entry))
            _package, media_types, path = self.server.epub_package(relative)
            if entry not in media_types:
                raise ValueError("EPUB resource is not declared by the package")
            archive = zipfile.ZipFile(path)
            try:
                info = archive.getinfo(entry)
            except KeyError:
                archive.close()
                raise ValueError("EPUB resource not found") from None
            if (
                normalize_epub_entry(info.filename) != entry
                or info.is_dir()
                or info.flag_bits & 0x1
                or info.file_size > EPUB_RESOURCE_LIMIT
            ):
                archive.close()
                raise ValueError("EPUB resource not found")
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return

        content_type = media_types.get(entry) or mimetypes.guess_type(entry)[0]
        content_type = content_type or "application/octet-stream"
        if content_type in EPUB_DOCUMENT_TYPES:
            content_type = "text/html; charset=utf-8"
        elif content_type == "text/css":
            content_type = "text/css; charset=utf-8"

        self.send_response(HTTPStatus.OK)
        self._security_headers(frame_policy="SAMEORIGIN")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'none'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self' data:; media-src 'self'; "
            "connect-src 'none'; frame-src 'none'; object-src 'none'; "
            "frame-ancestors 'self'; base-uri 'self'; form-action 'none'",
        )
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cache-Control", "private, max-age=3600")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(info.file_size))
        self.send_header("Content-Disposition", "inline")
        self.end_headers()
        if head_only:
            archive.close()
            return
        try:
            with archive, archive.open(info) as source:
                shutil.copyfileobj(source, self.wfile, length=1024 * 1024)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self._reject_bad_host():
            return
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path != "/api/action":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        if self.headers.get("X-Library-Token") != self.server.action_token:
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid action token"})
            return
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).hostname not in LOOPBACK_HOSTS:
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid origin"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 1 or length > 4096:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid request size"})
            return
        try:
            body = json.loads(self.rfile.read(length))
            relative = str(body.get("path", ""))
            action = str(body.get("action", ""))
            path = resolve_payload(self.server.root, relative, self.server.allowed_paths)
        except (json.JSONDecodeError, ValueError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        if action not in {"open", "reveal"}:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Unknown action"})
            return
        command = ["/usr/bin/open", str(path)]
        if action == "reveal":
            command = ["/usr/bin/open", "-R", str(path)]
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "action": action, "path": relative})


def find_running_library(port: int, expected_library_id: str | None = None) -> str | None:
    url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=0.4) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if payload.get("app") != "cs-library" or payload.get("protocolVersion") != PROTOCOL_VERSION:
        return None
    if expected_library_id is not None and payload.get("libraryId") != expected_library_id:
        return None
    return url


def create_server(
    port: int,
    root: Path = REPO_ROOT,
    *,
    ui_root: Path | None = None,
    parent_pid: int | None = None,
) -> LibraryHTTPServer:
    return LibraryHTTPServer(
        ("127.0.0.1", port),
        root=root,
        ui_root=ui_root,
        parent_pid=parent_pid,
    )


def run_server(
    port: int,
    *,
    root: Path = REPO_ROOT,
    ui_root: Path | None = None,
    parent_pid: int | None = None,
    open_browser: bool = True,
) -> int:
    candidates = [port] if port == 0 else list(range(port, min(port + 20, 65536)))
    expected_library_id = library_identity(root)
    for candidate in candidates:
        if candidate and (running_url := find_running_library(candidate, expected_library_id)):
            print(f"CS Library is already running at {running_url}")
            if open_browser:
                webbrowser.open(running_url)
            return 0

    server: LibraryHTTPServer | None = None
    for candidate in candidates:
        try:
            server = create_server(candidate, root=root, ui_root=ui_root, parent_pid=parent_pid)
            break
        except OSError:
            continue
    if server is None:
        print("Could not find an available local port for CS Library.", file=sys.stderr)
        return 1

    actual_port = int(server.server_address[1])
    url = f"http://127.0.0.1:{actual_port}"
    print(f"CS Library is ready: {url}")
    print("Your books stay on this Mac. Press Control-C to stop the library.")
    if open_browser:
        threading.Timer(0.25, webbrowser.open, args=(url,)).start()

    def stop_server(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="Preferred local port")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="CS Library content root")
    parser.add_argument("--ui-root", type=Path, default=None, help="Bundled UI resource directory")
    parser.add_argument("--parent-pid", type=int, default=None, help="Exit when this parent process exits")
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.port < 0 or args.port > 65535:
        print("Port must be between 0 and 65535.", file=sys.stderr)
        return 2
    if args.parent_pid is not None and args.parent_pid <= 1:
        print("Parent PID must be greater than 1.", file=sys.stderr)
        return 2
    try:
        return run_server(
            args.port,
            root=args.root,
            ui_root=args.ui_root,
            parent_pid=args.parent_pid,
            open_browser=not args.no_browser,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
