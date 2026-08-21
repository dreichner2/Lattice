#!/usr/bin/env python3
"""Serve the CS library as a private, local-only virtual bookshelf.

The server binds to loopback, derives its inventory from CATALOG.md and the
tracked metadata tree, and never uploads or copies a book. macOS file actions
are token-protected and restricted to cataloged payloads under books/ or
papers/.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import secrets
import signal
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Any


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
    suffix = payload.suffix.lower().lstrip(".") or "file"
    return {
        "title": metadata.get("title") or payload.stem,
        "path": path,
        "format": suffix.upper(),
        "bytes": metadata.get("bytes") or (payload.stat().st_size if payload.exists() else 0),
        "sha256": metadata.get("sha256") or "",
        "license": metadata.get("license") or "Not recorded",
        "sourceUrl": metadata.get("source_url") or metadata.get("page_url") or "",
        "fileUrl": metadata.get("file_url") or metadata.get("download_url") or "",
        "version": metadata.get("version") or metadata.get("edition") or "",
        "downloadedAt": metadata.get("downloaded_at") or "",
        "exists": payload.is_file(),
    }


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
    """Build the 47-work view from the authoritative Markdown catalog."""
    catalog_path = root / "CATALOG.md"
    metadata = _read_metadata(root)
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
            file_paths = sorted(path for path in metadata if path.startswith(local_path))
        else:
            file_paths = [local_path] if local_path in metadata else []
        if not file_paths:
            raise ValueError(f"Catalog work has no matching metadata: {work_id}")

        files = [_file_record(root, path, metadata[path]) for path in file_paths]
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
            }
        )

    linked_paths = {file["path"] for work in works for file in work["files"]}
    unlinked = sorted(set(metadata) - linked_paths)
    if unlinked:
        raise ValueError("Metadata is not reachable from the catalog: " + ", ".join(unlinked))

    materials: list[dict[str, Any]] = []
    for work in works:
        for file in work["files"]:
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
                }
            )

    artifact_count = len(materials)
    present_count = sum(
        1 for work in works for file in work["files"] if file["exists"]
    )
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
            "present": present_count,
            "subjects": len(subjects),
            "bytes": sum(work["totalBytes"] for work in works),
            "manifestEntries": manifest_count,
            "materialCounts": material_counts,
            "allPresent": artifact_count == present_count,
        },
        "builtAt": datetime.now(timezone.utc).isoformat(),
    }


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


class LibraryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], root: Path = REPO_ROOT):
        self.root = root.resolve()
        self.library = build_library(self.root)
        self.allowed_paths = frozenset(
            file["path"]
            for work in self.library["works"]
            for file in work["files"]
        )
        self.action_token = secrets.token_urlsafe(32)
        super().__init__(address, LibraryRequestHandler)


class LibraryRequestHandler(BaseHTTPRequestHandler):
    server: LibraryHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "CSLibrary/1.0"

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _valid_host(self) -> bool:
        host = self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]").lower()
        return host in LOOPBACK_HOSTS

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")

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
                "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
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
                {"app": "cs-library", "status": "ok"},
                head_only=head_only,
            )
            return
        if request_path == "/api/library":
            payload = dict(self.server.library)
            payload["actionToken"] = self.server.action_token
            self._send_json(HTTPStatus.OK, payload, head_only=head_only)
            return
        if request_path.startswith("/content/"):
            self._serve_payload(request_path.removeprefix("/content/"), head_only=head_only)
            return
        if request_path.startswith("/document/"):
            name = urllib.parse.unquote(request_path.removeprefix("/document/"))
            if name not in ALLOWED_DOCUMENTS:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Document not found"})
                return
            path = self.server.root / name
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
                (self.server.root / "ui" / filename).read_bytes(),
                content_type,
                cache="no-cache",
                head_only=head_only,
                page_policy=True,
            )
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

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
        self._security_headers()
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


def find_running_library(port: int) -> str | None:
    url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=0.4) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return url if payload.get("app") == "cs-library" else None


def create_server(port: int, root: Path = REPO_ROOT) -> LibraryHTTPServer:
    return LibraryHTTPServer(("127.0.0.1", port), root=root)


def run_server(port: int, *, open_browser: bool = True) -> int:
    candidates = [port] if port == 0 else list(range(port, min(port + 20, 65536)))
    for candidate in candidates:
        if candidate and (running_url := find_running_library(candidate)):
            print(f"CS Library is already running at {running_url}")
            if open_browser:
                webbrowser.open(running_url)
            return 0

    server: LibraryHTTPServer | None = None
    for candidate in candidates:
        try:
            server = create_server(candidate)
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
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.port < 0 or args.port > 65535:
        print("Port must be between 0 and 65535.", file=sys.stderr)
        return 2
    return run_server(args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
