"""Crash-safe, per-device storage tiering for cataloged Lattice payloads.

The synchronized library remains the catalog of record. The vault stores only
verified payload copies in a private, library-specific device cache. Adjacent
metadata sidecars always remain in the synchronized library.

The operation order is intentionally conservative:

* check out copies and verifies the payload before journaling it;
* check in re-verifies both copies, journals ``return-pending``, installs an
  effective exact-path Syncthing ignore, and only then removes the payload;
* restore journals ``restore-pending``, creates the payload without replacing
  any unexpected local file, verifies it, and only then removes vault state.

Startup reconciliation completes or rolls back interrupted journal phases. A
malformed journal is never treated as empty and therefore can never authorize
orphan pruning.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SIDECAR_SUFFIX = ".library.json"
STATE_VERSION = 1
COPY_CHUNK_BYTES = 1024 * 1024
MAXIMUM_STATE_BYTES = 8 * 1024 * 1024
MAXIMUM_IGNORE_BYTES = 1024 * 1024

PHASE_LOCAL = "local"
PHASE_AWAY = "away"
PHASE_RETURN_PENDING = "return-pending"
PHASE_RESTORE_PENDING = "restore-pending"
VALID_PHASES = {
    PHASE_LOCAL,
    PHASE_AWAY,
    PHASE_RETURN_PENDING,
    PHASE_RESTORE_PENDING,
}

AVAILABILITY_LOCAL = "local"
AVAILABILITY_AWAY = "away"

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_MANAGED_COPY = re.compile(r"^vault-[0-9a-f]{64}-[0-9a-f]{64}(?:\.[A-Za-z0-9]{1,12})?$")
_SYNCTHING_GLOB_CHARACTERS = frozenset("*?[]{}\\|")


class VaultError(ValueError):
    """A requested vault operation cannot be performed safely."""


def default_vault_root() -> Path:
    """Return the base directory for per-library, per-device vaults."""
    override = os.environ.get("LATTICE_VAULT_ROOT")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
        return base / "Lattice" / "Vault"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Lattice" / "Vault"
    return Path.home() / ".local" / "state" / "lattice" / "vault"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(COPY_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_relative(relative: str) -> str:
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise VaultError("Invalid library payload path")
    normalized_input = relative.replace("\\", "/")
    pure = Path(normalized_input)
    parts = [part for part in pure.parts if part not in {"", "."}]
    if (
        pure.is_absolute()
        or not parts
        or ".." in parts
        or any(part.startswith(".") or part.strip() != part for part in parts)
        or ":" in normalized_input
        or any(character in _SYNCTHING_GLOB_CHARACTERS for character in normalized_input)
        or any(ord(character) < 32 for character in normalized_input)
    ):
        raise VaultError(
            "This payload path cannot be represented as an exact cross-platform Syncthing ignore"
        )
    return "/".join(parts)


def _fsync_directory(path: Path) -> None:
    """Persist directory-entry changes where the platform supports it."""
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


class BookVault:
    """Verified per-device checkout cache for one stable library identity."""

    def __init__(self, library_root: Path, library_id: str, vault_root: Path | None = None):
        if not isinstance(library_id, str) or not library_id or len(library_id) > 512:
            raise VaultError("Invalid library vault identity")
        self.library_root = Path(library_root).expanduser().resolve()
        self.library_id = library_id
        self.base_root = Path(vault_root or default_vault_root()).expanduser().resolve()
        namespace = hashlib.sha256(f"lattice-vault:{library_id}".encode("utf-8")).hexdigest()[:24]
        self.root = self.base_root / namespace
        if self.root.is_relative_to(self.library_root) or self.library_root.is_relative_to(
            self.root
        ):
            raise VaultError("The device vault must be outside the synchronized library")

    @property
    def state_path(self) -> Path:
        return self.root / "vault-state.json"

    def copy_path(self, copy_name: str) -> Path:
        safe = Path(copy_name)
        if (
            not copy_name
            or safe.is_absolute()
            or safe.parent != Path(".")
            or safe.name != copy_name
        ):
            raise VaultError("Invalid vault copy name")
        return self.root / copy_name

    def local_payload(self, relative: str) -> Path:
        candidate = (self.library_root / _validate_relative(relative)).resolve()
        if not candidate.is_relative_to(self.library_root):
            raise VaultError("Payload escapes the library root")
        return candidate

    def _empty_state(self) -> dict[str, Any]:
        return {"version": STATE_VERSION, "libraryId": self.library_id, "entries": {}}

    def _validate_entry(self, relative: str, entry: Any) -> None:
        if _validate_relative(relative) != relative or not isinstance(entry, dict):
            raise VaultError("The vault journal contains an invalid entry")
        if entry.get("phase") not in VALID_PHASES:
            raise VaultError(f"The vault journal has an invalid phase for {relative}")
        digest = entry.get("sha256")
        copy_name = entry.get("copyName")
        size = entry.get("bytes")
        if not isinstance(digest, str) or not _HEX_64.fullmatch(digest):
            raise VaultError(f"The vault journal has an invalid checksum for {relative}")
        if not isinstance(copy_name, str) or not _MANAGED_COPY.fullmatch(copy_name):
            raise VaultError(f"The vault journal has an invalid copy name for {relative}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise VaultError(f"The vault journal has an invalid size for {relative}")
        if "ignoreAdded" in entry and not isinstance(entry["ignoreAdded"], bool):
            raise VaultError(f"The vault journal has invalid ignore ownership for {relative}")

    def _validate_state(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise VaultError("The vault journal is not a JSON object")
        if raw.get("version") != STATE_VERSION:
            raise VaultError("The vault journal uses an unsupported version")
        if raw.get("libraryId") != self.library_id:
            raise VaultError("The vault journal belongs to a different library")
        entries = raw.get("entries")
        if not isinstance(entries, dict):
            raise VaultError("The vault journal entries are invalid")
        for relative, entry in entries.items():
            if not isinstance(relative, str):
                raise VaultError("The vault journal contains a non-text path")
            self._validate_entry(relative, entry)
        return raw

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.is_symlink():
            raise VaultError("The vault journal cannot be a symbolic link")
        try:
            size = self.state_path.stat().st_size
        except FileNotFoundError:
            return self._empty_state()
        except OSError as exc:
            raise VaultError(f"The vault journal cannot be inspected: {exc}") from exc
        if size <= 0 or size > MAXIMUM_STATE_BYTES:
            raise VaultError("The vault journal has an invalid size")
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VaultError("The vault journal is unreadable or malformed") from exc
        return self._validate_state(raw)

    def _ensure_private_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or not self.root.is_dir():
            raise VaultError("The vault root is not a private directory")
        try:
            self.root.chmod(0o700)
        except OSError:
            if os.name != "nt":
                raise

    def _write_state(self, state: dict[str, Any]) -> None:
        self._ensure_private_root()
        state["version"] = STATE_VERSION
        state["libraryId"] = self.library_id
        state["updatedAt"] = _utc_now()
        self._validate_state(state)
        temporary = self.root / f".vault-state.{os.urandom(6).hex()}.tmp"
        descriptor = -1
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
            try:
                self.state_path.chmod(0o600)
            except OSError:
                if os.name != "nt":
                    raise
            _fsync_directory(self.root)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    def _verified_copy_name(self, relative: str, digest: str, payload: Path) -> str:
        path_digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()
        suffix = payload.suffix.lower()
        if not re.fullmatch(r"(?:\.[A-Za-z0-9]{1,12})?", suffix):
            suffix = ""
        return f"vault-{path_digest}-{digest}{suffix}"

    def _stage_verified_copy(
        self,
        source: Path,
        expected_digest: str,
        relative: str,
    ) -> tuple[Path, int]:
        self._ensure_private_root()
        destination = self.copy_path(self._verified_copy_name(relative, expected_digest, source))
        temporary = self.root / f".staging.{os.urandom(6).hex()}.tmp"
        descriptor = -1
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
                descriptor = -1
                shutil.copyfileobj(reader, writer, COPY_CHUNK_BYTES)
                writer.flush()
                os.fsync(writer.fileno())
            if sha256_file(temporary) != expected_digest:
                raise VaultError("Staged vault copy failed verification")
            size = temporary.stat().st_size
            os.replace(temporary, destination)
            try:
                destination.chmod(0o600)
            except OSError:
                if os.name != "nt":
                    raise
            _fsync_directory(self.root)
            return destination, size
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    def _verify_copy(self, entry: dict[str, Any]) -> Path:
        copy_name = str(entry.get("copyName") or "")
        copy = self.copy_path(copy_name)
        try:
            details = copy.lstat()
        except FileNotFoundError as exc:
            raise VaultError(f"The vault copy is missing: {copy_name}") from exc
        if copy.is_symlink() or not stat.S_ISREG(details.st_mode):
            raise VaultError("The vault copy is not a regular file")
        if details.st_size != entry.get("bytes") or sha256_file(copy) != entry.get("sha256"):
            raise VaultError("The vault copy no longer matches the recorded checksum")
        return copy

    def _sidecar_digest(self, payload: Path) -> str | None:
        sidecar = payload.with_name(payload.name + SIDECAR_SUFFIX)
        if not sidecar.exists():
            return None
        if sidecar.is_symlink() or not sidecar.is_file():
            raise VaultError("The adjacent metadata sidecar is not a regular file")
        try:
            record = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VaultError("The adjacent metadata sidecar is unreadable or malformed") from exc
        value = record.get("sha256") if isinstance(record, dict) else None
        if not isinstance(value, str) or not _HEX_64.fullmatch(value):
            raise VaultError("The adjacent metadata sidecar has no valid payload checksum")
        return value

    def _verify_local_payload(self, payload: Path, expected_digest: str | None = None) -> str:
        try:
            details = payload.lstat()
        except FileNotFoundError as exc:
            raise VaultError("The local payload is unavailable") from exc
        if payload.is_symlink() or not stat.S_ISREG(details.st_mode):
            raise VaultError("The local payload is not a regular file")
        digest = sha256_file(payload)
        after = payload.lstat()
        before_identity = (details.st_dev, details.st_ino, details.st_size, details.st_mtime_ns)
        after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if before_identity != after_identity:
            raise VaultError("The local payload changed while it was being verified")
        if expected_digest is not None and digest != expected_digest:
            raise VaultError("The local payload changed after it was checked out")
        recorded = self._sidecar_digest(payload)
        if recorded is not None and recorded != digest:
            raise VaultError("The local payload no longer matches its metadata checksum")
        return digest

    def _ignore_marker(self, relative: str) -> str:
        return f"/{_validate_relative(relative)}"

    def _read_ignore_lines(self) -> list[str]:
        ignore_path = self.library_root / ".stignore"
        if ignore_path.is_symlink():
            raise VaultError(".stignore cannot be a symbolic link")
        try:
            details = ignore_path.stat()
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise VaultError(f".stignore cannot be inspected: {exc}") from exc
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAXIMUM_IGNORE_BYTES:
            raise VaultError(".stignore is not a bounded regular file")
        try:
            return ignore_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise VaultError(".stignore cannot be read as UTF-8") from exc

    def _write_ignore_lines(self, lines: list[str]) -> None:
        ignore_path = self.library_root / ".stignore"
        mode = 0o600
        try:
            mode = stat.S_IMODE(ignore_path.stat().st_mode)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise VaultError(f".stignore permissions cannot be inspected: {exc}") from exc
        temporary = ignore_path.with_name(f".stignore.{os.urandom(6).hex()}.tmp")
        descriptor = -1
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                descriptor = -1
                handle.write("\n".join(lines) + ("\n" if lines else ""))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, ignore_path)
            _fsync_directory(self.library_root)
        except OSError as exc:
            raise VaultError(f".stignore could not be updated safely: {exc}") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _ignore_insert_index(lines: list[str]) -> int:
        index = 0
        while index < len(lines):
            stripped = lines[index].strip()
            if not stripped or stripped.startswith("//") or stripped.startswith("#escape="):
                index += 1
                continue
            break
        return index

    def _has_ignore_marker(self, relative: str) -> bool:
        marker = self._ignore_marker(relative)
        return any(line.strip() == marker for line in self._read_ignore_lines())

    def _ensure_ignore(self, relative: str) -> bool:
        """Install the exact marker before every potentially matching pattern."""
        marker = self._ignore_marker(relative)
        lines = self._read_ignore_lines()
        existed = any(line.strip() == marker for line in lines)
        remaining = [line for line in lines if line.strip() != marker]
        remaining.insert(self._ignore_insert_index(remaining), marker)
        if remaining != lines:
            self._write_ignore_lines(remaining)
        verified = self._read_ignore_lines()
        marker_index = next(
            (index for index, line in enumerate(verified) if line.strip() == marker),
            None,
        )
        if marker_index is None or marker_index != self._ignore_insert_index(verified):
            raise VaultError("The exact Syncthing ignore could not be made authoritative")
        return not existed

    def _remove_ignore(self, relative: str) -> None:
        marker = self._ignore_marker(relative)
        lines = self._read_ignore_lines()
        remaining = [line for line in lines if line.strip() != marker]
        if remaining != lines:
            self._write_ignore_lines(remaining)

    def _revert_return(self, relative: str, ignore_added: bool) -> None:
        removal_error: VaultError | None = None
        if ignore_added:
            try:
                self._remove_ignore(relative)
            except VaultError as exc:
                removal_error = exc
        state = self._load_state()
        entry = state["entries"].get(relative)
        if isinstance(entry, dict):
            entry["phase"] = PHASE_LOCAL
            entry.pop("returnedAt", None)
            if removal_error is None:
                entry.pop("ignoreAdded", None)
            else:
                entry["ignoreAdded"] = True
            self._write_state(state)
        if removal_error is not None:
            raise VaultError(
                "The local copy was preserved, but its temporary Syncthing ignore could not be removed"
            ) from removal_error

    def check_out(self, relative: str) -> dict[str, Any]:
        """Copy a local payload into the vault; the library keeps serving it."""
        clean = _validate_relative(relative)
        payload = self.local_payload(clean)
        if clean in self._load_state()["entries"]:
            raise VaultError("This book is already managed by the vault")
        digest = self._verify_local_payload(payload)
        destination, size = self._stage_verified_copy(payload, digest, clean)
        state = self._load_state()
        if clean in state["entries"]:
            raise VaultError("This book became managed while it was being copied")
        state["entries"][clean] = {
            "sha256": digest,
            "bytes": size,
            "copyName": destination.name,
            "checkedOutAt": _utc_now(),
            "phase": PHASE_LOCAL,
        }
        self._write_state(state)
        return {"ok": True, "path": clean, "availability": AVAILABILITY_LOCAL}

    def check_in(self, relative: str) -> dict[str, Any]:
        """Verify both copies, protect the path from sync, then release payload only."""
        clean = _validate_relative(relative)
        state = self._load_state()
        current = state["entries"].get(clean)
        if not isinstance(current, dict) or current.get("phase") != PHASE_LOCAL:
            raise VaultError("This book is not checked out")
        self._verify_copy(current)
        payload = self.local_payload(clean)
        self._verify_local_payload(payload, str(current["sha256"]))

        marker_existed = self._has_ignore_marker(clean)
        ignore_added = bool(current.get("ignoreAdded")) or not marker_existed
        current["phase"] = PHASE_RETURN_PENDING
        current["returnedAt"] = _utc_now()
        current["ignoreAdded"] = ignore_added
        self._write_state(state)

        try:
            newly_added = self._ensure_ignore(clean)
            ignore_added = ignore_added or newly_added
            if current.get("ignoreAdded") != ignore_added:
                state = self._load_state()
                state["entries"][clean]["ignoreAdded"] = ignore_added
                self._write_state(state)
            self._verify_local_payload(payload, str(current["sha256"]))
        except (OSError, VaultError):
            self._revert_return(clean, ignore_added)
            raise

        try:
            payload.unlink()
            _fsync_directory(payload.parent)
        except FileNotFoundError:
            pass
        except OSError as exc:
            self._revert_return(clean, ignore_added)
            raise VaultError(f"Could not release the local payload: {exc}") from exc

        state = self._load_state()
        finalized = state["entries"].get(clean)
        if not isinstance(finalized, dict):
            raise VaultError("The vault journal lost the pending return")
        finalized["phase"] = PHASE_AWAY
        finalized.pop("returnedAt", None)
        finalized["ignoreAdded"] = ignore_added
        self._write_state(state)
        return {"ok": True, "path": clean, "availability": AVAILABILITY_AWAY}

    def _finish_restore(self, relative: str, entry: dict[str, Any], copy: Path) -> None:
        payload = self.local_payload(relative)
        payload.parent.mkdir(parents=True, exist_ok=True)
        expected = str(entry["sha256"])
        if payload.exists() or payload.is_symlink():
            self._verify_local_payload(payload, expected)
        else:
            descriptor = -1
            created_identity: tuple[int, int] | None = None
            try:
                descriptor = os.open(payload, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                opened = os.fstat(descriptor)
                created_identity = (opened.st_dev, opened.st_ino)
                with copy.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
                    descriptor = -1
                    shutil.copyfileobj(reader, writer, COPY_CHUNK_BYTES)
                    writer.flush()
                    os.fsync(writer.fileno())
                self._verify_local_payload(payload, expected)
                _fsync_directory(payload.parent)
            except FileExistsError:
                self._verify_local_payload(payload, expected)
            except (OSError, VaultError) as exc:
                if descriptor >= 0:
                    os.close(descriptor)
                    descriptor = -1
                try:
                    details = payload.lstat()
                    if created_identity == (details.st_dev, details.st_ino):
                        payload.unlink()
                except OSError:
                    pass
                if isinstance(exc, VaultError):
                    raise
                raise VaultError(f"The local payload could not be restored safely: {exc}") from exc
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
        if entry.get("ignoreAdded", True):
            self._remove_ignore(relative)

    def restore(self, relative: str) -> dict[str, Any]:
        """Restore without overwriting any unexpected local payload."""
        clean = _validate_relative(relative)
        state = self._load_state()
        current = state["entries"].get(clean)
        if not isinstance(current, dict) or current.get("phase") not in {
            PHASE_AWAY,
            PHASE_RESTORE_PENDING,
        }:
            raise VaultError("This book is not in the vault")
        current["phase"] = PHASE_RESTORE_PENDING
        current["restoredAt"] = _utc_now()
        self._write_state(state)

        try:
            copy = self._verify_copy(current)
            self._finish_restore(clean, current, copy)
        except VaultError:
            # A conflicting, missing, or invalid local payload means no restore
            # was committed. Return to the durable away phase immediately. If
            # the expected payload is present, cleanup may have failed after a
            # successful copy, so leave restore-pending for reconciliation.
            payload = self.local_payload(clean)
            try:
                self._verify_local_payload(payload, str(current["sha256"]))
            except VaultError:
                state = self._load_state()
                pending = state["entries"].get(clean)
                if (
                    isinstance(pending, dict)
                    and pending.get("phase") == PHASE_RESTORE_PENDING
                ):
                    pending["phase"] = PHASE_AWAY
                    pending.pop("restoredAt", None)
                    self._write_state(state)
            raise
        state = self._load_state()
        pending = state["entries"].get(clean)
        if not isinstance(pending, dict) or pending.get("phase") != PHASE_RESTORE_PENDING:
            raise VaultError("The vault journal lost the pending restore")
        state["entries"].pop(clean)
        self._write_state(state)
        try:
            copy.unlink()
            _fsync_directory(self.root)
        except OSError:
            pass
        return {"ok": True, "path": clean, "availability": AVAILABILITY_LOCAL}

    def availability(self, relatives: list[str]) -> dict[str, str]:
        entries = self._load_state()["entries"]
        result: dict[str, str] = {}
        for relative in relatives:
            entry = entries.get(relative)
            away = isinstance(entry, dict) and entry.get("phase") in {
                PHASE_AWAY,
                PHASE_RETURN_PENDING,
                PHASE_RESTORE_PENDING,
            }
            result[relative] = AVAILABILITY_AWAY if away else AVAILABILITY_LOCAL
        return result

    def away_paths(self) -> frozenset[str]:
        """Paths whose local payload is released or in a pending transition."""
        return frozenset(
            relative
            for relative, entry in self._load_state()["entries"].items()
            if isinstance(entry, dict)
            and entry.get("phase") in {
                PHASE_AWAY,
                PHASE_RETURN_PENDING,
                PHASE_RESTORE_PENDING,
            }
        )

    def status(self) -> dict[str, Any]:
        state = self._load_state()
        checked_out: dict[str, dict[str, Any]] = {}
        for relative, entry in sorted(state["entries"].items()):
            copy_exists = False
            try:
                copy = self.copy_path(str(entry.get("copyName") or ""))
                copy_exists = copy.is_file() and not copy.is_symlink()
            except VaultError:
                pass
            checked_out[relative] = {
                "bytes": entry.get("bytes"),
                "checkedOutAt": entry.get("checkedOutAt"),
                "phase": entry.get("phase"),
                "vaultCopyReady": copy_exists,
            }
        return {"vaultRoot": str(self.root), "checkedOut": checked_out}

    def _verify_copy_quietly(self, entry: dict[str, Any]) -> bool:
        try:
            self._verify_copy(entry)
        except VaultError:
            return False
        return True

    def reconcile(self) -> dict[str, Any]:
        """Repair interrupted operations, then prune only known-format orphans."""
        state = self._load_state()
        entries: dict[str, dict[str, Any]] = state["entries"]
        report = {
            "revertedReturns": [],
            "finalizedReturns": [],
            "completedRestores": [],
            "selfHealedAway": [],
            "unrecoverableEntries": [],
            "prunedCopies": [],
        }
        copies_to_delete: list[Path] = []
        for relative, entry in list(entries.items()):
            phase = entry["phase"]
            payload = self.local_payload(relative)
            if phase == PHASE_RETURN_PENDING:
                if payload.is_file() and not payload.is_symlink():
                    if entry.get("ignoreAdded", True):
                        self._remove_ignore(relative)
                    entry["phase"] = PHASE_LOCAL
                    entry.pop("returnedAt", None)
                    entry.pop("ignoreAdded", None)
                    report["revertedReturns"].append(relative)
                else:
                    if not self._has_ignore_marker(relative):
                        entry["ignoreAdded"] = self._ensure_ignore(relative)
                    entry["phase"] = PHASE_AWAY
                    entry.pop("returnedAt", None)
                    if not self._verify_copy_quietly(entry):
                        entry["recoveryError"] = "Both local and vault copies are unavailable"
                        report["unrecoverableEntries"].append(relative)
                    report["finalizedReturns"].append(relative)
            elif phase == PHASE_RESTORE_PENDING:
                if self._verify_copy_quietly(entry):
                    copy = self.copy_path(str(entry["copyName"]))
                    try:
                        self._finish_restore(relative, entry, copy)
                    except VaultError:
                        entry["phase"] = PHASE_AWAY
                    else:
                        entries.pop(relative)
                        copies_to_delete.append(copy)
                        report["completedRestores"].append(relative)
                else:
                    entry["phase"] = PHASE_AWAY
                    entry["recoveryError"] = "The verified vault copy is unavailable"
                    report["unrecoverableEntries"].append(relative)
            elif phase == PHASE_LOCAL and not payload.is_file():
                marker_existed = self._has_ignore_marker(relative)
                newly_added = self._ensure_ignore(relative)
                entry["ignoreAdded"] = (
                    bool(entry.get("ignoreAdded")) or newly_added or not marker_existed
                )
                entry["phase"] = PHASE_AWAY
                if not self._verify_copy_quietly(entry):
                    entry["recoveryError"] = "Both local and vault copies are unavailable"
                    report["unrecoverableEntries"].append(relative)
                report["selfHealedAway"].append(relative)
            elif phase == PHASE_AWAY and not self._has_ignore_marker(relative):
                entry["ignoreAdded"] = self._ensure_ignore(relative)

        state["entries"] = entries
        if entries or self.root.is_dir():
            self._write_state(state)
        for copy in copies_to_delete:
            try:
                copy.unlink()
            except OSError:
                pass

        known_copies = {str(entry["copyName"]) for entry in entries.values()}
        if self.root.is_dir():
            for candidate in sorted(self.root.iterdir()):
                if (
                    not candidate.is_file()
                    or candidate.is_symlink()
                    or candidate.name in known_copies
                    or not _MANAGED_COPY.fullmatch(candidate.name)
                ):
                    continue
                try:
                    candidate.unlink()
                    report["prunedCopies"].append(candidate.name)
                except OSError:
                    continue
        return report
