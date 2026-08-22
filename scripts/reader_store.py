#!/usr/bin/env python3
"""Durable, versioned reader data for every CS Library client.

The store is intentionally standard-library-only. It lives under the ignored
.library-cache directory, uses SQLite/WAL for crash-safe writes, and exposes a
small API consumed by the loopback server, the shared web UI, and native apps.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
MAX_JSON_BYTES = 8 * 1024 * 1024


def _json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("Reader data is too large")
    return encoded


def _decode(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def document_identifier(work_id: str, path: str, sha256: str = "") -> str:
    """Return a stable identity that survives a file rename when a hash exists."""
    identity = sha256.strip().lower() or hashlib.sha256(path.encode("utf-8")).hexdigest()
    safe_work = work_id.strip() or "local"
    return f"{safe_work}:{identity[:32]}"


@dataclass(frozen=True)
class ReaderDocument:
    document_id: str
    work_id: str
    path: str
    title: str
    format: str
    sha256: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "ReaderDocument":
        path = str(value.get("path") or "").strip()
        work_id = str(value.get("workId") or value.get("work_id") or "local").strip()
        sha256 = str(value.get("sha256") or "").strip()
        document_id = str(value.get("documentId") or value.get("document_id") or "").strip()
        if not document_id:
            document_id = document_identifier(work_id, path, sha256)
        if not path or not document_id:
            raise ValueError("Reader document requires an id and path")
        return cls(
            document_id=document_id,
            work_id=work_id,
            path=path,
            title=str(value.get("title") or value.get("workTitle") or Path(path).stem),
            format=str(value.get("format") or Path(path).suffix.lstrip(".")).upper(),
            sha256=sha256,
        )


class ReaderStore:
    """Thread-safe SQLite facade with short-lived per-operation connections."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.directory = self.root / ".library-cache"
        self.path = self.directory / "reader.sqlite3"
        self.backup_directory = self.directory / "backups"
        self._initialize_lock = threading.Lock()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._initialize_lock, self._connect() as connection:
            connection.executescript(
                """
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    work_id TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    format TEXT NOT NULL,
                    sha256 TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS documents_work_idx ON documents(work_id);
                CREATE INDEX IF NOT EXISTS documents_hash_idx ON documents(sha256);

                CREATE TABLE IF NOT EXISTS reader_state (
                    document_id TEXT PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
                    position_json TEXT NOT NULL DEFAULT '{}',
                    preferences_json TEXT NOT NULL DEFAULT '{}',
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS bookmarks (
                    bookmark_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    locator_json TEXT NOT NULL,
                    label TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS bookmarks_document_idx
                    ON bookmarks(document_id, created_at);

                CREATE TABLE IF NOT EXISTS annotations (
                    annotation_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL DEFAULT 'note',
                    locator_json TEXT NOT NULL DEFAULT '{}',
                    quote TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    color TEXT NOT NULL DEFAULT '',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS annotations_document_idx
                    ON annotations(document_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS reading_sessions (
                    session_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    started_at REAL NOT NULL,
                    ended_at REAL,
                    active_seconds REAL NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS sessions_document_idx
                    ON reading_sessions(document_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS key_values (
                    namespace TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(namespace, key)
                );
                COMMIT;
                """
            )
            current = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()
            if current is None:
                connection.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
            elif int(current["value"]) > SCHEMA_VERSION:
                raise RuntimeError("Reader database was created by a newer CS Library")

    def register_documents(self, materials: Iterable[dict[str, Any]]) -> None:
        now = time.time()
        documents = [ReaderDocument.from_mapping(material) for material in materials]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for document in documents:
                existing = connection.execute(
                    "SELECT document_id FROM documents WHERE path = ?",
                    (document.path,),
                ).fetchone()
                if existing and existing["document_id"] != document.document_id:
                    # A replaced edition receives a new identity. Cascading deletes avoid
                    # accidentally applying annotations to different bytes.
                    connection.execute(
                        "DELETE FROM documents WHERE document_id = ?",
                        (existing["document_id"],),
                    )
                connection.execute(
                    """
                    INSERT INTO documents(
                        document_id, work_id, path, title, format, sha256, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(document_id) DO UPDATE SET
                        work_id = excluded.work_id,
                        path = excluded.path,
                        title = excluded.title,
                        format = excluded.format,
                        sha256 = excluded.sha256,
                        updated_at = excluded.updated_at
                    """,
                    (
                        document.document_id,
                        document.work_id,
                        document.path,
                        document.title,
                        document.format,
                        document.sha256,
                        now,
                        now,
                    ),
                )
            connection.execute("COMMIT")

    def resolve_path(self, path: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE path = ?",
                (path,),
            ).fetchone()
        return dict(row) if row else None

    def document_snapshot(self, document_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            document = connection.execute(
                "SELECT * FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if document is None:
                raise KeyError("Unknown reader document")
            state = connection.execute(
                "SELECT * FROM reader_state WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            bookmarks = connection.execute(
                "SELECT * FROM bookmarks WHERE document_id = ? ORDER BY created_at",
                (document_id,),
            ).fetchall()
            annotations = connection.execute(
                "SELECT * FROM annotations WHERE document_id = ? ORDER BY updated_at DESC",
                (document_id,),
            ).fetchall()
        return {
            "document": dict(document),
            "position": _decode(state["position_json"], {}) if state else {},
            "preferences": _decode(state["preferences_json"], {}) if state else {},
            "updatedAt": float(state["updated_at"]) if state else 0,
            "bookmarks": [self._bookmark_from_row(row) for row in bookmarks],
            "annotations": [self._annotation_from_row(row) for row in annotations],
        }

    def save_document_snapshot(
        self,
        document: dict[str, Any],
        *,
        position: dict[str, Any] | None = None,
        preferences: dict[str, Any] | None = None,
        bookmarks: list[dict[str, Any]] | None = None,
        annotations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        reader_document = ReaderDocument.from_mapping(document)
        self.register_documents([document])
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT position_json, preferences_json FROM reader_state WHERE document_id = ?",
                (reader_document.document_id,),
            ).fetchone()
            next_position = position if position is not None else _decode(
                existing["position_json"] if existing else None, {}
            )
            next_preferences = preferences if preferences is not None else _decode(
                existing["preferences_json"] if existing else None, {}
            )
            connection.execute(
                """
                INSERT INTO reader_state(document_id, position_json, preferences_json, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    position_json = excluded.position_json,
                    preferences_json = excluded.preferences_json,
                    updated_at = excluded.updated_at
                """,
                (
                    reader_document.document_id,
                    _json(next_position),
                    _json(next_preferences),
                    now,
                ),
            )
            if bookmarks is not None:
                connection.execute(
                    "DELETE FROM bookmarks WHERE document_id = ?",
                    (reader_document.document_id,),
                )
                for value in bookmarks:
                    self._insert_bookmark(connection, reader_document.document_id, value, now)
            if annotations is not None:
                connection.execute(
                    "DELETE FROM annotations WHERE document_id = ?",
                    (reader_document.document_id,),
                )
                for value in annotations:
                    self._insert_annotation(connection, reader_document.document_id, value, now)
            connection.execute("COMMIT")
        return self.document_snapshot(reader_document.document_id)

    def upsert_annotation(self, document_id: str, value: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone() is None:
                raise KeyError("Unknown reader document")
            connection.execute("BEGIN IMMEDIATE")
            annotation_id = self._insert_annotation(connection, document_id, value, now)
            connection.execute("COMMIT")
            row = connection.execute(
                "SELECT * FROM annotations WHERE annotation_id = ?",
                (annotation_id,),
            ).fetchone()
        assert row is not None
        return self._annotation_from_row(row)

    def delete_annotation(self, document_id: str, annotation_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM annotations WHERE document_id = ? AND annotation_id = ?",
                (document_id, annotation_id),
            )
        return cursor.rowcount > 0

    def key_value(self, namespace: str, key: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value_json, updated_at FROM key_values WHERE namespace = ? AND key = ?",
                (namespace, key),
            ).fetchone()
        return {
            "value": _decode(row["value_json"], None) if row else None,
            "updatedAt": float(row["updated_at"]) if row else 0,
        }

    def set_key_value(self, namespace: str, key: str, value: Any) -> dict[str, Any]:
        if not namespace or not key or len(namespace) > 80 or len(key) > 160:
            raise ValueError("Invalid reader storage key")
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO key_values(namespace, key, value_json, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(namespace, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (namespace, key, _json(value), now),
            )
        return {"value": value, "updatedAt": now}

    def start_session(self, document_id: str, started_at: float | None = None) -> str:
        session_id = str(uuid.uuid4())
        timestamp = float(started_at or time.time())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO reading_sessions(session_id, document_id, started_at, active_seconds)
                VALUES(?, ?, ?, 0)
                """,
                (session_id, document_id, timestamp),
            )
        return session_id

    def finish_session(self, session_id: str, active_seconds: float) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE reading_sessions
                SET ended_at = ?, active_seconds = ?
                WHERE session_id = ?
                """,
                (time.time(), max(0.0, float(active_seconds)), session_id),
            )

    def notebook(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT annotations.*, documents.title, documents.path, documents.work_id
                FROM annotations
                JOIN documents USING(document_id)
                ORDER BY annotations.updated_at DESC
                """
            ).fetchall()
        output: list[dict[str, Any]] = []
        for row in rows:
            annotation = self._annotation_from_row(row)
            annotation.update(
                {
                    "title": row["title"],
                    "path": row["path"],
                    "workId": row["work_id"],
                }
            )
            output.append(annotation)
        return output

    def export(self, format_name: str = "json") -> tuple[bytes, str, str]:
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "exportedAt": time.time(),
            "annotations": self.notebook(),
        }
        if format_name == "markdown":
            lines = ["# CS Library Notebook", ""]
            for item in payload["annotations"]:
                lines.extend(
                    [
                        f"## {item['title']}",
                        "",
                        f"- Source: `{item['path']}`",
                        f"- Updated: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(item['updatedAt']))}",
                    ]
                )
                if item.get("quote"):
                    lines.extend(["", "> " + str(item["quote"]).replace("\n", "\n> ")])
                if item.get("note"):
                    lines.extend(["", str(item["note"])])
                lines.append("")
            return "\n".join(lines).encode("utf-8"), "text/markdown; charset=utf-8", "cs-library-notebook.md"
        return (
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json; charset=utf-8",
            "cs-library-notebook.json",
        )

    def backup(self) -> Path:
        self.backup_directory.mkdir(parents=True, exist_ok=True)
        destination = self.backup_directory / time.strftime("reader-%Y%m%d-%H%M%S.sqlite3")
        with self._connect() as source, sqlite3.connect(destination) as target:
            source.backup(target)
        backups = sorted(self.backup_directory.glob("reader-*.sqlite3"), reverse=True)
        for stale in backups[20:]:
            stale.unlink(missing_ok=True)
        return destination

    def _insert_bookmark(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        value: dict[str, Any],
        now: float,
    ) -> str:
        bookmark_id = str(value.get("id") or value.get("bookmarkId") or uuid.uuid4())
        created_at = float(value.get("createdAt") or now)
        connection.execute(
            """
            INSERT INTO bookmarks(
                bookmark_id, document_id, locator_json, label, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(bookmark_id) DO UPDATE SET
                locator_json = excluded.locator_json,
                label = excluded.label,
                updated_at = excluded.updated_at
            """,
            (
                bookmark_id,
                document_id,
                _json(value.get("locator") or {}),
                str(value.get("label") or ""),
                created_at,
                now,
            ),
        )
        return bookmark_id

    def _insert_annotation(
        self,
        connection: sqlite3.Connection,
        document_id: str,
        value: dict[str, Any],
        now: float,
    ) -> str:
        annotation_id = str(value.get("id") or value.get("annotationId") or uuid.uuid4())
        created_at = float(value.get("createdAt") or now)
        connection.execute(
            """
            INSERT INTO annotations(
                annotation_id, document_id, kind, locator_json, quote, note,
                color, tags_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(annotation_id) DO UPDATE SET
                kind = excluded.kind,
                locator_json = excluded.locator_json,
                quote = excluded.quote,
                note = excluded.note,
                color = excluded.color,
                tags_json = excluded.tags_json,
                updated_at = excluded.updated_at
            """,
            (
                annotation_id,
                document_id,
                str(value.get("kind") or "note"),
                _json(value.get("locator") or {}),
                str(value.get("quote") or ""),
                str(value.get("note") or ""),
                str(value.get("color") or ""),
                _json(value.get("tags") or []),
                created_at,
                now,
            ),
        )
        return annotation_id

    @staticmethod
    def _bookmark_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["bookmark_id"],
            "documentId": row["document_id"],
            "locator": _decode(row["locator_json"], {}),
            "label": row["label"],
            "createdAt": float(row["created_at"]),
            "updatedAt": float(row["updated_at"]),
        }

    @staticmethod
    def _annotation_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["annotation_id"],
            "documentId": row["document_id"],
            "kind": row["kind"],
            "locator": _decode(row["locator_json"], {}),
            "quote": row["quote"],
            "note": row["note"],
            "color": row["color"],
            "tags": _decode(row["tags_json"], []),
            "createdAt": float(row["created_at"]),
            "updatedAt": float(row["updated_at"]),
        }
