#!/usr/bin/env python3
"""Run CS Library with a stable cross-platform state store and desktop helpers.

This wrapper preserves the existing local-only catalog server while adding:

* a versioned SQLite store for reader state, notes, bookmarks, and preferences;
* a stable library identity so desktop apps never attach to the wrong checkout;
* a parent-process watchdog so orphaned desktop servers exit automatically;
* static routes for the Windows PDF.js reading workspace; and
* export/import endpoints for all personal reading data.

The underlying catalog, EPUB parser, path validation, action token, CSP, and
loopback-only networking remain implemented by ``scripts/library_ui.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import signal
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import library_ui
except ModuleNotFoundError:  # Normal source-tree execution.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import library_ui  # type: ignore[no-redef]


PROTOCOL_VERSION = 2
MAX_STATE_BODY = 4 * 1024 * 1024
MAX_STATE_KEY = 1024
MAX_STATE_VALUE = 2 * 1024 * 1024
STATE_SCHEMA_VERSION = 1
WINDOWS_READER_ROOT = Path("windows") / "reader"


def library_identity(root: Path) -> str:
    """Return the identity shared by the macOS, Windows, and Python hosts."""
    canonical = root.resolve().as_posix().rstrip("/")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def default_state_database() -> Path:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "CS Library" / "reader-state.sqlite3"


class ReaderStateStore:
    """Small WAL-backed state database shared by both desktop applications."""

    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=8, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=8000")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._write_lock, self._connect() as connection:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS kv_state (
                    namespace TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (namespace, state_key)
                );
                CREATE INDEX IF NOT EXISTS kv_state_updated_idx
                    ON kv_state(updated_at DESC);
                CREATE TABLE IF NOT EXISTS reading_sessions (
                    id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL DEFAULT '',
                    material_path TEXT NOT NULL DEFAULT '',
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    active_seconds REAL NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                INSERT INTO schema_meta(key, value)
                VALUES ('schema_version', '1')
                ON CONFLICT(key) DO UPDATE SET value=excluded.value;
                COMMIT;
                """
            )

    @staticmethod
    def _validate(namespace: str, key: str, value: str) -> tuple[str, str, str]:
        namespace = str(namespace).strip()
        key = str(key).strip()
        value = str(value)
        if not namespace or len(namespace) > 128:
            raise ValueError("Invalid state namespace")
        if not key or len(key) > MAX_STATE_KEY:
            raise ValueError("Invalid state key")
        if len(value.encode("utf-8")) > MAX_STATE_VALUE:
            raise ValueError("State value is too large")
        return namespace, key, value

    def snapshot(self, namespace: str) -> dict[str, str]:
        namespace = str(namespace).strip()
        if not namespace or len(namespace) > 128:
            raise ValueError("Invalid state namespace")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT state_key, value FROM kv_state WHERE namespace=? ORDER BY state_key",
                (namespace,),
            ).fetchall()
        return {str(row["state_key"]): str(row["value"]) for row in rows}

    def set_value(self, namespace: str, key: str, value: str) -> None:
        namespace, key, value = self._validate(namespace, key, value)
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO kv_state(namespace, state_key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, state_key)
                DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (namespace, key, value, time.time()),
            )
            connection.execute("COMMIT")

    def delete_value(self, namespace: str, key: str) -> None:
        namespace = str(namespace).strip()
        key = str(key).strip()
        if not namespace or not key:
            raise ValueError("Invalid state key")
        with self._write_lock, self._connect() as connection:
            connection.execute(
                "DELETE FROM kv_state WHERE namespace=? AND state_key=?",
                (namespace, key),
            )

    def set_batch(self, namespace: str, values: dict[str, Any]) -> None:
        if not isinstance(values, dict) or len(values) > 5000:
            raise ValueError("Invalid state batch")
        rows = [self._validate(namespace, key, value) for key, value in values.items()]
        now = time.time()
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """
                INSERT INTO kv_state(namespace, state_key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, state_key)
                DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                [(item_namespace, key, value, now) for item_namespace, key, value in rows],
            )
            connection.execute("COMMIT")

    def export_payload(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT namespace, state_key, value, updated_at FROM kv_state "
                "ORDER BY namespace, state_key"
            ).fetchall()
            sessions = connection.execute(
                "SELECT * FROM reading_sessions ORDER BY started_at"
            ).fetchall()
        return {
            "application": "CS Library",
            "schemaVersion": STATE_SCHEMA_VERSION,
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "states": [dict(row) for row in rows],
            "readingSessions": [dict(row) for row in sessions],
        }

    def import_payload(self, payload: dict[str, Any], *, replace: bool = False) -> int:
        if not isinstance(payload, dict):
            raise ValueError("Invalid import payload")
        states = payload.get("states")
        if not isinstance(states, list) or len(states) > 100_000:
            raise ValueError("The import has no valid state records")
        prepared: list[tuple[str, str, str, float]] = []
        for record in states:
            if not isinstance(record, dict):
                raise ValueError("Invalid state record")
            namespace, key, value = self._validate(
                str(record.get("namespace", "")),
                str(record.get("state_key", record.get("key", ""))),
                str(record.get("value", "")),
            )
            prepared.append(
                (namespace, key, value, float(record.get("updated_at") or time.time()))
            )
        with self._write_lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if replace:
                connection.execute("DELETE FROM kv_state")
            connection.executemany(
                """
                INSERT INTO kv_state(namespace, state_key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, state_key)
                DO UPDATE SET
                    value=excluded.value,
                    updated_at=MAX(kv_state.updated_at, excluded.updated_at)
                """,
                prepared,
            )
            connection.execute("COMMIT")
        return len(prepared)


class CrossPlatformLibraryServer(library_ui.LibraryHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        *,
        root: Path,
        state_database: Path,
        parent_pid: int = 0,
    ):
        self.library_id = library_identity(root)
        self.instance_id = str(uuid.uuid4())
        self.protocol_version = PROTOCOL_VERSION
        self.state_store = ReaderStateStore(state_database)
        self.parent_pid = max(0, int(parent_pid))
        super().__init__(address, root=root)
        # LibraryHTTPServer intentionally defaults to the original handler.
        # Swapping the class after construction preserves all initialization.
        self.RequestHandlerClass = CrossPlatformRequestHandler
        self._parent_watchdog: threading.Thread | None = None
        if self.parent_pid:
            self._parent_watchdog = threading.Thread(
                target=self._watch_parent,
                name="cs-library-parent-watchdog",
                daemon=True,
            )
            self._parent_watchdog.start()

    def health_payload(self) -> dict[str, Any]:
        payload = super().health_payload()
        payload.update(
            {
                "protocolVersion": self.protocol_version,
                "libraryId": self.library_id,
                "instanceId": self.instance_id,
                "pid": os.getpid(),
            }
        )
        return payload

    def _watch_parent(self) -> None:
        while not self._watcher_stop.wait(2.0):
            if process_is_alive(self.parent_pid):
                continue
            threading.Thread(target=self.shutdown, daemon=True).start()
            return


class CrossPlatformRequestHandler(library_ui.LibraryRequestHandler):
    server: CrossPlatformLibraryServer

    def _token_valid(self) -> bool:
        return self.headers.get("X-Library-Token") == self.server.action_token

    def _origin_valid(self) -> bool:
        origin = self.headers.get("Origin")
        return not origin or urllib.parse.urlsplit(origin).hostname in library_ui.LOOPBACK_HOSTS

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 1 or length > MAX_STATE_BODY:
            raise ValueError("Invalid request size")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON request") from exc
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value

    def _require_state_access(self) -> bool:
        if not self._token_valid():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid action token"})
            return False
        if not self._origin_valid():
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid origin"})
            return False
        return True

    def _route_get(self, *, head_only: bool) -> None:
        if self._reject_bad_host():
            return
        parsed = urllib.parse.urlsplit(self.path)
        request_path = parsed.path
        if request_path == "/api/health":
            self._send_json(HTTPStatus.OK, self.server.health_payload(), head_only=head_only)
            return
        if request_path == "/api/state/snapshot":
            if not self._require_state_access():
                return
            namespace = urllib.parse.parse_qs(parsed.query).get("namespace", ["localStorage"])[0]
            try:
                values = self.server.state_store.snapshot(namespace)
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._send_json(
                HTTPStatus.OK,
                {"namespace": namespace, "values": values},
                head_only=head_only,
            )
            return
        if request_path == "/api/state/export":
            if not self._require_state_access():
                return
            self._send_json(
                HTTPStatus.OK,
                self.server.state_store.export_payload(),
                head_only=head_only,
            )
            return
        if request_path.startswith("/windows-reader/"):
            self._serve_windows_reader(
                request_path.removeprefix("/windows-reader/"),
                head_only=head_only,
            )
            return
        super()._route_get(head_only=head_only)

    def _serve_windows_reader(self, relative: str, *, head_only: bool) -> None:
        try:
            pure = PurePosixPath(urllib.parse.unquote(relative))
            if pure.is_absolute() or not pure.parts or any(
                part in {"", ".", ".."} for part in pure.parts
            ):
                raise ValueError("Reader resource not found")
            reader_root = (self.server.root / WINDOWS_READER_ROOT).resolve()
            path = (reader_root / pure.as_posix()).resolve()
            if not path.is_relative_to(reader_root) or not path.is_file():
                raise ValueError("Reader resource not found")
        except (OSError, ValueError):
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Reader resource not found"})
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix.lower() in {".mjs", ".js"}:
            content_type = "text/javascript; charset=utf-8"
        elif path.suffix.lower() == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix.lower() == ".html":
            content_type = "text/html; charset=utf-8"
        cache = "private, max-age=31536000, immutable" if "vendor" in pure.parts else "no-cache"
        payload = path.read_bytes()
        if path.suffix.lower() != ".html":
            self._send_bytes(
                HTTPStatus.OK,
                payload,
                content_type,
                cache=cache,
                head_only=head_only,
            )
            return
        self.send_response(HTTPStatus.OK)
        self._security_headers()
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
            "worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'none'",
        )
        self.send_header("Cache-Control", cache)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if not head_only:
            self.wfile.write(payload)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self._reject_bad_host():
            return
        request_path = urllib.parse.urlsplit(self.path).path
        if not request_path.startswith("/api/state/"):
            super().do_POST()
            return
        if not self._require_state_access():
            return
        try:
            body = self._read_json_body()
            if request_path == "/api/state/set":
                self.server.state_store.set_value(
                    str(body.get("namespace", "localStorage")),
                    str(body.get("key", "")),
                    str(body.get("value", "")),
                )
                result: dict[str, Any] = {"ok": True}
            elif request_path == "/api/state/delete":
                self.server.state_store.delete_value(
                    str(body.get("namespace", "localStorage")),
                    str(body.get("key", "")),
                )
                result = {"ok": True}
            elif request_path == "/api/state/batch":
                values = body.get("values")
                if not isinstance(values, dict):
                    raise ValueError("Invalid state batch")
                self.server.state_store.set_batch(
                    str(body.get("namespace", "localStorage")), values
                )
                result = {"ok": True, "count": len(values)}
            elif request_path == "/api/state/import":
                payload = body.get("payload")
                if not isinstance(payload, dict):
                    raise ValueError("Invalid import payload")
                count = self.server.state_store.import_payload(
                    payload,
                    replace=bool(body.get("replace", False)),
                )
                result = {"ok": True, "count": count}
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
                return
        except (OSError, sqlite3.Error, ValueError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._send_json(HTTPStatus.OK, result)


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
    try:
        import ctypes
        from ctypes import wintypes

        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        try:
            exit_code = wintypes.DWORD()
            if not ctypes.windll.kernel32.GetExitCodeProcess(process, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(process)
    except Exception:
        return True  # A watchdog failure must not terminate a healthy server.


def find_matching_server(port: int, expected_library_id: str) -> str | None:
    url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=0.45) as response:
            payload = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    if (
        payload.get("app") == "cs-library"
        and payload.get("libraryId") == expected_library_id
        and int(payload.get("protocolVersion") or 0) >= PROTOCOL_VERSION
    ):
        return url
    return None


def create_server(
    port: int,
    *,
    root: Path,
    state_database: Path,
    parent_pid: int = 0,
) -> CrossPlatformLibraryServer:
    return CrossPlatformLibraryServer(
        ("127.0.0.1", port),
        root=root,
        state_database=state_database,
        parent_pid=parent_pid,
    )


def run_server(
    port: int,
    *,
    root: Path,
    state_database: Path,
    parent_pid: int = 0,
    open_browser: bool = True,
) -> int:
    root = root.expanduser().resolve()
    if not (root / "CATALOG.md").is_file() or not (root / "ui" / "index.html").is_file():
        print(f"Not a CS Library folder: {root}", file=sys.stderr)
        return 2
    expected_id = library_identity(root)
    candidates = [port] if port == 0 else list(range(port, min(port + 20, 65536)))
    for candidate in candidates:
        if candidate and (running_url := find_matching_server(candidate, expected_id)):
            print(f"CS Library is already running at {running_url}")
            if open_browser:
                webbrowser.open(running_url)
            return 0

    server: CrossPlatformLibraryServer | None = None
    for candidate in candidates:
        try:
            server = create_server(
                candidate,
                root=root,
                state_database=state_database,
                parent_pid=parent_pid,
            )
            break
        except OSError:
            continue
    if server is None:
        print("Could not find an available local port for CS Library.", file=sys.stderr)
        return 1

    actual_port = int(server.server_address[1])
    url = f"http://127.0.0.1:{actual_port}"
    print(f"CS Library is ready: {url}")
    print(f"Library ID: {server.library_id}")
    print("Your books and reading data stay on this computer. Press Control-C to stop.")
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
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="CS Library folder")
    parser.add_argument("--port", type=int, default=8766, help="Preferred local port")
    parser.add_argument("--state-db", type=Path, default=default_state_database())
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--print-library-id", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.print_library_id:
        print(library_identity(args.root))
        return 0
    if args.port < 0 or args.port > 65535:
        print("Port must be between 0 and 65535.", file=sys.stderr)
        return 2
    return run_server(
        args.port,
        root=args.root,
        state_database=args.state_db,
        parent_pid=args.parent_pid,
        open_browser=not args.no_browser,
    )


if __name__ == "__main__":
    raise SystemExit(main())
