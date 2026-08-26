"""External-drive book vault for Lattice.

A per-device cache that holds verified copies of library payloads so the
local copies inside a synchronized library checkout can be released while
the reading drive is the only connected copy. Checking a book back in
verifies the vault copy byte-for-byte before removing the local payload;
restoring copies it back and verifies the result.

Crash safety is ordered around one rule: the durable vault-state journal is
updated BEFORE any destructive step and reconciled at startup.

- check-out: copy to vault first, then journal the entry. A crash before
  journaling leaves only an orphan copy that reconciliation prunes.
- check-in: journal ``return-pending``, then delete the local payload, then
  drop the journal entry. A crash in between either reverts the return
  (payload still present) or finalizes it (verified vault copy remains).
- restore: journal ``restore-pending``, then copy back, then drop the entry.
  A crash either resumes the restore or finishes its bookkeeping.

The vault never touches Syncthing. Deleting an ignored payload could still
propagate as a deletion before Syncthing rescans ``.stignore``, so check-in
adds an exact-path ignore line before deleting and restore removes it again.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SIDECAR_SUFFIX = ".library.json"
STATE_VERSION = 1
COPY_CHUNK_BYTES = 1024 * 1024

PHASE_LOCAL = "local"
PHASE_AWAY = "away"
PHASE_RETURN_PENDING = "return-pending"
PHASE_RESTORE_PENDING = "restore-pending"

# An entry exists for every path the vault is responsible for. ``local`` means
# a verified vault copy is staged while the payload also remains in the
# library; ``away`` means the local payload (and its adjacent sidecar) were
# released after verification and the vault copy is the only device-local one.

AVAILABILITY_LOCAL = "local"
AVAILABILITY_AWAY = "away"


class VaultError(ValueError):
    """A requested vault operation cannot be performed safely."""


def default_vault_root() -> Path:
    """Per-device private cache location, overridable for tests."""
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
        while True:
            chunk = handle.read(COPY_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _validate_relative(relative: str) -> str:
    pure = Path(relative.replace("\\", "/"))
    parts = [part for part in pure.parts if part not in {"", "."}]
    if (
        not relative
        or pure.is_absolute()
        or not parts
        or ".." in parts
        or any(part.startswith(".") for part in parts)
    ):
        raise VaultError("Invalid library payload path")
    normalized = "/".join(parts)
    if ":" in normalized:
        raise VaultError("Invalid library payload path")
    return normalized


class BookVault:
    """Verified per-device checkout cache for one library root."""

    def __init__(self, library_root: Path, library_id: str, vault_root: Path | None = None):
        self.library_root = Path(library_root).resolve()
        self.library_id = library_id
        self.root = Path(vault_root) if vault_root else default_vault_root()

    # ------------------------------------------------------------------ paths

    @property
    def state_path(self) -> Path:
        return self.root / "vault-state.json"

    def copy_path(self, copy_name: str) -> Path:
        safe = Path(copy_name)
        if safe.is_absolute() or safe.parent != Path("."):
            raise VaultError("Invalid vault copy name")
        return self.root / copy_name

    def local_payload(self, relative: str) -> Path:
        candidate = (self.library_root / _validate_relative(relative)).resolve()
        resolved_root = self.library_root.resolve()
        if not candidate.is_relative_to(resolved_root):
            raise VaultError("Payload escapes the library root")
        return candidate

    # ------------------------------------------------------------------ state

    def _load_state(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return {"version": STATE_VERSION, "libraryId": self.library_id, "entries": {}}
        if not isinstance(raw, dict) or not isinstance(raw.get("entries"), dict):
            return {"version": STATE_VERSION, "libraryId": self.library_id, "entries": {}}
        if raw.get("libraryId") != self.library_id:
            return {"version": STATE_VERSION, "libraryId": self.library_id, "entries": {}}
        return raw

    def _write_state(self, state: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        state["version"] = STATE_VERSION
        state["libraryId"] = self.library_id
        state["updatedAt"] = _utc_now()
        temporary = self.root / f".vault-state.{os.urandom(6).hex()}.tmp"
        try:
            with temporary.open("w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _entry(self, relative: str) -> dict[str, Any] | None:
        entry = self._load_state()["entries"].get(relative)
        return entry if isinstance(entry, dict) else None

    # ------------------------------------------------------------ core helpers

    def _verified_copy_name(self, digest: str, payload: Path) -> str:
        stem = payload.stem[:60] or "book"
        return f"{stem}-{digest[:10]}{payload.suffix.lower()}"

    def _stage_verified_copy(self, source: Path, expected_digest: str) -> tuple[Path, int]:
        """Copy source into the vault and prove it matches expected_digest."""
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.copy_path(self._verified_copy_name(expected_digest, source))
        temporary = self.root / f".staging.{os.urandom(6).hex()}.tmp"
        try:
            with source.open("rb") as reader, temporary.open("xb") as writer:
                shutil.copyfileobj(reader, writer, COPY_CHUNK_BYTES)
                writer.flush()
                os.fsync(writer.fileno())
            staged_digest = sha256_file(temporary)
            if staged_digest != expected_digest:
                raise VaultError("Staged vault copy failed verification")
            size = temporary.stat().st_size
            os.replace(temporary, destination)
            return destination, size
        finally:
            temporary.unlink(missing_ok=True)

    def _verify_copy(self, entry: dict[str, Any]) -> Path:
        copy_name = str(entry.get("copyName") or "")
        if not copy_name:
            raise VaultError("Vault entry has no recorded copy")
        copy = self.copy_path(copy_name)
        if not copy.is_file():
            raise VaultError(f"The vault copy is missing: {copy_name}")
        digest = sha256_file(copy)
        if digest != entry.get("sha256"):
            raise VaultError("The vault copy no longer matches the recorded checksum")
        return copy

    def _set_ignore(self, relative: str, *, ignore: bool) -> None:
        marker = f"/{relative}"
        ignore_path = self.library_root / ".stignore"
        lines: list[str] = []
        if ignore_path.is_file():
            try:
                lines = ignore_path.read_text(encoding="utf-8").splitlines()
            except OSError:
                lines = []
        rest = [line for line in lines if line.strip() != marker]
        if ignore:
            rest.append(marker)
        if rest == lines:
            return
        temporary = ignore_path.with_name(f".stignore.{os.urandom(6).hex()}.tmp")
        try:
            temporary.write_text("\n".join(rest) + ("\n" if rest else ""), encoding="utf-8")
            os.replace(temporary, ignore_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _sidecar_digest(self, payload: Path) -> str | None:
        sidecar = payload.with_name(payload.name + SIDECAR_SUFFIX)
        if not sidecar.is_file():
            return None
        try:
            record = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return None
        value = record.get("sha256") if isinstance(record, dict) else None
        return value if isinstance(value, str) and len(value) == 64 else None

    # ------------------------------------------------------------- operations

    def check_out(self, relative: str) -> dict[str, Any]:
        """Copy a local payload into the vault; the library keeps serving it."""
        clean = _validate_relative(relative)
        payload = self.local_payload(clean)
        if not payload.is_file():
            raise VaultError("Payload is unavailable")
        if clean in self._load_state()["entries"]:
            raise VaultError("This book is already managed by the vault")
        digest = sha256_file(payload)
        recorded = self._sidecar_digest(payload)
        if recorded and recorded != digest:
            raise VaultError("Library payload no longer matches its recorded checksum")
        destination, size = self._stage_verified_copy(payload, digest)
        state = self._load_state()
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
        """Verify the vault copy, then release the local payload."""
        clean = _validate_relative(relative)
        entry = self._entry(clean)
        if entry is None or entry.get("phase") != PHASE_LOCAL:
            raise VaultError("This book is not checked out")
        self._verify_copy(entry)

        state = self._load_state()
        current = state["entries"].get(clean)
        if not isinstance(current, dict) or current.get("phase") != PHASE_LOCAL:
            raise VaultError("This book is not checked out")
        current["phase"] = PHASE_RETURN_PENDING
        current["returnedAt"] = _utc_now()
        self._write_state(state)

        payload = self.local_payload(clean)
        if payload.exists():
            try:
                payload.unlink()
            except OSError as exc:
                state = self._load_state()
                resumed = state["entries"].get(clean)
                if isinstance(resumed, dict):
                    resumed["phase"] = PHASE_LOCAL
                    self._write_state(state)
                raise VaultError(f"Could not release the local copy: {exc}") from exc
        payload.with_name(payload.name + SIDECAR_SUFFIX).unlink(missing_ok=True)

        state = self._load_state()
        finalized = state["entries"].pop(clean, None)
        if isinstance(finalized, dict):
            finalized["phase"] = PHASE_AWAY
            finalized.pop("returnedAt", None)
            state["entries"][clean] = finalized
        self._write_state(state)
        self._set_ignore(clean, ignore=True)
        return {"ok": True, "path": clean, "availability": AVAILABILITY_AWAY}

    def restore(self, relative: str) -> dict[str, Any]:
        """Copy a checked-out book back into the library and verify it."""
        clean = _validate_relative(relative)
        entry = self._entry(clean)
        if entry is None or entry.get("phase") not in {PHASE_AWAY, PHASE_RESTORE_PENDING}:
            raise VaultError("This book is not in the vault")

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

        copy = self._verify_copy(current)
        payload = self.local_payload(clean)
        payload.parent.mkdir(parents=True, exist_ok=True)
        temporary = payload.with_name(f".lattice-restore.{os.urandom(6).hex()}.tmp")
        try:
            with copy.open("rb") as reader, temporary.open("xb") as writer:
                shutil.copyfileobj(reader, writer, COPY_CHUNK_BYTES)
                writer.flush()
                os.fsync(writer.fileno())
            restored_digest = sha256_file(temporary)
            if restored_digest != current.get("sha256"):
                raise VaultError("Restored copy failed verification")
            os.replace(temporary, payload)
        finally:
            temporary.unlink(missing_ok=True)
        self._set_ignore(clean, ignore=False)

        state = self._load_state()
        state["entries"].pop(clean, None)
        self._write_state(state)
        try:
            copy.unlink()
        except OSError:
            pass
        return {"ok": True, "path": clean, "availability": AVAILABILITY_LOCAL}

    # ---------------------------------------------------------------- queries

    def availability(self, relatives: list[str]) -> dict[str, str]:
        entries = self._load_state()["entries"]
        result: dict[str, str] = {}
        for relative in relatives:
            entry = entries.get(relative)
            away = isinstance(entry, dict) and entry.get("phase") == PHASE_AWAY
            result[relative] = AVAILABILITY_AWAY if away else AVAILABILITY_LOCAL
        return result

    def away_paths(self) -> frozenset[str]:
        """Paths whose local payload has been released to the vault."""
        return frozenset(
            relative
            for relative, entry in self._load_state()["entries"].items()
            if isinstance(entry, dict) and entry.get("phase") == PHASE_AWAY
        )

    def status(self) -> dict[str, Any]:
        state = self._load_state()
        checked_out: dict[str, dict[str, Any]] = {}
        for relative, entry in sorted(state["entries"].items()):
            if not isinstance(entry, dict):
                continue
            copy_exists = False
            copy_name = entry.get("copyName")
            if isinstance(copy_name, str) and copy_name:
                copy_exists = self.copy_path(copy_name).is_file()
            checked_out[relative] = {
                "title": entry.get("title") or "",
                "bytes": entry.get("bytes"),
                "checkedOutAt": entry.get("checkedOutAt"),
                "phase": entry.get("phase"),
                "vaultCopyReady": copy_exists,
            }
        return {"vaultRoot": str(self.root), "checkedOut": checked_out}

    # ------------------------------------------------------------- reconcile

    def reconcile(self) -> dict[str, Any]:
        """Repair interrupted operations and prune orphaned copies at startup."""
        state = self._load_state()
        entries: dict[str, dict[str, Any]] = {
            key: value
            for key, value in state["entries"].items()
            if isinstance(value, dict)
        }
        report = {
            "revertedReturns": [],
            "finalizedReturns": [],
            "completedRestores": [],
            "selfHealedAway": [],
            "droppedEntries": [],
            "prunedCopies": [],
        }

        for relative, entry in list(entries.items()):
            phase = entry.get("phase")
            payload = self.local_payload(relative)
            if phase == PHASE_RETURN_PENDING:
                if payload.is_file():
                    entry["phase"] = PHASE_LOCAL
                    report["revertedReturns"].append(relative)
                elif self._verify_copy_quietly(entry):
                    entry["phase"] = PHASE_AWAY
                    entry.pop("returnedAt", None)
                    self._set_ignore(relative, ignore=True)
                    report["finalizedReturns"].append(relative)
                else:
                    # Neither copy survived; surface it as an unusable away
                    # entry rather than pretending the book is available.
                    entry["phase"] = PHASE_AWAY
                    report["finalizedReturns"].append(relative)
            elif phase == PHASE_RESTORE_PENDING:
                if self._verify_copy_quietly(entry):
                    try:
                        copy = self.copy_path(str(entry.get("copyName") or ""))
                        self._finish_restore(relative, entry, copy)
                        entry["phase"] = PHASE_LOCAL
                        entry.pop("restoredAt", None)
                        report["completedRestores"].append(relative)
                    except VaultError:
                        entry["phase"] = PHASE_AWAY
                else:
                    entry["phase"] = PHASE_AWAY
            elif phase == PHASE_LOCAL:
                if not payload.is_file():
                    if self._verify_copy_quietly(entry):
                        entry["phase"] = PHASE_AWAY
                        self._set_ignore(relative, ignore=True)
                        report["selfHealedAway"].append(relative)
                    else:
                        entries.pop(relative, None)
                        report["droppedEntries"].append(relative)

        known_copies = {str(entry.get("copyName")) for entry in entries.values()}
        if self.root.is_dir():
            for candidate in sorted(self.root.iterdir()):
                if (
                    not candidate.is_file()
                    or candidate.name in known_copies
                    or candidate.name.startswith(".")
                    or candidate.name == self.state_path.name
                ):
                    continue
                try:
                    candidate.unlink()
                    report["prunedCopies"].append(candidate.name)
                except OSError:
                    continue

        state["entries"] = entries
        # Avoid creating the per-device vault directory as a side effect when
        # there was never any vault state (e.g. read-only or test contexts).
        if entries or self.root.is_dir():
            self._write_state(state)
        return report

    # ------------------------------------------------------- reconcile helpers

    def _verify_copy_quietly(self, entry: dict[str, Any]) -> bool:
        try:
            self._verify_copy(entry)
        except VaultError:
            return False
        return True

    def _finish_restore(self, relative: str, entry: dict[str, Any], copy: Path) -> None:
        payload = self.local_payload(relative)
        payload.parent.mkdir(parents=True, exist_ok=True)
        temporary = payload.with_name(f".lattice-restore.{os.urandom(6).hex()}.tmp")
        try:
            with copy.open("rb") as reader, temporary.open("xb") as writer:
                shutil.copyfileobj(reader, writer, COPY_CHUNK_BYTES)
                writer.flush()
                os.fsync(writer.fileno())
            if sha256_file(temporary) != entry.get("sha256"):
                raise VaultError("Restored copy failed verification")
            os.replace(temporary, payload)
        finally:
            temporary.unlink(missing_ok=True)
        self._set_ignore(relative, ignore=False)
