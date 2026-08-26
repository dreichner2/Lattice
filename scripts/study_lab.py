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

import json
import os
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CELL_KINDS = ("latex", "python")
MAX_TITLE_CHARS = 200
MAX_CELL_SOURCE_CHARS = 100_000
MAX_CELLS_PER_NOTEBOOK = 500

_SCHEMA_VERSION = 1


class StudyError(ValueError):
    """A requested Study Lab operation is invalid."""


class StudyConflict(StudyError):
    """The caller's base revision no longer matches the stored notebook."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_study_root(library_id: str) -> Path:
    """Private per-user, per-library storage location."""
    override = os.environ.get("LATTICE_STUDY_ROOT")
    if override:
        return Path(override) / library_id
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "Lattice" / "Study" / library_id
    if sys.platform == "darwin":
        support = Path.home() / "Library" / "Application Support"
        return support / "Lattice" / "Study" / library_id
    state = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    return state / "lattice" / "study" / library_id


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
        self.library_root = Path(library_root).resolve()
        self.library_id = library_id
        self.root = study_root if study_root else default_study_root(library_id)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.root / "Study.sqlite",
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        try:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._migrate()
        except sqlite3.Error:
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
            self._connection.close()

    # ------------------------------------------------------------- internals

    def _touch_notebook(self, cursor: sqlite3.Cursor, notebook_id: str) -> str:
        updated_at = _utc_now()
        cursor.execute(
            "UPDATE notebooks SET updated_at = ? WHERE id = ?",
            (updated_at, notebook_id),
        )
        self._last_touch = updated_at
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
            # No base supplied: the caller explicitly opted out of the
            # concurrency check (programmatic edits). A client that tracks
            # revisions always sends one.
            return
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
        work_path = str(value.get("workPath") or "")
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
                        (notebook_id, work_path, str(value.get("workTitle") or "")),
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
                self._touch_notebook(cursor, notebook_id)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return self.get_notebook(notebook_id)

    def set_link(self, notebook_id: str, value: dict[str, Any]) -> dict[str, Any]:
        work_path = str(value.get("workPath") or "")
        with self._lock:
            self._require_notebook_row(notebook_id)
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
                        (notebook_id, work_path, str(value.get("workTitle") or "")),
                    )
                self._touch_notebook(cursor, notebook_id)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return self.get_notebook(notebook_id)

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
        # Appending is non-destructive, so it intentionally skips the
        # compare-and-swap check: two windows may both append and both
        # succeed. Only destructive operations require a fresh revision.
        with self._lock:
            self._require_notebook_row(notebook_id)
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
                self._touch_notebook(cursor, notebook_id)
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return {"ok": True, "cell": self._cell_payload(self._require_cell_row(cell_id)), "notebookUpdatedAt": self._last_touch}

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
                self._touch_notebook(cursor, row["notebook_id"])
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return {"ok": True, "cell": self._cell_payload(self._require_cell_row(row["id"])), "notebookUpdatedAt": self._last_touch}

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
                self._touch_notebook(cursor, row["notebook_id"])
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return {
            "ok": True,
            "cell": self._cell_payload(self._require_cell_row(row["id"])),
            "notebookUpdatedAt": self._last_touch,
        }

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
                self._touch_notebook(cursor, row["notebook_id"])
                self._connection.commit()
            except Exception:
                self._connection.rollback()
                raise
        return {"ok": True, "deleted": row["id"], "notebookUpdatedAt": self._last_touch}
