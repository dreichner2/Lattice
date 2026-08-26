#!/usr/bin/env python3
"""Safely relocate a Lattice library and its Syncthing folder binding.

The desktop shells use this helper only from a local working directory outside
the library. It deliberately uses Syncthing's loopback API rather than editing
``config.xml`` and never prints or persists the API key.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_FOLDER_ID = "cs-library-3b8290f24f15"
COPY_BUFFER_BYTES = 4 * 1024 * 1024
MINIMUM_FREE_SPACE_RESERVE = 64 * 1024 * 1024
MAXIMUM_API_RESPONSE_BYTES = 4 * 1024 * 1024
MAXIMUM_SYNCTHING_CONFIG_BYTES = 4 * 1024 * 1024
MAXIMUM_API_KEY_CHARACTERS = 4096
MAXIMUM_DISCONNECT_STATE_BYTES = 16 * 1024


class LibraryMoveError(RuntimeError):
    """A user-actionable relocation failure."""


class SyncthingUnavailableError(LibraryMoveError):
    """The verified loopback endpoint is not currently running."""


class Reporter:
    """Emit bounded newline-delimited JSON for a native progress surface."""

    def __call__(self, event: str, **fields: Any) -> None:
        payload = {"event": event, **fields}
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> None:
        return None


@dataclass(frozen=True)
class SourceFile:
    relative_path: Path
    size: int
    modified_ns: int


@dataclass(frozen=True)
class MovePlan:
    source: Path
    destination: Path
    staging: Path
    directories: tuple[Path, ...]
    files: tuple[SourceFile, ...]
    total_bytes: int


@dataclass(frozen=True)
class SyncthingConnection:
    config_path: Path
    base_uri: str
    api_key: str


@dataclass(frozen=True)
class MoveResult:
    destination: Path
    source_removed: bool
    syncthing_managed: bool
    warning: str | None = None


@dataclass(frozen=True)
class SyncthingDiscovery:
    client: "SyncthingClient | None"
    folder: dict[str, Any] | None
    config_path: Path | None
    managed: bool
    running: bool


@dataclass(frozen=True)
class DisconnectResult:
    syncthing_managed: bool
    syncthing_running: bool
    paused_by_lattice: bool
    syncthing_stopped: bool


@dataclass(frozen=True)
class ReconnectResult:
    syncthing_managed: bool
    syncthing_running: bool
    syncthing_started: bool
    resumed_by_lattice: bool
    resumed_existing_pause: bool
    folder_paused: bool


def _same_path(left: Path | str, right: Path | str) -> bool:
    return os.path.normcase(os.path.realpath(os.fspath(left))) == os.path.normcase(
        os.path.realpath(os.fspath(right))
    )


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_reparse_point(path: Path) -> bool:
    details = path.lstat()
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(getattr(details, "st_file_attributes", 0) & reparse_flag)


def _validate_library_root(source: Path, folder_id: str) -> None:
    if not source.is_dir() or source.is_symlink() or _is_reparse_point(source):
        raise LibraryMoveError("The current library root is missing or is an unsupported link.")

    required_files = ("CATALOG.md", "library-layout.json", "library-taxonomy.json")
    required_directories = (
        "metadata",
        "ui",
        "books",
        "papers",
        "lectures",
        "audio",
    )
    for relative in required_files:
        if not (source / relative).is_file():
            raise LibraryMoveError(f"The current library is missing {relative}.")
    for relative in required_directories:
        if not (source / relative).is_dir():
            raise LibraryMoveError(f"The current library is missing {relative}/.")

    try:
        layout = json.loads((source / "library-layout.json").read_text(encoding="utf-8"))
        configured_id = layout["syncthing"]["folder_id"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise LibraryMoveError("library-layout.json is not a valid Lattice storage layout.") from error
    if configured_id != folder_id:
        raise LibraryMoveError(
            f"The library names Syncthing folder {configured_id!r}, not the expected {folder_id!r}."
        )


def _enumerate_source(source: Path) -> tuple[tuple[Path, ...], tuple[SourceFile, ...], int]:
    directories: list[Path] = []
    files: list[SourceFile] = []
    total_bytes = 0
    for current, directory_names, file_names in os.walk(source, topdown=True, followlinks=False):
        current_path = Path(current)
        directory_names.sort()
        file_names.sort()
        for name in directory_names:
            child = current_path / name
            if child.is_symlink() or _is_reparse_point(child):
                raise LibraryMoveError(
                    f"The library contains an unsupported linked directory: {child.relative_to(source)}"
                )
            mode = child.lstat().st_mode
            if not stat.S_ISDIR(mode):
                raise LibraryMoveError(
                    f"The library contains an unsupported filesystem entry: {child.relative_to(source)}"
                )
            directories.append(child.relative_to(source))
        for name in file_names:
            child = current_path / name
            details = child.lstat()
            if child.is_symlink() or _is_reparse_point(child) or not stat.S_ISREG(details.st_mode):
                raise LibraryMoveError(
                    f"The library contains an unsupported linked or special file: {child.relative_to(source)}"
                )
            relative = child.relative_to(source)
            files.append(SourceFile(relative, details.st_size, details.st_mtime_ns))
            total_bytes += details.st_size
    return tuple(directories), tuple(files), total_bytes


def build_move_plan(
    source_value: Path | str,
    destination_value: Path | str,
    folder_id: str = DEFAULT_FOLDER_ID,
    protected_paths: Iterable[Path | str] = (),
) -> MovePlan:
    source_input = Path(source_value).expanduser()
    if source_input.is_symlink():
        raise LibraryMoveError("The current library root cannot be a symbolic link.")
    source = source_input.resolve(strict=True)
    destination_input = Path(destination_value).expanduser()
    destination = destination_input.resolve(strict=False)
    destination_parent = destination.parent

    _validate_library_root(source, folder_id)
    if _same_path(source, destination):
        raise LibraryMoveError("The destination is the current library folder.")
    if _is_within(destination, source) or _is_within(source, destination):
        raise LibraryMoveError("The destination cannot contain, or be inside, the current library.")
    if not destination_parent.is_dir() or destination_parent.is_symlink():
        raise LibraryMoveError("The selected destination folder is unavailable.")
    if destination.exists() or destination.is_symlink():
        raise LibraryMoveError(f"The destination already exists: {destination}")

    for protected_value in protected_paths:
        protected_input = Path(protected_value).expanduser()
        protected = protected_input.resolve(strict=False)
        if _is_within(protected, source):
            raise LibraryMoveError(
                "Lattice itself is running from inside the library. Install or move the app outside "
                "the library folder before relocating its storage."
            )

    directories, files, total_bytes = _enumerate_source(source)
    reserve = max(MINIMUM_FREE_SPACE_RESERVE, total_bytes // 50)
    try:
        available = shutil.disk_usage(destination_parent).free
    except OSError as error:
        raise LibraryMoveError("Lattice could not measure free space on the destination drive.") from error
    if available < total_bytes + reserve:
        needed = total_bytes + reserve
        raise LibraryMoveError(
            f"The destination needs at least {needed:,} free bytes; only {available:,} are available."
        )

    staging = destination_parent / f".{destination.name}.lattice-moving-{uuid.uuid4().hex}"
    if staging.exists():
        raise LibraryMoveError("A temporary relocation folder already exists at the destination.")
    return MovePlan(source, destination, staging, directories, files, total_bytes)


def _copy_file_verified(
    source: Path,
    destination: Path,
    expected: SourceFile,
    on_bytes: Callable[[int], None],
) -> bytes:
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while True:
            chunk = reader.read(COPY_BUFFER_BYTES)
            if not chunk:
                break
            writer.write(chunk)
            digest.update(chunk)
            copied += len(chunk)
            on_bytes(len(chunk))
        writer.flush()
        os.fsync(writer.fileno())
    if copied != expected.size:
        raise LibraryMoveError(f"The source changed while copying {expected.relative_path}.")

    after = source.stat()
    if after.st_size != expected.size or after.st_mtime_ns != expected.modified_ns:
        raise LibraryMoveError(f"The source changed while copying {expected.relative_path}.")

    destination_digest = hashlib.sha256()
    with destination.open("rb") as copied_file:
        while True:
            chunk = copied_file.read(COPY_BUFFER_BYTES)
            if not chunk:
                break
            destination_digest.update(chunk)
    if not hmac.compare_digest(digest.digest(), destination_digest.digest()):
        raise LibraryMoveError(f"Verification failed for {expected.relative_path}.")
    try:
        shutil.copystat(source, destination, follow_symlinks=False)
    except OSError:
        # Some removable filesystems cannot preserve every source metadata bit.
        pass
    return digest.digest()


def _copy_plan(plan: MovePlan, report: Callable[..., None]) -> dict[Path, bytes]:
    plan.staging.mkdir(mode=0o700)
    for relative in plan.directories:
        (plan.staging / relative).mkdir()

    completed_bytes = 0
    last_percent = -1
    source_digests: dict[Path, bytes] = {}

    def on_bytes(count: int) -> None:
        nonlocal completed_bytes, last_percent
        completed_bytes += count
        percent = 100 if plan.total_bytes == 0 else min(100, completed_bytes * 100 // plan.total_bytes)
        if percent != last_percent:
            last_percent = percent
            report(
                "progress",
                phase="copying",
                percent=percent,
                completedBytes=completed_bytes,
                totalBytes=plan.total_bytes,
                message=f"Copying and verifying your library… {percent}%",
            )

    for item in plan.files:
        source_file = plan.source / item.relative_path
        destination_file = plan.staging / item.relative_path
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        source_digests[item.relative_path] = _copy_file_verified(
            source_file,
            destination_file,
            item,
            on_bytes,
        )

    for relative in reversed(plan.directories):
        try:
            shutil.copystat(plan.source / relative, plan.staging / relative, follow_symlinks=False)
        except OSError:
            # Directory timestamps are cosmetic. File bytes and metadata remain verified.
            pass
    try:
        shutil.copystat(plan.source, plan.staging, follow_symlinks=False)
    except OSError:
        pass
    if plan.total_bytes == 0:
        report(
            "progress",
            phase="copying",
            percent=100,
            completedBytes=0,
            totalBytes=0,
            message="Copying and verifying your library… 100%",
        )
    os.replace(plan.staging, plan.destination)
    return source_digests


def _assert_source_unchanged(
    plan: MovePlan,
    expected_digests: dict[Path, bytes],
    *,
    verify_contents: bool = True,
) -> None:
    directories, files, total_bytes = _enumerate_source(plan.source)
    if directories != plan.directories or files != plan.files or total_bytes != plan.total_bytes:
        raise LibraryMoveError("The library changed while it was being copied. No original files were removed.")
    if not verify_contents:
        return
    for item in plan.files:
        digest = hashlib.sha256()
        with (plan.source / item.relative_path).open("rb") as source_file:
            while True:
                chunk = source_file.read(COPY_BUFFER_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
        if not hmac.compare_digest(digest.digest(), expected_digests[item.relative_path]):
            raise LibraryMoveError(
                f"The library changed while verifying {item.relative_path}. No original files were removed."
            )


def _configuration_candidates(explicit: Path | str | None = None) -> list[Path]:
    if explicit is not None:
        return [Path(explicit).expanduser()]

    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.extend(
            [
                Path(local_app_data) / "Syncthing" / "config.xml",
                Path(local_app_data) / "CSLibrarySync" / "Config" / "config.xml",
            ]
        )
    home = Path.home()
    candidates.extend(
        [
            home / "Library" / "Application Support" / "CSLibrarySync" / "Config" / "config.xml",
            home / "Library" / "Application Support" / "Syncthing" / "config.xml",
            home / ".config" / "syncthing" / "config.xml",
            home / ".local" / "state" / "syncthing" / "config.xml",
        ]
    )
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = os.path.normcase(os.fspath(candidate))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def _read_syncthing_connection(config_path: Path) -> SyncthingConnection:
    if config_path.is_symlink() or not config_path.is_file():
        raise LibraryMoveError("Syncthing's configuration file is unavailable.")
    try:
        config_size = config_path.stat().st_size
    except OSError as error:
        raise LibraryMoveError("Syncthing's configuration file could not be inspected.") from error
    if config_size <= 0 or config_size > MAXIMUM_SYNCTHING_CONFIG_BYTES:
        raise LibraryMoveError("Syncthing's configuration file has an unsafe size.")
    try:
        root = ET.parse(config_path).getroot()
    except (OSError, ET.ParseError) as error:
        raise LibraryMoveError("Syncthing's configuration file could not be read.") from error
    gui = root.find("gui")
    if gui is None or gui.get("enabled", "true").lower() == "false":
        raise LibraryMoveError("Syncthing's local GUI/API is disabled.")
    if gui.get("tls", gui.get("useTLS", "false")).lower() == "true":
        raise LibraryMoveError(
            "Lattice cannot safely automate a TLS-enabled Syncthing GUI. Use its loopback HTTP GUI."
        )
    address = (gui.findtext("address") or "127.0.0.1:8384").strip()
    if address.startswith("unix"):
        raise LibraryMoveError("A Unix-socket Syncthing GUI is not supported by Move Library.")
    try:
        parsed = urllib.parse.urlsplit(address if "://" in address else f"http://{address}")
        host = parsed.hostname
        port = parsed.port or 8384
    except ValueError as error:
        raise LibraryMoveError("Syncthing has an invalid local GUI address.") from error
    if host in {"0.0.0.0", "::", "[::]", "localhost"}:
        host = "127.0.0.1"
    if host not in {"127.0.0.1", "::1"}:
        raise LibraryMoveError("Refusing to send Syncthing credentials to a non-loopback address.")
    display_host = f"[{host}]" if ":" in host else host
    api_key = (gui.findtext("apikey") or gui.findtext("apiKey") or "").strip()
    if not api_key or len(api_key) > MAXIMUM_API_KEY_CHARACTERS:
        raise LibraryMoveError("Syncthing's local API key is missing.")
    return SyncthingConnection(config_path.resolve(), f"http://{display_host}:{port}", api_key)


class SyncthingClient:
    def __init__(self, connection: SyncthingConnection, timeout: float = 10.0):
        self.connection = connection
        self.timeout = timeout
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> Any:
        data = None
        headers = {"X-API-Key": self.connection.api_key, "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.connection.base_uri + path,
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                payload = response.read(MAXIMUM_API_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            error.close()
            raise LibraryMoveError("Syncthing's loopback API did not accept the storage change.") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise SyncthingUnavailableError("Syncthing's loopback API is not running.") from error
        if len(payload) > MAXIMUM_API_RESPONSE_BYTES:
            raise LibraryMoveError("Syncthing returned an unexpectedly large API response.")
        if not payload:
            return None
        try:
            return json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise LibraryMoveError("Syncthing returned an invalid API response.") from error

    def folder(self, folder_id: str) -> dict[str, Any]:
        encoded = urllib.parse.quote(folder_id, safe="")
        value = self._request("GET", f"/rest/config/folders/{encoded}")
        if not isinstance(value, dict):
            raise LibraryMoveError("Syncthing returned an invalid folder configuration.")
        return value

    def patch_folder(self, folder_id: str, values: dict[str, Any]) -> None:
        encoded = urllib.parse.quote(folder_id, safe="")
        self._request("PATCH", f"/rest/config/folders/{encoded}", values)

    def restart_required(self) -> bool:
        value = self._request("GET", "/rest/config/restart-required")
        if not isinstance(value, dict) or not isinstance(value.get("requiresRestart"), bool):
            raise LibraryMoveError("Syncthing returned an invalid restart status.")
        return bool(value["requiresRestart"])

    def status(self, folder_id: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({"folder": folder_id})
        value = self._request("GET", f"/rest/db/status?{query}")
        if not isinstance(value, dict):
            raise LibraryMoveError("Syncthing returned an invalid folder status.")
        return value

    def scan(self, folder_id: str) -> None:
        query = urllib.parse.urlencode({"folder": folder_id})
        self._request("POST", f"/rest/db/scan?{query}")

    def shutdown(self) -> None:
        self._request("POST", "/rest/system/shutdown")


def _configuration_claims_library(config_path: Path, source: Path, folder_id: str) -> bool:
    if not config_path.is_file() or config_path.is_symlink():
        return False
    try:
        config_size = config_path.stat().st_size
        if config_size <= 0 or config_size > MAXIMUM_SYNCTHING_CONFIG_BYTES:
            return False
        configuration_root = ET.parse(config_path).getroot()
    except (OSError, ET.ParseError):
        return False
    for configured_folder in configuration_root.findall("folder"):
        configured_path = configured_folder.get("path")
        if (
            configured_folder.get("id") == folder_id
            and isinstance(configured_path, str)
            and _same_path(configured_path, source)
        ):
            return True
    return False


def _discover_syncthing(
    source: Path,
    folder_id: str,
    explicit_config: Path | str | None,
) -> SyncthingDiscovery:
    configuration_claims_source = False
    offline_config: Path | None = None
    claimed_configuration_error: LibraryMoveError | None = None
    for config_path in _configuration_candidates(explicit_config):
        if not config_path.is_file():
            continue
        claims_source = _configuration_claims_library(config_path, source, folder_id)
        configuration_claims_source = configuration_claims_source or claims_source
        try:
            client = SyncthingClient(_read_syncthing_connection(config_path))
            folder = client.folder(folder_id)
        except SyncthingUnavailableError:
            if claims_source:
                offline_config = config_path.resolve()
            continue
        except LibraryMoveError as error:
            if claims_source:
                claimed_configuration_error = error
            continue
        configured_path = folder.get("path")
        if isinstance(configured_path, str) and _same_path(configured_path, source):
            return SyncthingDiscovery(client, folder, config_path.resolve(), True, True)

    if claimed_configuration_error is not None:
        raise claimed_configuration_error
    if offline_config is not None:
        return SyncthingDiscovery(None, None, offline_config, True, False)

    if (
        (source / ".stfolder").exists()
        or configuration_claims_source
        or explicit_config is not None
    ):
        raise LibraryMoveError(
            "Lattice could not verify that the running Syncthing instance manages this exact library. "
            "Start Syncthing and make sure its Lattice folder is healthy, then try again."
        )
    return SyncthingDiscovery(None, None, None, False, False)


def _find_syncthing_client(
    source: Path,
    folder_id: str,
    explicit_config: Path | str | None,
) -> tuple[SyncthingClient, dict[str, Any]] | None:
    discovery = _discover_syncthing(source, folder_id, explicit_config)
    if discovery.running:
        assert discovery.client is not None and discovery.folder is not None
        return discovery.client, discovery.folder
    if discovery.managed:
        raise LibraryMoveError(
            "Lattice could not verify that the running Syncthing instance manages this exact library. "
            "Start Syncthing and make sure its Lattice folder is healthy, then try again."
        )
    return None


def _validate_syncthing_status(status: dict[str, Any], allow_paused: bool) -> bool:
    state = status.get("state")
    allowed_states = {"idle"}
    if allow_paused:
        # Syncthing v2 may expose either ``paused`` or an empty database-model
        # state after the folder configuration has independently confirmed its
        # paused flag. Callers pass allow_paused only after that confirmation.
        allowed_states.update(("paused", ""))
    return (
        state in allowed_states
        and status.get("needTotalItems", 0) == 0
        and status.get("pullErrors", 0) == 0
        and not status.get("invalid")
    )


def _wait_for_syncthing(
    client: SyncthingClient,
    folder_id: str,
    *,
    allow_paused: bool,
    timeout: float,
    required_state: str | None = None,
) -> None:
    deadline = time.monotonic() + timeout
    last_status: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last_status = client.status(folder_id)
        if (
            _validate_syncthing_status(last_status, allow_paused)
            and (
                required_state is None
                or last_status.get("state") == required_state
                or (
                    required_state == "paused"
                    and allow_paused
                    and last_status.get("state") == ""
                )
            )
        ):
            return
        time.sleep(0.4)
    state = last_status.get("state") if last_status else "unknown"
    raise LibraryMoveError(
        f"Syncthing did not return the relocated folder to an up-to-date state (state: {state})."
    )


def _disconnect_state_path(source: Path, state_value: Path | str) -> Path:
    state_input = Path(state_value).expanduser()
    unresolved = Path(os.path.abspath(state_input))
    if _is_within(unresolved, source):
        raise LibraryMoveError(
            "Lattice's reconnect record must stay off the synchronized library drive."
        )
    if state_input.exists() and state_input.is_symlink():
        raise LibraryMoveError("Lattice's external-drive reconnect record cannot be a symbolic link.")
    try:
        state_input.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent = state_input.parent.resolve(strict=True)
    except OSError as error:
        raise LibraryMoveError("Lattice could not open its local reconnect-state folder.") from error
    state_path = parent / state_input.name
    if _is_within(state_path, source):
        raise LibraryMoveError(
            "Lattice's reconnect record must stay off the synchronized library drive."
        )
    return state_path


def _read_disconnect_state(source: Path, state_value: Path | str) -> dict[str, Any] | None:
    state_path = _disconnect_state_path(source, state_value)
    if not state_path.exists():
        return None
    if state_path.is_symlink() or not state_path.is_file():
        raise LibraryMoveError("Lattice's external-drive reconnect record is unsafe.")
    try:
        size = state_path.stat().st_size
        if size <= 0 or size > MAXIMUM_DISCONNECT_STATE_BYTES:
            raise LibraryMoveError("Lattice's external-drive reconnect record has an unsafe size.")
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except LibraryMoveError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise LibraryMoveError("Lattice's external-drive reconnect record could not be read.") from error
    if (
        not isinstance(value, dict)
        or value.get("schemaVersion") != 1
        or not isinstance(value.get("folderId"), str)
        or not isinstance(value.get("libraryRoot"), str)
        or not isinstance(value.get("resumeRequired"), bool)
    ):
        raise LibraryMoveError("Lattice's external-drive reconnect record is invalid.")
    return value


def _write_disconnect_state(
    source: Path,
    state_value: Path | str,
    folder_id: str,
) -> None:
    state_path = _disconnect_state_path(source, state_value)
    existing = _read_disconnect_state(source, state_path)
    if existing is not None and (
        existing["folderId"] != folder_id
        or not _same_path(existing["libraryRoot"], source)
    ):
        raise LibraryMoveError(
            "Another Lattice library is waiting to reconnect. Reconnect that drive before disconnecting this one."
        )
    payload = {
        "schemaVersion": 1,
        "folderId": folder_id,
        "libraryRoot": str(source),
        "resumeRequired": True,
    }
    temporary = state_path.parent / f".{state_path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as output:
            json.dump(payload, output, ensure_ascii=False, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, state_path)
    except OSError as error:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise LibraryMoveError("Lattice could not save its external-drive reconnect record.") from error


def _delete_disconnect_state(source: Path, state_value: Path | str) -> None:
    state_path = _disconnect_state_path(source, state_value)
    try:
        state_path.unlink(missing_ok=True)
    except OSError as error:
        raise LibraryMoveError("Lattice reconnected sync but could not clear its reconnect record.") from error


def _find_windows_syncthing_executable() -> Path | None:
    candidates: list[Path] = []
    for command in ("syncthing.exe", "syncthing"):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        local_root = Path(local_app_data)
        candidates.extend(
            [
                local_root / "Microsoft" / "WinGet" / "Links" / "syncthing.exe",
                local_root / "Programs" / "Syncthing" / "syncthing.exe",
            ]
        )
        packages = local_root / "Microsoft" / "WinGet" / "Packages"
        if packages.is_dir():
            candidates.extend(packages.glob("Syncthing.Syncthing_*/**/syncthing.exe"))
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "Syncthing" / "syncthing.exe")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def _syncthing_process_may_be_running() -> bool:
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["tasklist.exe", "/FI", "IMAGENAME eq syncthing.exe", "/FO", "CSV", "/NH"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=3,
                check=False,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
            output = result.stdout.decode("utf-8", errors="replace").lower()
            return result.returncode == 0 and '"syncthing.exe"' in output
        result = subprocess.run(
            ["/usr/bin/pgrep", "-x", "syncthing"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        # If process state cannot be proven, do not tell the user the drive is safe.
        return True


def _windows_syncthing_listener_process_id(client: SyncthingClient) -> int | None:
    if os.name != "nt":
        return None
    try:
        port = urllib.parse.urlsplit(client.connection.base_uri).port
        if port is None:
            return None
        result = subprocess.run(
            ["netstat.exe", "-ano", "-p", "TCP"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
        if result.returncode != 0:
            return None
        expected_port = str(port)
        for line in result.stdout.decode("utf-8", errors="replace").splitlines():
            columns = line.split()
            if len(columns) < 5 or columns[0].lower() != "tcp":
                continue
            local_address = columns[1]
            _, separator, local_port = local_address.rpartition(":")
            if not separator or local_port != expected_port:
                continue
            try:
                process_id = int(columns[-1])
            except ValueError:
                continue
            if process_id > 0:
                return process_id
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def _process_id_may_be_running(process_id: int) -> bool:
    try:
        if os.name != "nt":
            os.kill(process_id, 0)
            return True
        result = subprocess.run(
            ["tasklist.exe", "/FI", f"PID eq {process_id}", "/FO", "CSV", "/NH"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
        output = result.stdout.decode("utf-8", errors="replace")
        return result.returncode == 0 and f'"{process_id}"' in output
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, subprocess.SubprocessError):
        return True


def _wait_for_syncthing_shutdown(
    client: SyncthingClient,
    timeout: float,
    process_id: int | None = None,
) -> None:
    deadline = time.monotonic() + timeout
    api_stopped = False
    process_running = True
    while time.monotonic() < deadline:
        try:
            client._request("GET", "/rest/noauth/health")
            api_stopped = False
        except SyncthingUnavailableError:
            api_stopped = True
        except LibraryMoveError:
            # An HTTP response still proves that the local process owns the port.
            api_stopped = False
        process_running = (
            _process_id_may_be_running(process_id)
            if process_id is not None
            else _syncthing_process_may_be_running()
        )
        if api_stopped and not process_running:
            return
        time.sleep(0.4)
    if not api_stopped:
        raise LibraryMoveError(
            "The dedicated Lattice Syncthing instance did not shut down, so the drive is still connected."
        )
    raise LibraryMoveError(
        "A Syncthing process is still running after Lattice requested shutdown, so the drive is still connected."
    )


def _start_windows_syncthing(config_path: Path) -> subprocess.Popen[bytes]:
    if os.name != "nt":
        raise LibraryMoveError(
            "Syncthing is stopped. Start it, then choose Reconnect library sync again."
        )
    executable = _find_windows_syncthing_executable()
    if executable is None:
        raise LibraryMoveError(
            "Syncthing is stopped and its executable could not be found. Reinstall Syncthing or rerun Lattice Windows setup."
        )
    home = config_path.parent.resolve(strict=True)
    creation_flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        return subprocess.Popen(
            [
                str(executable),
                "serve",
                "--no-browser",
                "--no-console",
                f"--home={home}",
            ],
            cwd=home,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as error:
        raise LibraryMoveError("Windows could not restart the dedicated Lattice Syncthing instance.") from error


def _wait_for_started_syncthing(
    source: Path,
    folder_id: str,
    config_path: Path,
    process: subprocess.Popen[bytes],
    timeout: float,
) -> SyncthingDiscovery:
    deadline = time.monotonic() + timeout
    last_error: LibraryMoveError | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LibraryMoveError(
                "Syncthing exited before its local API became ready. Rerun Lattice Windows setup to repair it."
            )
        try:
            discovery = _discover_syncthing(source, folder_id, config_path)
            if discovery.running:
                return discovery
        except LibraryMoveError as error:
            last_error = error
        time.sleep(0.4)
    if last_error is not None and not isinstance(last_error, SyncthingUnavailableError):
        raise last_error
    raise LibraryMoveError("Syncthing did not come back online within 30 seconds.")


def prepare_library_disconnect(
    source_value: Path | str,
    state_file: Path | str,
    *,
    folder_id: str = DEFAULT_FOLDER_ID,
    syncthing_config: Path | str | None = None,
    shutdown_syncthing: bool = False,
    sync_timeout: float = 30.0,
) -> DisconnectResult:
    source_input = Path(source_value).expanduser()
    if source_input.is_symlink():
        raise LibraryMoveError("The current library root cannot be a symbolic link.")
    source = source_input.resolve(strict=True)
    _validate_library_root(source, folder_id)
    existing_state = _read_disconnect_state(source, state_file)
    if existing_state is not None and (
        existing_state["folderId"] != folder_id
        or not _same_path(existing_state["libraryRoot"], source)
    ):
        raise LibraryMoveError(
            "Another Lattice library is waiting to reconnect. Reconnect that drive before disconnecting this one."
        )
    discovery = _discover_syncthing(source, folder_id, syncthing_config)
    if not discovery.managed:
        return DisconnectResult(False, False, False, False)
    if not discovery.running:
        if _syncthing_process_may_be_running():
            raise LibraryMoveError(
                "Syncthing's local API is unavailable, but a Syncthing process is still running. "
                "Restart Syncthing, wait for Lattice to show Live sync, and try disconnecting again."
            )
        if existing_state is not None and existing_state["resumeRequired"]:
            # This state is written only after an earlier Up-to-Date check and
            # confirmed Lattice-owned pause. The stopped process has no handle.
            return DisconnectResult(True, False, False, True)
        raise LibraryMoveError(
            "Start Syncthing so Lattice can verify that the folder is Up to Date before ejecting its drive."
        )

    assert discovery.client is not None and discovery.folder is not None
    client = discovery.client
    folder = discovery.folder
    if folder.get("type") != "sendreceive":
        raise LibraryMoveError("The Lattice Syncthing folder must be Send & Receive before disconnecting.")
    if client.restart_required():
        raise LibraryMoveError("Syncthing has a pending restart. Restart it, then try disconnecting again.")
    original_paused = bool(folder.get("paused", False))
    paused_by_lattice = False
    if original_paused:
        if not _validate_syncthing_status(client.status(folder_id), allow_paused=True):
            raise LibraryMoveError(
                "The paused Lattice folder is not fully synchronized. Resume it and wait for Up to Date before ejecting its drive."
            )
    else:
        initial_status = client.status(folder_id)
        if not _validate_syncthing_status(initial_status, allow_paused=False):
            raise LibraryMoveError(
                "Wait for the Lattice folder to show Up to Date before disconnecting its drive."
            )

        client.patch_folder(folder_id, {"paused": True})
        try:
            if not bool(client.folder(folder_id).get("paused", False)):
                raise LibraryMoveError("Syncthing did not pause the Lattice folder.")
            _wait_for_syncthing(
                client,
                folder_id,
                allow_paused=True,
                timeout=sync_timeout,
                required_state="paused",
            )
            _write_disconnect_state(source, state_file, folder_id)
            paused_by_lattice = True
        except BaseException as error:
            try:
                client.patch_folder(folder_id, {"paused": False})
                client.scan(folder_id)
            except Exception as restore_error:  # pragma: no cover - catastrophic API failure
                raise LibraryMoveError(
                    f"{error} Syncthing also could not restore the folder after disconnect preparation failed: {restore_error}"
                ) from error
            raise

    if shutdown_syncthing:
        process_id = _windows_syncthing_listener_process_id(client)
        try:
            client.shutdown()
        except SyncthingUnavailableError:
            # Syncthing may close the socket before the successful shutdown
            # response reaches the client. The process check below is authoritative.
            pass
        _wait_for_syncthing_shutdown(client, sync_timeout, process_id)
        return DisconnectResult(True, True, paused_by_lattice, True)

    return DisconnectResult(True, True, paused_by_lattice, False)


def reconnect_library(
    source_value: Path | str,
    state_file: Path | str,
    *,
    folder_id: str = DEFAULT_FOLDER_ID,
    syncthing_config: Path | str | None = None,
    start_if_needed: bool = False,
    resume_existing_pause: bool = False,
    previous_source: Path | str | None = None,
    sync_timeout: float = 120.0,
) -> ReconnectResult:
    source_input = Path(source_value).expanduser()
    if source_input.is_symlink():
        raise LibraryMoveError("The current library root cannot be a symbolic link.")
    source = source_input.resolve(strict=True)
    _validate_library_root(source, folder_id)
    previous = (
        Path(previous_source).expanduser().resolve(strict=False)
        if previous_source is not None
        else None
    )
    state = _read_disconnect_state(source, state_file)
    if state is not None and (
        state["folderId"] != folder_id
        or (
            not _same_path(state["libraryRoot"], source)
            and (previous is None or not _same_path(state["libraryRoot"], previous))
        )
    ):
        raise LibraryMoveError(
            "The saved reconnect record belongs to another library path. Reconnect that drive before changing this folder."
        )

    discovery_error: LibraryMoveError | None = None
    try:
        discovery = _discover_syncthing(source, folder_id, syncthing_config)
    except LibraryMoveError as error:
        discovery_error = error
        discovery = SyncthingDiscovery(None, None, None, False, False)
    discovery_source = source
    if (
        not discovery.managed
        and previous is not None
        and not _same_path(previous, source)
    ):
        try:
            previous_discovery = _discover_syncthing(previous, folder_id, syncthing_config)
        except LibraryMoveError:
            if discovery_error is not None:
                raise discovery_error
            raise
        if previous_discovery.managed:
            discovery = previous_discovery
            discovery_source = previous
    if not discovery.managed and discovery_error is not None:
        raise discovery_error
    started = False
    if discovery.managed and not discovery.running and start_if_needed:
        if discovery.config_path is None:
            raise LibraryMoveError("Lattice could not locate Syncthing's configuration for this library.")
        process = _start_windows_syncthing(discovery.config_path)
        discovery = _wait_for_started_syncthing(
            discovery_source,
            folder_id,
            discovery.config_path,
            process,
            30.0,
        )
        started = True
    if not discovery.managed:
        return ReconnectResult(False, False, False, False, False, False)
    if not discovery.running:
        raise LibraryMoveError(
            "Syncthing is stopped. Start it, then choose Reconnect library sync again."
        )

    assert discovery.client is not None and discovery.folder is not None
    client = discovery.client
    folder = discovery.folder
    if folder.get("type") != "sendreceive":
        raise LibraryMoveError("The Lattice Syncthing folder must be Send & Receive before reconnecting.")
    if client.restart_required():
        raise LibraryMoveError("Syncthing has a pending restart. Restart it, then reconnect the library.")
    if not _same_path(str(folder.get("path", "")), source):
        if previous is None or not _same_path(str(folder.get("path", "")), previous):
            raise LibraryMoveError(
                "Syncthing's saved Lattice folder points to an unexpected path. No sync setting was changed."
            )
        if not bool(folder.get("paused", False)):
            raise LibraryMoveError(
                "Syncthing's saved Lattice folder is not paused, so Lattice will not change its drive path."
            )
        client.patch_folder(folder_id, {"path": str(source), "paused": True})
        folder = client.folder(folder_id)
        if not _same_path(str(folder.get("path", "")), source):
            raise LibraryMoveError("Syncthing did not accept the reconnected library drive path.")
    resumed = False
    resumed_existing_pause = False
    if state is not None and state["resumeRequired"]:
        if bool(folder.get("paused", False)):
            client.patch_folder(folder_id, {"paused": False})
            if bool(client.folder(folder_id).get("paused", True)):
                raise LibraryMoveError("Syncthing did not resume the Lattice folder.")
            resumed = True
    elif bool(folder.get("paused", False)) and resume_existing_pause:
        client.patch_folder(folder_id, {"paused": False})
        if bool(client.folder(folder_id).get("paused", True)):
            raise LibraryMoveError("Syncthing did not resume the Lattice folder.")
        resumed_existing_pause = True

    folder_paused = bool(client.folder(folder_id).get("paused", False))
    if not folder_paused:
        client.scan(folder_id)
        _wait_for_syncthing(client, folder_id, allow_paused=False, timeout=sync_timeout)
        if state is not None:
            _delete_disconnect_state(source, state_file)

    return ReconnectResult(
        True,
        True,
        started,
        resumed,
        resumed_existing_pause,
        folder_paused,
    )


def _remove_tree(path: Path) -> None:
    def make_writable_and_retry(function: Callable[..., Any], value: str, _: Any) -> None:
        os.chmod(value, stat.S_IWRITE | stat.S_IREAD)
        function(value)

    shutil.rmtree(path, onerror=make_writable_and_retry)


def move_library(
    source: Path | str,
    destination: Path | str,
    *,
    folder_id: str = DEFAULT_FOLDER_ID,
    protected_paths: Iterable[Path | str] = (),
    syncthing_config: Path | str | None = None,
    report: Callable[..., None] | None = None,
    sync_timeout: float = 120.0,
) -> MoveResult:
    emit = report or (lambda _event, **_fields: None)
    plan = build_move_plan(source, destination, folder_id, protected_paths)
    emit(
        "plan",
        source=str(plan.source),
        destination=str(plan.destination),
        files=len(plan.files),
        totalBytes=plan.total_bytes,
        message=f"Preparing to move {len(plan.files):,} files.",
    )

    syncthing = _find_syncthing_client(plan.source, folder_id, syncthing_config)
    client: SyncthingClient | None = None
    original_folder: dict[str, Any] | None = None
    original_paused = False
    pause_attempted = False
    path_change_attempted = False

    if syncthing is not None:
        client, original_folder = syncthing
        if original_folder.get("type") != "sendreceive":
            raise LibraryMoveError("The Lattice Syncthing folder must be Send & Receive before it can move.")
        original_paused = bool(original_folder.get("paused", False))
        if client.restart_required():
            raise LibraryMoveError("Syncthing already has a pending restart. Restart it, then try again.")
        initial_status = client.status(folder_id)
        if not _validate_syncthing_status(initial_status, allow_paused=original_paused):
            raise LibraryMoveError(
                "Syncthing must show the Lattice folder as Up to Date before Move Library can begin."
            )

    try:
        if client is not None:
            emit("progress", phase="pausing", percent=0, message="Pausing Syncthing safely…")
            pause_attempted = True
            client.patch_folder(folder_id, {"paused": True})
            if not bool(client.folder(folder_id).get("paused", False)):
                raise LibraryMoveError("Syncthing did not pause the Lattice folder.")

        source_digests = _copy_plan(plan, emit)
        _assert_source_unchanged(plan, source_digests)
        if not (plan.destination / ".stfolder").exists() and client is not None:
            raise LibraryMoveError("The copied library is missing Syncthing's .stfolder safety marker.")

        if client is not None:
            emit(
                "progress",
                phase="redirecting",
                percent=100,
                message="Pointing Syncthing at the external library…",
            )
            path_change_attempted = True
            client.patch_folder(folder_id, {"path": str(plan.destination), "paused": True})
            moved_folder = client.folder(folder_id)
            if not _same_path(str(moved_folder.get("path", "")), plan.destination):
                raise LibraryMoveError("Syncthing did not retain the relocated library path.")
            if client.restart_required():
                raise LibraryMoveError("Syncthing unexpectedly requires a restart for the new library path.")
            client.patch_folder(folder_id, {"paused": original_paused})
            if not original_paused:
                emit(
                    "progress",
                    phase="syncing",
                    percent=100,
                    message="Verifying the relocated library with Syncthing…",
                )
                client.scan(folder_id)
            _wait_for_syncthing(
                client,
                folder_id,
                allow_paused=original_paused,
                timeout=sync_timeout,
            )

        _assert_source_unchanged(plan, source_digests, verify_contents=False)
        source_removed = True
        warning = None
        emit(
            "progress",
            phase="cleanup",
            percent=100,
            message="Removing the verified copy from the old drive…",
        )
        try:
            _remove_tree(plan.source)
        except OSError:
            source_removed = False
            warning = (
                "The external library is active, but the system could not remove every file from the old "
                "location. You can delete the old folder after confirming Lattice opens normally."
            )
        return MoveResult(plan.destination, source_removed, client is not None, warning)
    except BaseException as error:
        rollback_error: Exception | None = None
        if client is not None and pause_attempted:
            try:
                current_folder = client.folder(folder_id)
                if path_change_attempted or not _same_path(
                    str(current_folder.get("path", "")), plan.source
                ):
                    client.patch_folder(folder_id, {"path": str(plan.source), "paused": True})
                    restored = client.folder(folder_id)
                    if not _same_path(str(restored.get("path", "")), plan.source):
                        raise LibraryMoveError("Syncthing did not restore the original library path.")
                client.patch_folder(folder_id, {"paused": original_paused})
                if not original_paused:
                    client.scan(folder_id)
            except Exception as restore_error:  # pragma: no cover - catastrophic API failure
                rollback_error = restore_error

        if not path_change_attempted:
            for temporary in (plan.staging, plan.destination):
                if temporary.exists():
                    try:
                        _remove_tree(temporary)
                    except OSError:
                        pass
        if rollback_error is not None:
            raise LibraryMoveError(
                f"{error} Syncthing also could not restore its original path: {rollback_error}"
            ) from error
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Lattice library storage safely.")
    parser.add_argument(
        "--operation",
        choices=("move", "disconnect", "reconnect"),
        default="move",
    )
    parser.add_argument("--source", required=True, help="Current Lattice library root")
    parser.add_argument("--destination", help="New, not-yet-existing library root")
    parser.add_argument("--state-file", help="Local reconnect record outside the library")
    parser.add_argument("--start-if-needed", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--resume-existing-pause", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--previous-source", help=argparse.SUPPRESS)
    parser.add_argument("--shutdown-syncthing", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--folder-id", default=DEFAULT_FOLDER_ID)
    parser.add_argument("--protected-path", action="append", default=[])
    parser.add_argument("--syncthing-config", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    reporter = Reporter()
    try:
        if arguments.operation == "move":
            if not arguments.destination:
                raise LibraryMoveError("Move Library requires a destination folder.")
            result = move_library(
                arguments.source,
                arguments.destination,
                folder_id=arguments.folder_id,
                protected_paths=arguments.protected_path,
                syncthing_config=arguments.syncthing_config,
                report=reporter,
            )
            reporter(
                "complete",
                operation="move",
                destination=str(result.destination),
                sourceRemoved=result.source_removed,
                syncthingManaged=result.syncthing_managed,
                warning=result.warning,
                message="Your Lattice library is ready on the new drive.",
            )
        elif arguments.operation == "disconnect":
            if not arguments.state_file:
                raise LibraryMoveError("Disconnect library drive requires a local state file.")
            disconnected = prepare_library_disconnect(
                arguments.source,
                arguments.state_file,
                folder_id=arguments.folder_id,
                syncthing_config=arguments.syncthing_config,
                shutdown_syncthing=arguments.shutdown_syncthing,
            )
            reporter(
                "complete",
                operation="disconnect",
                syncthingManaged=disconnected.syncthing_managed,
                syncthingRunning=disconnected.syncthing_running,
                pausedByLattice=disconnected.paused_by_lattice,
                syncthingStopped=disconnected.syncthing_stopped,
                message=(
                    "The dedicated Lattice Syncthing instance is stopped and released the library drive."
                    if disconnected.syncthing_stopped
                    else "Syncthing released the Lattice folder."
                    if disconnected.syncthing_running
                    else "Syncthing is already stopped and has no library-drive handle."
                ),
            )
        else:
            if not arguments.state_file:
                raise LibraryMoveError("Reconnect library sync requires a local state file.")
            reconnected = reconnect_library(
                arguments.source,
                arguments.state_file,
                folder_id=arguments.folder_id,
                syncthing_config=arguments.syncthing_config,
                start_if_needed=arguments.start_if_needed,
                resume_existing_pause=arguments.resume_existing_pause,
                previous_source=arguments.previous_source,
            )
            reporter(
                "complete",
                operation="reconnect",
                syncthingManaged=reconnected.syncthing_managed,
                syncthingRunning=reconnected.syncthing_running,
                syncthingStarted=reconnected.syncthing_started,
                resumedByLattice=reconnected.resumed_by_lattice,
                resumedExistingPause=reconnected.resumed_existing_pause,
                folderPaused=reconnected.folder_paused,
                message=(
                    "Syncthing is running, but the Lattice folder is paused."
                    if reconnected.folder_paused
                    else "The Lattice library and Syncthing are reconnected."
                    if reconnected.syncthing_managed
                    else "This library is not managed by Syncthing."
                ),
            )
    except (LibraryMoveError, OSError, ValueError) as error:
        reporter("error", message=str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
