from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import move_library  # noqa: E402


FOLDER_ID = move_library.DEFAULT_FOLDER_ID
API_KEY = "fixture-api-key"


def make_library(root: Path, *, synced: bool) -> None:
    root.mkdir()
    (root / "CATALOG.md").write_text("# Fixture\n", encoding="utf-8")
    (root / "library-taxonomy.json").write_text("{}\n", encoding="utf-8")
    (root / "library-layout.json").write_text(
        json.dumps({"schema_version": 1, "syncthing": {"folder_id": FOLDER_ID}}),
        encoding="utf-8",
    )
    (root / "metadata").mkdir()
    (root / "ui").mkdir()
    for name in ("books", "papers", "lectures", "audio"):
        (root / name).mkdir()
    (root / "books" / "large.pdf").write_bytes((b"lattice fixture\n" * 8192) + b"end")
    (root / "papers" / "paper.txt").write_text("verified", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    if synced:
        (root / ".stfolder").mkdir()
        (root / ".stfolder" / "marker").write_text("keep", encoding="utf-8")


class FakeSyncthingState:
    def __init__(self, source: Path):
        self.source = str(source)
        self.folder = {
            "id": FOLDER_ID,
            "label": "Lattice",
            "path": str(source),
            "type": "sendreceive",
            "paused": False,
        }
        self.scans = 0
        self.shutdowns = 0
        self.paused_status_state = "paused"
        self.fail_after_redirect = False
        self.fail_pause_response_once = False
        self.fail_redirect_response_once = False
        self.redirect_folder_request = False
        self.redirect_leak_requests = 0


class FakeSyncthingHandler(BaseHTTPRequestHandler):
    server: "FakeSyncthingServer"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _authorized(self) -> bool:
        return self.headers.get("X-API-Key") == API_KEY

    def _json(self, value: object, status: int = 200) -> None:
        encoded = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _empty(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json({"error": "unauthorized"}, 403)
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == f"/rest/config/folders/{FOLDER_ID}":
            if self.server.state.redirect_folder_request:
                self.send_response(302)
                self.send_header(
                    "Location",
                    f"http://127.0.0.1:{self.server.server_address[1]}/credential-leak",
                )
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._json(self.server.state.folder)
        elif parsed.path == "/credential-leak":
            self.server.state.redirect_leak_requests += 1
            self._json({"leaked": True})
        elif parsed.path == "/rest/config/restart-required":
            self._json({"requiresRestart": False})
        elif parsed.path == "/rest/db/status":
            redirected = self.server.state.folder["path"] != self.server.state.source
            blocked = redirected and self.server.state.fail_after_redirect
            self._json(
                {
                    "state": (
                        self.server.state.paused_status_state
                        if self.server.state.folder["paused"]
                        else "idle"
                    ),
                    "needTotalItems": 1 if blocked else 0,
                    "pullErrors": 0,
                    "invalid": "",
                }
            )
        else:
            self._json({"error": "not found"}, 404)

    def do_PATCH(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json({"error": "unauthorized"}, 403)
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != f"/rest/config/folders/{FOLDER_ID}":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        values = json.loads(self.rfile.read(length))
        self.server.state.folder.update(values)
        if "path" in values and self.server.state.fail_redirect_response_once:
            self.server.state.fail_redirect_response_once = False
            self._json({"error": "ambiguous redirect fixture"}, 500)
            return
        if values.get("paused") is True and self.server.state.fail_pause_response_once:
            self.server.state.fail_pause_response_once = False
            self._json({"error": "ambiguous pause fixture"}, 500)
            return
        self._empty()

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._json({"error": "unauthorized"}, 403)
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/rest/db/scan":
            self.server.state.scans += 1
            self._empty()
        elif parsed.path == "/rest/system/shutdown":
            self.server.state.shutdowns += 1
            self._empty()
        else:
            self._json({"error": "not found"}, 404)


class FakeSyncthingServer(ThreadingHTTPServer):
    def __init__(self, state: FakeSyncthingState):
        super().__init__(("127.0.0.1", 0), FakeSyncthingHandler)
        self.state = state


class running_syncthing:
    def __init__(self, source: Path):
        self.state = FakeSyncthingState(source)
        self.server = FakeSyncthingServer(self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "running_syncthing":
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])


def write_syncthing_config(path: Path, port: int, source: Path | None = None) -> None:
    path.parent.mkdir(parents=True)
    folder = (
        f'<folder id="{FOLDER_ID}" path="{source}" type="sendreceive" paused="false" />'
        if source is not None
        else ""
    )
    path.write_text(
        "<?xml version=\"1.0\"?>\n"
        "<configuration>"
        f"{folder}"
        f"<gui enabled=\"true\" tls=\"false\"><address>127.0.0.1:{port}</address>"
        f"<apikey>{API_KEY}</apikey></gui>"
        "</configuration>\n",
        encoding="utf-8",
    )


class MoveLibraryTests(unittest.TestCase):
    def test_disconnect_pauses_exact_folder_and_reconnect_restores_only_lattice_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "external" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                write_syncthing_config(config, fixture.port, source)
                disconnected = move_library.prepare_library_disconnect(
                    source,
                    state_file,
                    syncthing_config=config,
                    sync_timeout=1,
                )
                self.assertTrue(disconnected.syncthing_managed)
                self.assertTrue(disconnected.syncthing_running)
                self.assertTrue(disconnected.paused_by_lattice)
                self.assertTrue(fixture.state.folder["paused"])
                saved = json.loads(state_file.read_text(encoding="utf-8"))
                self.assertEqual(saved["folderId"], FOLDER_ID)
                self.assertTrue(saved["resumeRequired"])
                self.assertNotIn(API_KEY, state_file.read_text(encoding="utf-8"))

                reconnected = move_library.reconnect_library(
                    source,
                    state_file,
                    syncthing_config=config,
                    sync_timeout=1,
                )
                self.assertTrue(reconnected.syncthing_running)
                self.assertTrue(reconnected.resumed_by_lattice)
                self.assertFalse(reconnected.resumed_existing_pause)
                self.assertFalse(reconnected.syncthing_started)
                self.assertFalse(reconnected.folder_paused)
                self.assertFalse(fixture.state.folder["paused"])
                self.assertFalse(state_file.exists())
                self.assertGreaterEqual(fixture.state.scans, 1)

    def test_disconnect_preserves_a_pause_not_created_by_lattice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "external" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                fixture.state.folder["paused"] = True
                write_syncthing_config(config, fixture.port, source)
                disconnected = move_library.prepare_library_disconnect(
                    source,
                    state_file,
                    syncthing_config=config,
                    sync_timeout=1,
                )
                self.assertFalse(disconnected.paused_by_lattice)
                self.assertFalse(state_file.exists())
                reconnected = move_library.reconnect_library(
                    source,
                    state_file,
                    syncthing_config=config,
                    sync_timeout=1,
                )
                self.assertFalse(reconnected.resumed_by_lattice)
                self.assertFalse(reconnected.resumed_existing_pause)
                self.assertTrue(reconnected.folder_paused)
                self.assertTrue(fixture.state.folder["paused"])

                resumed = move_library.reconnect_library(
                    source,
                    state_file,
                    syncthing_config=config,
                    resume_existing_pause=True,
                    sync_timeout=1,
                )
                self.assertFalse(resumed.resumed_by_lattice)
                self.assertTrue(resumed.resumed_existing_pause)
                self.assertFalse(resumed.folder_paused)
                self.assertFalse(fixture.state.folder["paused"])
                self.assertGreaterEqual(fixture.state.scans, 1)

    def test_reconnect_rescans_and_waits_when_folder_was_already_unpaused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "external" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                write_syncthing_config(config, fixture.port, source)
                reconnected = move_library.reconnect_library(
                    source,
                    state_file,
                    syncthing_config=config,
                    sync_timeout=1,
                )
                self.assertTrue(reconnected.syncthing_managed)
                self.assertTrue(reconnected.syncthing_running)
                self.assertFalse(reconnected.folder_paused)
                self.assertGreaterEqual(fixture.state.scans, 1)

    def test_reconnect_updates_syncthing_after_windows_changes_drive_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            previous = base / "old-drive" / "Lattice"
            source = base / "new-drive" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            state_file.parent.mkdir()
            state_file.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "folderId": FOLDER_ID,
                        "libraryRoot": str(previous),
                        "resumeRequired": True,
                    }
                ),
                encoding="utf-8",
            )
            with running_syncthing(source) as fixture:
                fixture.state.folder["path"] = str(previous)
                fixture.state.folder["paused"] = True
                write_syncthing_config(config, fixture.port, previous)
                reconnected = move_library.reconnect_library(
                    source,
                    state_file,
                    syncthing_config=config,
                    previous_source=previous,
                    sync_timeout=1,
                )
                self.assertTrue(reconnected.resumed_by_lattice)
                self.assertFalse(reconnected.folder_paused)
                self.assertTrue(move_library._same_path(fixture.state.folder["path"], source))
                self.assertGreaterEqual(fixture.state.scans, 1)
                self.assertFalse(state_file.exists())

    def test_disconnect_accepts_syncthing_v2_empty_state_after_confirmed_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "external" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                fixture.state.paused_status_state = ""
                write_syncthing_config(config, fixture.port, source)
                disconnected = move_library.prepare_library_disconnect(
                    source,
                    state_file,
                    syncthing_config=config,
                    sync_timeout=1,
                )
                self.assertTrue(disconnected.paused_by_lattice)
                self.assertTrue(fixture.state.folder["paused"])

    def test_windows_disconnect_stops_the_dedicated_syncthing_process(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "external" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                write_syncthing_config(config, fixture.port, source)
                with (
                    mock.patch.object(
                        move_library,
                        "_windows_syncthing_listener_process_id",
                        return_value=4321,
                    ),
                    mock.patch.object(move_library, "_wait_for_syncthing_shutdown") as wait,
                ):
                    disconnected = move_library.prepare_library_disconnect(
                        source,
                        state_file,
                        syncthing_config=config,
                        shutdown_syncthing=True,
                        sync_timeout=1,
                    )
                self.assertEqual(fixture.state.shutdowns, 1)
                self.assertTrue(disconnected.syncthing_stopped)
                self.assertTrue(disconnected.paused_by_lattice)
                wait.assert_called_once()
                self.assertEqual(wait.call_args.args[1:], (1, 4321))

    def test_windows_disconnect_stops_syncthing_without_resuming_a_manual_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "external" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                fixture.state.folder["paused"] = True
                write_syncthing_config(config, fixture.port, source)
                with mock.patch.object(move_library, "_wait_for_syncthing_shutdown"):
                    disconnected = move_library.prepare_library_disconnect(
                        source,
                        state_file,
                        syncthing_config=config,
                        shutdown_syncthing=True,
                        sync_timeout=1,
                    )
                self.assertEqual(fixture.state.shutdowns, 1)
                self.assertTrue(disconnected.syncthing_stopped)
                self.assertFalse(disconnected.paused_by_lattice)
                self.assertFalse(state_file.exists())
                self.assertTrue(fixture.state.folder["paused"])

    def test_windows_disconnect_finishes_a_previous_folder_only_disconnect(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "external" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                write_syncthing_config(config, fixture.port, source)
                first = move_library.prepare_library_disconnect(
                    source,
                    state_file,
                    syncthing_config=config,
                    sync_timeout=1,
                )
                self.assertTrue(first.paused_by_lattice)
                self.assertTrue(state_file.exists())

                with mock.patch.object(move_library, "_wait_for_syncthing_shutdown"):
                    finished = move_library.prepare_library_disconnect(
                        source,
                        state_file,
                        syncthing_config=config,
                        shutdown_syncthing=True,
                        sync_timeout=1,
                    )
                self.assertTrue(finished.syncthing_stopped)
                self.assertFalse(finished.paused_by_lattice)
                self.assertTrue(state_file.exists())

                reconnected = move_library.reconnect_library(
                    source,
                    state_file,
                    syncthing_config=config,
                    sync_timeout=1,
                )
                self.assertTrue(reconnected.resumed_by_lattice)
                self.assertFalse(state_file.exists())
                self.assertFalse(fixture.state.folder["paused"])

    def test_shutdown_wait_requires_both_api_and_process_to_stop(self) -> None:
        client = mock.Mock()
        client._request.side_effect = move_library.SyncthingUnavailableError("stopped")
        with mock.patch.object(
            move_library,
            "_syncthing_process_may_be_running",
            return_value=False,
        ):
            move_library._wait_for_syncthing_shutdown(client, timeout=0.1)

        with (
            mock.patch.object(
                move_library,
                "_syncthing_process_may_be_running",
                return_value=True,
            ),
            mock.patch.object(move_library.time, "sleep", return_value=None),
        ):
            with self.assertRaisesRegex(move_library.LibraryMoveError, "still running"):
                move_library._wait_for_syncthing_shutdown(client, timeout=0.001)

    def test_disconnect_requires_running_syncthing_to_verify_up_to_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "external" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                write_syncthing_config(config, fixture.port, source)
            with mock.patch.object(
                move_library,
                "_syncthing_process_may_be_running",
                return_value=False,
            ):
                with self.assertRaisesRegex(move_library.LibraryMoveError, "verify.*Up to Date"):
                    move_library.prepare_library_disconnect(
                        source,
                        state_file,
                        syncthing_config=config,
                        sync_timeout=0.1,
                    )
            self.assertFalse(state_file.exists())

    def test_disconnect_never_calls_an_unreachable_api_safe_while_syncthing_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "external" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                write_syncthing_config(config, fixture.port, source)
            with mock.patch.object(
                move_library,
                "_syncthing_process_may_be_running",
                return_value=True,
            ):
                with self.assertRaisesRegex(move_library.LibraryMoveError, "still running"):
                    move_library.prepare_library_disconnect(
                        source,
                        state_file,
                        syncthing_config=config,
                        sync_timeout=0.1,
                    )

    def test_disconnect_state_must_stay_outside_synchronized_library(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "Lattice"
            make_library(source, synced=False)
            with self.assertRaisesRegex(move_library.LibraryMoveError, "must stay off"):
                move_library.prepare_library_disconnect(
                    source,
                    source / "reconnect.json",
                )

    def test_unsynced_library_moves_with_hidden_files_and_verified_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            external = base / "external"
            destination = external / "Lattice"
            external.mkdir()
            make_library(source, synced=False)
            original = (source / "books" / "large.pdf").read_bytes()

            events: list[tuple[str, dict[str, object]]] = []
            result = move_library.move_library(
                source,
                destination,
                report=lambda event, **fields: events.append((event, fields)),
            )

            self.assertFalse(source.exists())
            self.assertEqual((destination / "books" / "large.pdf").read_bytes(), original)
            self.assertTrue((destination / ".git" / "HEAD").is_file())
            self.assertTrue(result.source_removed)
            self.assertFalse(result.syncthing_managed)
            self.assertTrue(any(event == "progress" for event, _ in events))

    def test_synced_library_preserves_folder_id_redirects_and_rescans(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            external = base / "external"
            destination = external / "Lattice"
            config = base / "syncthing" / "config.xml"
            external.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                write_syncthing_config(config, fixture.port)
                result = move_library.move_library(
                    source,
                    destination,
                    syncthing_config=config,
                    sync_timeout=1,
                )

                self.assertTrue(
                    move_library._same_path(Path(fixture.state.folder["path"]), destination)
                )
                self.assertFalse(fixture.state.folder["paused"])
                self.assertGreaterEqual(fixture.state.scans, 1)
            self.assertTrue((destination / ".stfolder" / "marker").is_file())
            self.assertTrue(result.syncthing_managed)
            self.assertFalse(source.exists())

    def test_copy_failure_restores_pause_state_and_removes_staging(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            external = base / "external"
            destination = external / "Lattice"
            config = base / "syncthing" / "config.xml"
            external.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                write_syncthing_config(config, fixture.port)
                with mock.patch.object(
                    move_library,
                    "_copy_file_verified",
                    side_effect=move_library.LibraryMoveError("fixture copy failure"),
                ):
                    with self.assertRaisesRegex(move_library.LibraryMoveError, "fixture copy failure"):
                        move_library.move_library(
                            source,
                            destination,
                            syncthing_config=config,
                            sync_timeout=1,
                        )
                self.assertTrue(move_library._same_path(Path(fixture.state.folder["path"]), source))
                self.assertFalse(fixture.state.folder["paused"])
            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())
            self.assertEqual(list(external.glob(".*.lattice-moving-*")), [])

    def test_source_change_during_copy_preserves_original_and_discards_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            external = base / "external"
            destination = external / "Lattice"
            external.mkdir()
            make_library(source, synced=False)
            original_copy = move_library._copy_plan

            def copy_then_change(plan: move_library.MovePlan, report: object) -> dict[Path, bytes]:
                digests = original_copy(plan, report)  # type: ignore[arg-type]
                (source / "books" / "late-arrival.pdf").write_bytes(b"late")
                return digests

            with mock.patch.object(move_library, "_copy_plan", side_effect=copy_then_change):
                with self.assertRaisesRegex(move_library.LibraryMoveError, "changed while"):
                    move_library.move_library(source, destination)
            self.assertTrue((source / "books" / "late-arrival.pdf").is_file())
            self.assertFalse(destination.exists())

    def test_post_redirect_failure_rolls_syncthing_back_and_keeps_both_copies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            external = base / "external"
            destination = external / "Lattice"
            config = base / "syncthing" / "config.xml"
            external.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                fixture.state.fail_after_redirect = True
                write_syncthing_config(config, fixture.port)
                with self.assertRaisesRegex(move_library.LibraryMoveError, "did not return"):
                    move_library.move_library(
                        source,
                        destination,
                        syncthing_config=config,
                        sync_timeout=0.1,
                    )
                self.assertTrue(move_library._same_path(Path(fixture.state.folder["path"]), source))
                self.assertFalse(fixture.state.folder["paused"])
            self.assertTrue(source.exists())
            self.assertTrue(destination.exists())

    def test_ambiguous_pause_response_restores_original_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            external = base / "external"
            destination = external / "Lattice"
            config = base / "syncthing" / "config.xml"
            external.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                fixture.state.fail_pause_response_once = True
                write_syncthing_config(config, fixture.port)
                with self.assertRaises(move_library.LibraryMoveError):
                    move_library.move_library(
                        source,
                        destination,
                        syncthing_config=config,
                        sync_timeout=1,
                    )
                self.assertTrue(move_library._same_path(fixture.state.folder["path"], source))
                self.assertFalse(fixture.state.folder["paused"])
            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())

    def test_ambiguous_redirect_response_restores_path_and_preserves_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            external = base / "external"
            destination = external / "Lattice"
            config = base / "syncthing" / "config.xml"
            external.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                fixture.state.fail_redirect_response_once = True
                write_syncthing_config(config, fixture.port)
                with self.assertRaises(move_library.LibraryMoveError):
                    move_library.move_library(
                        source,
                        destination,
                        syncthing_config=config,
                        sync_timeout=1,
                    )
                self.assertTrue(move_library._same_path(fixture.state.folder["path"], source))
                self.assertFalse(fixture.state.folder["paused"])
            self.assertTrue(source.exists())
            self.assertTrue(destination.exists())

    def test_syncthing_api_redirect_is_refused_without_forwarding_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            external = base / "external"
            destination = external / "Lattice"
            config = base / "syncthing" / "config.xml"
            external.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                fixture.state.redirect_folder_request = True
                write_syncthing_config(config, fixture.port)
                with self.assertRaises(move_library.LibraryMoveError):
                    move_library.move_library(
                        source,
                        destination,
                        syncthing_config=config,
                        sync_timeout=1,
                    )
                self.assertEqual(fixture.state.redirect_leak_requests, 0)
            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())

    def test_move_rejects_destination_inside_source_and_running_app_inside_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            make_library(source, synced=False)
            with self.assertRaisesRegex(move_library.LibraryMoveError, "cannot contain"):
                move_library.build_move_plan(source, source / "external" / "Lattice")
            with self.assertRaisesRegex(move_library.LibraryMoveError, "running from inside"):
                move_library.build_move_plan(
                    source,
                    Path(temporary) / "Lattice",
                    protected_paths=[source / "Lattice.exe"],
                )

    def test_cli_reports_machine_readable_completion_without_exposing_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            external = base / "external"
            destination = external / "Lattice"
            external.mkdir()
            make_library(source, synced=False)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = move_library.main(
                    ["--source", str(source), "--destination", str(destination)]
                )
            messages = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(exit_code, 0)
            self.assertEqual(messages[-1]["event"], "complete")
            self.assertTrue(
                move_library._same_path(Path(messages[-1]["destination"]), destination)
            )
            self.assertNotIn(API_KEY, output.getvalue())

    def test_cli_disconnect_and_reconnect_contract_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "external" / "Lattice"
            state_file = base / "local-state" / "external-drive.json"
            config = base / "syncthing" / "config.xml"
            source.parent.mkdir()
            make_library(source, synced=True)
            with running_syncthing(source) as fixture:
                write_syncthing_config(config, fixture.port, source)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    exit_code = move_library.main(
                        [
                            "--operation", "disconnect",
                            "--source", str(source),
                            "--state-file", str(state_file),
                            "--syncthing-config", str(config),
                        ]
                    )
                message = json.loads(output.getvalue().splitlines()[-1])
                self.assertEqual(exit_code, 0)
                self.assertEqual(message["operation"], "disconnect")
                self.assertTrue(message["pausedByLattice"])
                self.assertFalse(message["syncthingStopped"])

                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    exit_code = move_library.main(
                        [
                            "--operation", "reconnect",
                            "--source", str(source),
                            "--state-file", str(state_file),
                            "--syncthing-config", str(config),
                        ]
                    )
                message = json.loads(output.getvalue().splitlines()[-1])
                self.assertEqual(exit_code, 0)
                self.assertEqual(message["operation"], "reconnect")
                self.assertTrue(message["resumedByLattice"])
                self.assertFalse(message["resumedExistingPause"])
                self.assertFalse(message["folderPaused"])
                self.assertNotIn(API_KEY, output.getvalue())


if __name__ == "__main__":
    unittest.main()
