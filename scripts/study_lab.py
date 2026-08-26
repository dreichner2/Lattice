"""Study Lab persistence for Lattice.

Classic Jupyter-style notebooks with explicit cell kinds. Aidan's rule:
cells are ``latex`` or ``python`` only — there is no prose/text cell kind
and no automatic segmentation of mixed content.

Notebooks live in one SQLite database per library in the user's private
application-support area, never inside the synchronized library folder
(same posture as the Tutor cache and reader state).

Write discipline:

- every mutating call takes the caller's expected notebook ``updated_at``
  (compare-and-swap). A mismatch raises :class:`StudyConflict`, surfaced
  as HTTP 409 so two open editors cannot silently overwrite each other;
- all multi-statement writes run inside one transaction;
- sources are bounded so a runaway paste cannot wedge the service.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

CELL_KINDS = ("latex", "python")
MAX_TITLE_CHARS = 200
MAX_CELL_SOURCE_CHARS = 100_000
MAX_CELLS_PER_NOTEBOOK = 500
MAX_WORK_PATH_CHARS = 1_024
MAX_WORK_TITLE_CHARS = 300

_SCHEMA_VERSION = 1


class StudyError(ValueError):
    """A requested Study Lab operation is invalid."""


class StudyConflict(StudyError):
    """The caller's base revision no longer matches the stored notebook."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _storage_namespace(library_id: str) -> str:
    identity = str(library_id or "")
    if not identity or len(identity) > 4_096:
        raise StudyError("A valid library identity is required")
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def default_study_root(library_id: str) -> Path:
    """Private per-user, per-library storage location."""
    namespace = _storage_namespace(library_id)
    override = os.environ.get("LATTICE_STUDY_ROOT")
    if override:
        return Path(override) / namespace
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "Lattice" / "Study" / namespace
    if sys.platform == "darwin":
        support = Path.home() / "Library" / "Application Support"
        return support / "Lattice" / "Study" / namespace
    state = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state / "lattice" / "study" / namespace


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _is_reparse(stat_result: os.stat_result) -> bool:
    attributes = int(getattr(stat_result, "st_file_attributes", 0))
    return stat.S_ISLNK(stat_result.st_mode) or bool(attributes & 0x400)


def _require_plain_directory(path: Path) -> None:
    try:
        details = os.lstat(path)
    except FileNotFoundError as exc:
        raise StudyError("Study Lab storage disappeared during startup") from exc
    if _is_reparse(details) or not stat.S_ISDIR(details.st_mode):
        raise StudyError("Study Lab storage must be a regular, non-linked directory")


def _require_plain_file(path: Path) -> os.stat_result:
    try:
        details = os.lstat(path)
    except FileNotFoundError as exc:
        raise StudyError("Study Lab database disappeared during startup") from exc
    if _is_reparse(details) or not stat.S_ISREG(details.st_mode):
        raise StudyError("Study Lab database must be a regular, non-linked file")
    return details


def _validate_work_link(work_path_value: Any, work_title_value: Any) -> tuple[str, str]:
    work_path = str(work_path_value or "").strip()
    work_title = str(work_title_value or "").strip()
    if not work_path:
        return "", ""
    if len(work_path) > MAX_WORK_PATH_CHARS or "\\" in work_path:
        raise StudyError("Linked work path is invalid")
    normalized = PurePosixPath(work_path)
    if (
        normalized.is_absolute()
        or not normalized.parts
        or any(part in {"", ".", ".."} for part in normalized.parts)
        or normalized.as_posix() != work_path
    ):
        raise StudyError("Linked work path is invalid")
    if len(work_title) > MAX_WORK_TITLE_CHARS:
        raise StudyError(
            f"Linked work title exceeds {MAX_WORK_TITLE_CHARS} characters"
        )
    return work_path, work_title


def _validate_title(value: Any) -> str:
    title = str(value or "").strip()
    if not title or len(title) > MAX_TITLE_CHARS:
        raise StudyError("Notebook title must be 1-200 characters")
    return title


def _validate_kind(value: Any) -> str:
    kind = str(value or "")
    if kind not in CELL_KINDS:
        raise StudyError("Cell kind must be latex or python")
    return kind


def _validate_source(value: Any) -> str:
    source = value if isinstance(value, str) else ""
    if len(source) > MAX_CELL_SOURCE_CHARS:
        raise StudyError(
            f"Cell source exceeds {MAX_CELL_SOURCE_CHARS} characters"
        )
    return source


def _new_id() -> str:
    import secrets

    return secrets.token_urlsafe(12)


class StudyLab:
    """SQLite-backed notebook store for one library identity."""

    def __init__(self, library_root: Path, library_id: str, study_root: Path | None = None):
        self.library_root = Path(library_root).resolve(strict=True)
        self.library_id = str(library_id or "")
        _storage_namespace(self.library_id)
        requested_root = Path(study_root) if study_root else default_study_root(self.library_id)
        requested_root = Path(os.path.abspath(os.fspath(requested_root.expanduser())))
        if not requested_root.name or requested_root == Path(requested_root.anchor):
            raise StudyError("Study Lab storage root is unsafe")
        # Resolve the parent (including the conventional /tmp -> /private/tmp
        # indirection on macOS), but preserve the final component so an
        # attacker-controlled link at the database root is rejected, not
        # followed.
        self.root = requested_root.parent.resolve(strict=False) / requested_root.name
        if self.root == Path.home().resolve(strict=False):
            raise StudyError("Study Lab storage root is unsafe")
        resolved_candidate = self.root.resolve(strict=False)
        if (
            resolved_candidate == self.library_root
            or self.library_root in resolved_candidate.parents
        ):
            raise StudyError(
                "Study Lab storage must remain outside the synchronized library"
            )
        if _lexists(self.root):
            _require_plain_directory(self.root)
        else:
            self.root.mkdir(parents=True, mode=0o700, exist_ok=False)
            _require_plain_directory(self.root)
        if os.name != "nt":
            os.chmod(self.root, 0o700)

        self.database_path = self.root / "Study.sqlite"
        if _lexists(self.database_path):
            database_details = _require_plain_file(self.database_path)
        else:
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            flags |= int(getattr(os, "O_NOFOLLOW", 0))
            descriptor = os.open(self.database_path, flags, 0o600)
            os.close(descriptor)
            database_details = _require_plain_file(self.database_path)
        if os.name != "nt":
            os.chmod(self.database_path, 0o600)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(f"{self.database_path}{suffix}")
            if not _lexists(sidecar):
                continue
            _require_plain_file(sidecar)
            if os.name != "nt":
                os.chmod(sidecar, 0o600)

        self._lock = threading.RLock()
        self._closed = False
        self._connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
            timeout=5,
        )
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.execute("PRAGMA busy_timeout = 5000")
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            self._connection.execute("PRAGMA synchronous = FULL")
            self._migrate()
            connected_details = _require_plain_file(self.database_path)
            if (
                connected_details.st_dev,
                connected_details.st_ino,
            ) != (
                database_details.st_dev,
                database_details.st_ino,
            ):
                raise StudyError("Study Lab database changed during startup")
            if os.name != "nt":
                os.chmod(self.database_path, 0o600)
        except (OSError, sqlite3.Error, StudyError):
            self._connection.close()
            raise

    # ------------------------------------------------------------------ setup

    def _migrate(self) -> None:
        with self._lock:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            row = self._connection.execute(
                "SELECT value FROM meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None:
                self._connection.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                    (str(_SCHEMA_VERSION),),
                )
            elif int(row["value"]) != _SCHEMA_VERSION:
                raise StudyError(
                    f"Unsupported Study Lab schema version {row['value']}"
                )
            identity = self._connection.execute(
                "SELECT value FROM meta WHERE key = 'library_identity'"
            ).fetchone()
            if identity is None:
                self._connection.execute(
                    "INSERT INTO meta (key, value) VALUES ('library_identity', ?)",
                    (self.library_id,),
                )
            elif identity["value"] != self.library_id:
                raise StudyError("Study Lab database belongs to another library")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notebooks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cells (
                    id TEXT PRIMARY KEY,
                    notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('latex', 'python')),
                    source TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(notebook_id, position)
                )
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notebook_links (
                    notebook_id TEXT PRIMARY KEY REFERENCES notebooks(id) ON DELETE CASCADE,
                    work_path TEXT NOT NULL,
                    work_title TEXT NOT NULL DEFAULT ''
                )
                """
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._connection.close()
            self._closed = True
            for suffix in ("", "-wal", "-shm", "-journal"):
                path = Path(f"{self.database_path}{suffix}")
                if not _lexists(path):
                    continue
                _require_plain_file(path)
                if os.name != "nt":
                    os.chmod(path, 0o600)

    # ------------------------------------------------------------- internals

    def _touch_notebook(self, cursor: sqlite3.Cursor, notebook_id: str) -> str:
        row = cursor.execute(
            "SELECT updated_at FROM notebooks WHERE id = ?",
            (notebook_id,),
        ).fetchone()
        if row is None:
            raise StudyError("Notebook not found")
        now = datetime.now(timezone.utc)
        try:
            previous = datetime.fromisoformat(str(row["updated_at"]))
        except ValueError as exc:
            raise StudyError("Notebook revision is invalid") from exc
        if now <= previous:
            now = previous + timedelta(microseconds=1)
        updated_at = now.isoformat()
        cursor.execute(
            "UPDATE notebooks SET updated_at = ? WHERE id = ?",
            (updated_at, notebook_id),
        )
        return updated_at

    def _mutation_result(self, notebook_id: str, updated_at: str, **extra: Any) -> dict[str, Any]:
        """Every mutation returns the fresh revision token so callers can
        chain operations without refetching the whole notebook."""
        result: dict[str, Any] = {"ok": True, "notebookUpdatedAt": updated_at}
        result.update(extra)
        return result

    def _require_notebook_row(self, notebook_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM notebooks WHERE id = ?",
            (notebook_id,),
        ).fetchone()
        if row is None:
            raise StudyError("Notebook not found")
        return row

    def _require_cell_row(self, cell_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM cells WHERE id = ?",
            (cell_id,),
        ).fetchone()
        if row is None:
            raise StudyError("Cell not found")
        return row

    def _check_revision(self, notebook_id: str, base_updated_at: Any) -> None:
        """One revision token per notebook: its ``updated_at``.

        Every mutating call advances the token, so a stale copy from
        another window is rejected before it can destroy anything.
        """
        row = self._connection.execute(
            "SELECT updated_at FROM notebooks WHERE id = ?",
            (notebook_id,),
        ).fetchone()
        if row is None:
            raise StudyError("Notebook not found")
        supplied = str(base_updated_at or "")
        if not supplied:
            raise StudyConflict(
                "A fresh notebook revision is required. Reload to continue."
            )
        if supplied != row["updated_at"]:
            raise StudyConflict(
                "This notebook changed in another window. Reload to continue."
            )

    @staticmethod
    def _cell_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "notebookId": row["notebook_id"],
            "position": row["position"],
            "kind": row["kind"],
            "source": row["source"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    @staticmethod
    def _notebook_payload(row: sqlite3.Row, link: sqlite3.Row | None, cell_count: int) -> dict[str, Any]:
        payload = {
            "id": row["id"],
            "title": row["title"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "cellCount": cell_count,
            "workPath": link["work_path"] if link else "",
            "workTitle": link["work_title"] if link else "",
        }
        return payload

    def _link_for(self, notebook_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM notebook_links WHERE notebook_id = ?",
            (notebook_id,),
        ).fetchone()

    # ---------------------------------------------------------------- reading

    def list_notebooks(self) -> dict[str, Any]:
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT n.*,
                       (
                           SELECT COUNT(*) FROM cells c
                           WHERE c.notebook_id = n.id
                       ) AS cell_count
                FROM notebooks n
                ORDER BY n.updated_at DESC
                """
            ).fetchall()
            links = {
                row["notebook_id"]: row
                for row in self._connection.execute("SELECT * FROM notebook_links")
            }
            return {
                "notebooks": [
                    self._notebook_payload(row, links.get(row["id"]), int(row["cell_count"]))
                    for row in rows
                ]
            }

    def get_notebook(self, notebook_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._require_notebook_row(notebook_id)
            cells = self._connection.execute(
                "SELECT * FROM cells WHERE notebook_id = ? ORDER BY position",
                (notebook_id,),
            ).fetchall()
            return {
                "notebook": self._notebook_payload(
                    row,
                    self._link_for(notebook_id),
                    len(cells),
                ),
                "cells": [self._cell_payload(cell) for cell in cells],
            }

    # ---------------------------------------------------------------- writing

    def create_notebook(self, value: dict[str, Any]) -> dict[str, Any]:
        title = _validate_title(value.get("title"))
        work_path, work_title = _validate_work_link(
            value.get("workPath"),
            value.get("workTitle"),
        )
        now = _utc_now()
        notebook_id = _new_id()
        with self._lock:
            cursor = self._connection.cursor()
            try:
                cursor.execute(
                    "INSERT INTO notebooks (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (notebook_id, title, now, now),
                )
                if work_path:
                    cursor.execute(
                        """
                        INSERT INTO notebook_links (notebook_id, work_path, work_title)
                        VALUES (?, ?, ?)
                        """,
                        (notebook_id, work_path, work_title),
                    )
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return self.get_notebook(notebook_id)

    def rename_notebook(self, notebook_id: str, value: dict[str, Any]) -> dict[str, Any]:
        title = _validate_title(value.get("title"))
        with self._lock:
            self._require_notebook_row(notebook_id)
            self._check_revision(notebook_id, value.get("baseUpdatedAt"))
            cursor = self._connection.cursor()
            try:
                cursor.execute(
                    "UPDATE notebooks SET title = ? WHERE id = ?",
                    (title, notebook_id),
                )
                updated_at = self._touch_notebook(cursor, notebook_id)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        result = self.get_notebook(notebook_id)
        result.update(self._mutation_result(notebook_id, updated_at))
        return result

    def set_link(self, notebook_id: str, value: dict[str, Any]) -> dict[str, Any]:
        work_path, work_title = _validate_work_link(
            value.get("workPath"),
            value.get("workTitle"),
        )
        with self._lock:
            self._require_notebook_row(notebook_id)
            self._check_revision(notebook_id, value.get("baseUpdatedAt"))
            cursor = self._connection.cursor()
            try:
                cursor.execute(
                    "DELETE FROM notebook_links WHERE notebook_id = ?",
                    (notebook_id,),
                )
                if work_path:
                    cursor.execute(
                        """
                        INSERT INTO notebook_links (notebook_id, work_path, work_title)
                        VALUES (?, ?, ?)
                        """,
                        (notebook_id, work_path, work_title),
                    )
                updated_at = self._touch_notebook(cursor, notebook_id)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        result = self.get_notebook(notebook_id)
        result.update(self._mutation_result(notebook_id, updated_at))
        return result

    def delete_notebook(self, notebook_id: str, value: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self._require_notebook_row(notebook_id)
            self._check_revision(notebook_id, value.get("baseUpdatedAt"))
            cursor = self._connection.cursor()
            try:
                cursor.execute("DELETE FROM notebooks WHERE id = ?", (notebook_id,))
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return {"ok": True, "deleted": notebook_id}

    def add_cell(self, notebook_id: str, value: dict[str, Any]) -> dict[str, Any]:
        kind = _validate_kind(value.get("kind"))
        source = _validate_source(value.get("source"))
        with self._lock:
            self._require_notebook_row(notebook_id)
            self._check_revision(notebook_id, value.get("baseUpdatedAt"))
            count = int(
                self._connection.execute(
                    "SELECT COUNT(*) AS n FROM cells WHERE notebook_id = ?",
                    (notebook_id,),
                ).fetchone()["n"]
            )
            if count >= MAX_CELLS_PER_NOTEBOOK:
                raise StudyError(
                    f"A notebook holds at most {MAX_CELLS_PER_NOTEBOOK} cells"
                )
            now = _utc_now()
            cell_id = _new_id()
            cursor = self._connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO cells
                        (id, notebook_id, position, kind, source, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (cell_id, notebook_id, count, kind, source, now, now),
                )
                updated_at = self._touch_notebook(cursor, notebook_id)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            cell = self._cell_payload(self._require_cell_row(cell_id))
        return self._mutation_result(
            notebook_id,
            updated_at,
            cell=cell,
        )

    def update_cell(self, value: dict[str, Any]) -> dict[str, Any]:
        source = _validate_source(value.get("source"))
        with self._lock:
            row = self._require_cell_row(str(value.get("cellId") or ""))
            self._check_revision(row["notebook_id"], value.get("baseUpdatedAt"))
            cursor = self._connection.cursor()
            try:
                now = _utc_now()
                cursor.execute(
                    "UPDATE cells SET source = ?, updated_at = ? WHERE id = ?",
                    (source, now, row["id"]),
                )
                updated_at = self._touch_notebook(cursor, row["notebook_id"])
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            cell = self._cell_payload(self._require_cell_row(row["id"]))
        return self._mutation_result(
            row["notebook_id"],
            updated_at,
            cell=cell,
        )

    def move_cell(self, value: dict[str, Any]) -> dict[str, Any]:
        direction = str(value.get("direction") or "")
        if direction not in {"up", "down"}:
            raise StudyError("Direction must be up or down")
        with self._lock:
            row = self._require_cell_row(str(value.get("cellId") or ""))
            self._check_revision(row["notebook_id"], value.get("baseUpdatedAt"))
            neighbor = self._connection.execute(
                """
                SELECT * FROM cells
                WHERE notebook_id = ?
                  AND position = ?
                """,
                (
                    row["notebook_id"],
                    row["position"] - 1 if direction == "up" else row["position"] + 1,
                ),
            ).fetchone()
            if neighbor is None:
                return {
                    "ok": True,
                    "unchanged": True,
                    "notebookUpdatedAt": str(
                        self._connection.execute(
                            "SELECT updated_at FROM notebooks WHERE id = ?",
                            (row["notebook_id"],),
                        ).fetchone()["updated_at"]
                    ),
                    "cell": self._cell_payload(row),
                }
            now = _utc_now()
            cursor = self._connection.cursor()
            try:
                cursor.execute(
                    "UPDATE cells SET position = -1 WHERE id = ?",
                    (row["id"],),
                )
                cursor.execute(
                    "UPDATE cells SET position = ? WHERE id = ?",
                    (row["position"], neighbor["id"]),
                )
                cursor.execute(
                    "UPDATE cells SET position = ?, updated_at = ? WHERE id = ?",
                    (neighbor["position"], now, row["id"]),
                )
                updated_at = self._touch_notebook(cursor, row["notebook_id"])
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
            cell = self._cell_payload(self._require_cell_row(row["id"]))
        return self._mutation_result(
            row["notebook_id"],
            updated_at,
            cell=cell,
        )

    def delete_cell(self, value: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            row = self._require_cell_row(str(value.get("cellId") or ""))
            self._check_revision(row["notebook_id"], value.get("baseUpdatedAt"))
            cursor = self._connection.cursor()
            try:
                cursor.execute("DELETE FROM cells WHERE id = ?", (row["id"],))
                cursor.execute(
                    """
                    UPDATE cells SET position = position - 1
                    WHERE notebook_id = ? AND position > ?
                    """,
                    (row["notebook_id"], row["position"]),
                )
                updated_at = self._touch_notebook(cursor, row["notebook_id"])
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return self._mutation_result(
            row["notebook_id"],
            updated_at,
            deleted=row["id"],
        )
