#!/usr/bin/env python3
"""Run Lattice with Windows desktop support and durable web-reader state.

The catalog, path validation, EPUB safety, and loopback HTTP boundary remain in
``library_ui``. This module adds a small SQLite mirror for the shared web UI,
Windows-safe open/reveal actions, and the lifecycle used by the packaged app.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from contextlib import closing
from datetime import datetime, timezone
from http import HTTPStatus
from pathlib import Path
from typing import Any

try:
    import library_ui
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import library_ui  # type: ignore[no-redef]


MAX_STATE_BODY = 4 * 1024 * 1024
MAX_STATE_KEY = 1024
MAX_STATE_VALUE = 2 * 1024 * 1024
MAX_STATE_BATCH = 5_000
PROTOCOL_VERSION = library_ui.PROTOCOL_VERSION
library_identity = library_ui.library_identity


def default_state_database() -> Path:
    """Return the platform-appropriate private reader-state path."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return base / "CS Library" / "WebReader.sqlite3"


class ReaderStateStore:
    """WAL-backed key/value storage for the existing web reader."""

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
        return connection

    def _initialize(self) -> None:
        with self._write_lock, closing(self._connect()) as connection:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS web_state (
                    library_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (library_id, namespace, state_key)
                );
                CREATE INDEX IF NOT EXISTS web_state_updated_idx
                    ON web_state(updated_at DESC);
                INSERT INTO schema_meta(key, value) VALUES ('schema_version', '1')
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

    def snapshot(self, library_id: str, namespace: str) -> dict[str, str]:
        namespace = str(namespace).strip()
        if not namespace or len(namespace) > 128:
            raise ValueError("Invalid state namespace")
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT state_key, value FROM web_state "
                "WHERE library_id=? AND namespace=? ORDER BY state_key",
                (library_id, namespace),
            ).fetchall()
        return {str(row["state_key"]): str(row["value"]) for row in rows}

    def set_value(
        self,
        library_id: str,
        namespace: str,
        key: str,
        value: str,
    ) -> None:
        namespace, key, value = self._validate(namespace, key, value)
        with self._write_lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO web_state(library_id, namespace, state_key, value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(library_id, namespace, state_key)
                DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (library_id, namespace, key, value, time.time()),
            )
            connection.execute("COMMIT")

    def delete_value(self, library_id: str, namespace: str, key: str) -> None:
        namespace, key, _value = self._validate(namespace, key, "")
        with self._write_lock, closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM web_state WHERE library_id=? AND namespace=? AND state_key=?",
                (library_id, namespace, key),
            )

    def set_batch(self, library_id: str, namespace: str, values: dict[str, Any]) -> None:
        if not isinstance(values, dict) or len(values) > MAX_STATE_BATCH:
            raise ValueError("Invalid state batch")
        rows = [self._validate(namespace, key, value) for key, value in values.items()]
        now = time.time()
        with self._write_lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executemany(
                """
                INSERT INTO web_state(library_id, namespace, state_key, value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(library_id, namespace, state_key)
                DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                [(library_id, item_namespace, key, value, now) for item_namespace, key, value in rows],
            )
            connection.execute("COMMIT")

    def export_payload(self, library_id: str) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT namespace, state_key, value, updated_at FROM web_state "
                "WHERE library_id=? ORDER BY namespace, state_key",
                (library_id,),
            ).fetchall()
        return {
            "application": "Lattice",
            "schemaVersion": 1,
            "libraryId": library_id,
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "states": [dict(row) for row in rows],
        }

    def import_payload(
        self,
        library_id: str,
        payload: dict[str, Any],
        *,
        replace: bool = False,
    ) -> int:
        states = payload.get("states") if isinstance(payload, dict) else None
        if not isinstance(states, list) or len(states) > 100_000:
            raise ValueError("The import has no valid state records")
        prepared: list[tuple[str, str, str, str, float]] = []
        for record in states:
            if not isinstance(record, dict):
                raise ValueError("Invalid state record")
            namespace, key, value = self._validate(
                str(record.get("namespace", "")),
                str(record.get("state_key", record.get("key", ""))),
                str(record.get("value", "")),
            )
            prepared.append(
                (library_id, namespace, key, value, float(record.get("updated_at") or time.time()))
            )
        with self._write_lock, closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            if replace:
                connection.execute("DELETE FROM web_state WHERE library_id=?", (library_id,))
            connection.executemany(
                """
                INSERT INTO web_state(library_id, namespace, state_key, value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(library_id, namespace, state_key)
                DO UPDATE SET value=excluded.value,
                    updated_at=MAX(web_state.updated_at, excluded.updated_at)
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
        ui_root: Path | None = None,
        state_database: Path,
        parent_pid: int | None = None,
    ):
        self.instance_id = str(uuid.uuid4())
        self.state_store = ReaderStateStore(state_database)
        super().__init__(address, root=root, ui_root=ui_root, parent_pid=parent_pid)
        self.RequestHandlerClass = CrossPlatformRequestHandler

    def health_payload(self) -> dict[str, Any]:
        payload = super().health_payload()
        payload.update({"instanceId": self.instance_id, "pid": os.getpid(), "platform": sys.platform})
        return payload


class CrossPlatformRequestHandler(library_ui.LibraryRequestHandler):
    server: CrossPlatformLibraryServer

    def _state_access_allowed(self) -> bool:
        if self.headers.get("X-Library-Token") != self.server.action_token:
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid action token"})
            return False
        origin = self.headers.get("Origin")
        if origin and urllib.parse.urlsplit(origin).hostname not in library_ui.LOOPBACK_HOSTS:
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "Invalid origin"})
            return False
        return True

    def _read_json_body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 1 or length > MAX_STATE_BODY:
            raise ValueError("Invalid request size")
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON request") from exc
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        return payload

    def _route_get(self, *, head_only: bool) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/state/snapshot":
            if self._reject_bad_host() or not self._state_access_allowed():
                return
            namespace = urllib.parse.parse_qs(parsed.query).get("namespace", ["localStorage"])[0]
            try:
                values = self.server.state_store.snapshot(self.server.library_id, namespace)
            except ValueError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}, head_only=head_only)
                return
            self._send_json(
                HTTPStatus.OK,
                {"namespace": namespace, "values": values},
                head_only=head_only,
            )
            return
        if parsed.path == "/api/state/export":
            if self._reject_bad_host() or not self._state_access_allowed():
                return
            self._send_json(
                HTTPStatus.OK,
                self.server.state_store.export_payload(self.server.library_id),
                head_only=head_only,
            )
            return
        super()._route_get(head_only=head_only)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self._reject_bad_host():
            return
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path == "/api/action" and os.name == "nt":
            self._windows_file_action()
            return
        if not request_path.startswith("/api/state/"):
            super().do_POST()
            return
        if not self._state_access_allowed():
            return
        try:
            body = self._read_json_body()
            namespace = str(body.get("namespace", "localStorage"))
            if request_path == "/api/state/set":
                self.server.state_store.set_value(
                    self.server.library_id,
                    namespace,
                    str(body.get("key", "")),
                    str(body.get("value", "")),
                )
                result: dict[str, Any] = {"ok": True}
            elif request_path == "/api/state/delete":
                self.server.state_store.delete_value(
                    self.server.library_id,
                    namespace,
                    str(body.get("key", "")),
                )
                result = {"ok": True}
            elif request_path == "/api/state/batch":
                values = body.get("values")
                if not isinstance(values, dict):
                    raise ValueError("Invalid state batch")
                self.server.state_store.set_batch(self.server.library_id, namespace, values)
                result = {"ok": True, "count": len(values)}
            elif request_path == "/api/state/import":
                payload = body.get("payload")
                if not isinstance(payload, dict):
                    raise ValueError("Invalid import payload")
                count = self.server.state_store.import_payload(
                    self.server.library_id,
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

    def _windows_file_action(self) -> None:
        if not self._state_access_allowed():
            return
        try:
            body = self._read_json_body()
            relative = str(body.get("path", ""))
            action = str(body.get("action", ""))
            path = library_ui.resolve_payload(
                self.server.root,
                relative,
                self.server.allowed_paths,
            )
            if action == "open":
                os.startfile(path)  # type: ignore[attr-defined]
            elif action == "reveal":
                subprocess.Popen(["explorer.exe", f"/select,{path}"], close_fds=True)
            else:
                raise ValueError("Unknown action")
        except (OSError, ValueError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "action": action, "path": relative})


def find_matching_server(port: int, expected_library_id: str) -> str | None:
    return library_ui.find_running_library(port, expected_library_id)


def create_server(
    port: int,
    *,
    root: Path,
    ui_root: Path | None = None,
    state_database: Path | None = None,
    parent_pid: int | None = None,
) -> CrossPlatformLibraryServer:
    return CrossPlatformLibraryServer(
        ("127.0.0.1", port),
        root=root,
        ui_root=ui_root,
        state_database=state_database or default_state_database(),
        parent_pid=parent_pid,
    )


def run_server(
    port: int,
    *,
    root: Path,
    ui_root: Path | None = None,
    state_database: Path | None = None,
    parent_pid: int | None = None,
    open_browser: bool = True,
    reuse_running: bool = True,
) -> int:
    root = root.expanduser().resolve()
    candidates = [port] if port == 0 else list(range(port, min(port + 20, 65536)))
    expected_library_id = library_ui.library_identity(root)
    # A desktop parent owns the child service lifetime. Never attach a second
    # app instance to a service that will exit when the first app closes.
    # A browser launch needs this process's private Study capability. Never
    # reuse an unrelated server whose per-launch capability is intentionally
    # unavailable to us.
    if reuse_running and parent_pid is None and not open_browser:
        for candidate in candidates:
            if candidate and (running_url := find_matching_server(candidate, expected_library_id)):
                print(f"Lattice is already running at {running_url}", flush=True)
                if open_browser:
                    webbrowser.open(running_url)
                return 0

    server: CrossPlatformLibraryServer | None = None
    for candidate in candidates:
        try:
            server = create_server(
                candidate,
                root=root,
                ui_root=ui_root,
                state_database=state_database,
                parent_pid=parent_pid,
            )
            break
        except OSError:
            continue
    if server is None:
        print("Could not find an available local port for Lattice.", file=sys.stderr, flush=True)
        return 1

    url = f"http://127.0.0.1:{int(server.server_address[1])}"
    launch_url = f"{url}#access={server.private_token}" if open_browser else url
    print(f"Lattice is ready: {url}", flush=True)
    print(f"Library ID: {server.library_id}", flush=True)
    if open_browser:
        threading.Timer(0.25, webbrowser.open, args=(launch_url,)).start()

    def stop_server(_signum: int, _frame: Any) -> None:
        threading.Thread(target=server.shutdown, daemon=True).start()

    import signal

    signal.signal(signal.SIGTERM, stop_server)
    signal.signal(signal.SIGINT, stop_server)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Lattice folder")
    parser.add_argument("--ui-root", type=Path, default=None, help="Bundled UI directory")
    parser.add_argument("--port", type=int, default=8766, help="Preferred local port")
    parser.add_argument("--state-db", type=Path, default=default_state_database())
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--isolated",
        action="store_true",
        help="Own a new server process instead of reusing one",
    )
    parser.add_argument("--print-library-id", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.print_library_id:
        print(library_ui.library_identity(args.root))
        return 0
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
            state_database=args.state_db,
            parent_pid=args.parent_pid,
            open_browser=not args.no_browser,
            reuse_running=not args.isolated,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
