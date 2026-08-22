from __future__ import annotations

import hashlib
import http.client
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_ui  # noqa: E402


PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"


def distinct_pdf(label: str) -> bytes:
    return f"%PDF-1.4\n% {label}\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n".encode()


def ready_ai_status() -> dict[str, object]:
    return {
        "available": True,
        "authenticated": True,
        "ready": True,
        "model": library_ui.AI_MODEL,
        "message": "ready",
    }


def enriched_metadata(title: str) -> dict[str, object]:
    return {
        "title": title,
        "authors": ["A. Author"],
        "year": 2026,
        "edition": "1e",
        "subject_id": "computer-science",
        "topics": ["testing"],
    }


def wait_for_job(
    server: library_ui.LibraryHTTPServer,
    job_id: str,
    statuses: set[str] | frozenset[str] = library_ui.IMPORT_TERMINAL_STATUSES,
    timeout: float = 4,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = server.import_status(job_id)
        if job is not None and job.get("status") in statuses:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {sorted(statuses)}")


def fixture_library(root: Path) -> Path:
    (root / "metadata").mkdir(parents=True)
    for directory in ("books", "papers", "lectures"):
        (root / directory).mkdir()
    (root / "CATALOG.md").write_text("# Empty catalog\n", encoding="utf-8")
    (root / "library-taxonomy.json").write_bytes((ROOT / "library-taxonomy.json").read_bytes())
    ui = root / "fixture-ui"
    ui.mkdir()
    (ui / "index.html").write_text("<!doctype html><title>Lattice fixture</title>", encoding="utf-8")
    (ui / "styles.css").write_text("body{}", encoding="utf-8")
    (ui / "app.js").write_text("'use strict';", encoding="utf-8")
    return ui


class ImportPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "library"
        self.ui = fixture_library(self.root)
        self.enrichment = mock.patch.object(
            library_ui.LibraryHTTPServer,
            "_start_enrichment",
            return_value="test-job",
        )
        self.enrichment.start()
        self.server = library_ui.create_server(0, root=self.root, ui_root=self.ui)
        self.port = int(self.server.server_address[1])
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.enrichment.stop()
        self.temporary.cleanup()

    def request(
        self,
        *,
        body: bytes,
        filename: str,
        kind: str = "book",
        token: str | None = None,
        origin: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        headers = {
            "Content-Type": "application/octet-stream",
            "X-Library-Filename": urllib.parse.quote(filename, safe=""),
            "X-Library-Kind": kind,
        }
        if token is not None:
            headers["X-Library-Token"] = token
        if origin is not None:
            headers["Origin"] = origin
        request = urllib.request.Request(
            self.base + "/api/import", data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read())
            finally:
                error.close()

    def test_import_requires_token_and_loopback_origin(self) -> None:
        status, _payload = self.request(body=PDF_BYTES, filename="Signals.pdf")
        self.assertEqual(status, 403)
        status, _payload = self.request(
            body=PDF_BYTES,
            filename="Signals.pdf",
            token=self.server.action_token,
            origin="https://example.com",
        )
        self.assertEqual(status, 403)

    def test_pdf_import_is_atomic_hashed_and_sidecar_backed(self) -> None:
        status, payload = self.request(
            body=PDF_BYTES,
            filename="Signals & Systems.pdf",
            token=self.server.action_token,
        )
        self.assertEqual(status, 201)
        self.assertTrue(payload["editableMetadata"])
        relative = str(payload["path"])
        self.assertRegex(relative, r"^books/signals-systems-[0-9a-f]{10}\.pdf$")
        installed = self.root / relative
        self.assertEqual(installed.read_bytes(), PDF_BYTES)
        sidecar = library_ui.sidecar_path_for(installed)
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(metadata["path"], relative)
        self.assertEqual(metadata["subject_id"], "other")
        self.assertEqual(
            metadata["access"],
            "User-provided local copy; redistribution not authorized",
        )
        self.assertEqual(list((self.root / "books").glob("*.part")), [])
        self.assertEqual(list((self.root / "books").glob(".syncthing.*.tmp")), [])

        status, duplicate = self.request(
            body=PDF_BYTES,
            filename="A different filename.pdf",
            token=self.server.action_token,
        )
        self.assertEqual(status, 201)
        self.assertTrue(duplicate["duplicate"])
        self.assertTrue(duplicate["editableMetadata"])
        self.assertEqual(duplicate["path"], relative)
        self.assertEqual(len(list((self.root / "books").glob("*.pdf"))), 1)

        unmanaged = self.root / "papers" / "unmanaged.pdf"
        unmanaged.write_bytes(distinct_pdf("unmanaged"))
        library = library_ui.build_library(self.root)
        works = {work["localPath"]: work for work in library["works"]}
        self.assertTrue(works[relative]["editableMetadata"])
        self.assertFalse(works["papers/unmanaged.pdf"]["editableMetadata"])

    def test_bad_magic_traversal_and_unsupported_files_are_rejected(self) -> None:
        for filename, body in (
            ("not-a-pdf.pdf", b"not a pdf"),
            ("../escape.pdf", PDF_BYTES),
            ("archive.zip", b"PK"),
        ):
            with self.subTest(filename=filename):
                status, _payload = self.request(
                    body=body,
                    filename=filename,
                    token=self.server.action_token,
                )
                self.assertEqual(status, 400)
        self.assertEqual(list((self.root / "books").glob("*.part")), [])
        self.assertEqual(list((self.root / "books").glob(".syncthing.*.tmp")), [])

    def test_atomic_json_writes_use_syncthing_reserved_temporary_names(self) -> None:
        target = self.root / "books" / "fixture.pdf.library.json"
        observed: list[tuple[Path, Path]] = []

        def observe_replace(source: str | Path, destination: str | Path) -> None:
            observed.append((Path(source), Path(destination)))

        with mock.patch.object(library_ui.os, "replace", side_effect=observe_replace):
            library_ui._atomic_write_json(target, {"fixture": True})
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][1], target)
        self.assertRegex(observed[0][0].name, r"^\.syncthing\.[0-9a-f]+\.tmp$")
        self.assertFalse(observed[0][0].exists())

    def test_worker_sidecar_reread_uses_the_full_bounded_validator(self) -> None:
        _status, imported = self.request(
            body=PDF_BYTES,
            filename="Peer replacement.pdf",
            token=self.server.action_token,
        )
        relative = str(imported["path"])
        sidecar = library_ui.sidecar_path_for(self.root / relative)
        sidecar.write_bytes(b"{" + b" " * library_ui.MAX_SIDECAR_BYTES + b"}")
        with self.server._import_lock, self.assertRaisesRegex(
            ValueError,
            "Metadata sidecar is unavailable",
        ):
            self.server._read_import_sidecar_locked(relative)

    def test_manual_metadata_edits_cannot_change_rights_or_hash(self) -> None:
        _status, imported = self.request(
            body=PDF_BYTES,
            filename="Circuit Analysis.pdf",
            kind="lecture",
            token=self.server.action_token,
        )
        relative = str(imported["path"])
        original = json.loads(
            library_ui.sidecar_path_for(self.root / relative).read_text(encoding="utf-8")
        )
        body = json.dumps(
            {
                "path": relative,
                "title": "Circuit Analysis",
                "authors": "A. Engineer, B. Scientist",
                "year": "2026",
                "edition": "2e",
                "subjectId": "electrical-engineering",
                "topics": ["circuits", "signals"],
                "access": "Public domain",
                "sha256": "fake",
            }
        ).encode()
        request = urllib.request.Request(
            self.base + "/api/metadata",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Library-Token": self.server.action_token,
            },
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            updated = json.loads(response.read())["metadata"]
        self.assertEqual(updated["subject_id"], "electrical-engineering")
        self.assertEqual(updated["authors"], ["A. Engineer", "B. Scientist"])
        self.assertEqual(updated["access"], original["access"])
        self.assertEqual(updated["sha256"], original["sha256"])
        self.assertEqual(updated["metadata_status"], "manual")

    def test_import_rejects_symlinked_shelf_destination(self) -> None:
        books = self.root / "books"
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir()
        books.rmdir()
        try:
            books.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"directory symlinks are unavailable: {error}")

        status, payload = self.request(
            body=PDF_BYTES,
            filename="Outside.pdf",
            token=self.server.action_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("symlink or junction", str(payload["error"]))
        self.assertEqual(list(outside.iterdir()), [])

    def test_synced_sidecar_integrity_is_validated_and_duplicate_repairs_it(self) -> None:
        status, imported = self.request(
            body=PDF_BYTES,
            filename="Integrity.pdf",
            token=self.server.action_token,
        )
        self.assertEqual(status, 201)
        relative = str(imported["path"])
        payload = self.root / relative
        sidecar = library_ui.sidecar_path_for(payload)

        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertIn(relative, records)
        self.assertEqual(warnings, [])

        tampered = json.loads(sidecar.read_text(encoding="utf-8"))
        tampered["sha256"] = "0" * 64
        sidecar.write_text(json.dumps(tampered), encoding="utf-8")
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertNotIn(relative, records)
        self.assertTrue(any("SHA-256 does not match" in warning for warning in warnings))

        status, duplicate = self.request(
            body=PDF_BYTES,
            filename="Integrity duplicate.pdf",
            token=self.server.action_token,
        )
        self.assertEqual(status, 201)
        self.assertTrue(duplicate["duplicate"])
        repaired = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(repaired["sha256"], library_ui._sha256_file(payload))
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertIn(relative, records)
        self.assertEqual(warnings, [])

    def test_synced_sidecars_are_size_schema_and_utf8_bounded(self) -> None:
        _status, imported = self.request(
            body=PDF_BYTES,
            filename="Bounded.pdf",
            token=self.server.action_token,
        )
        relative = str(imported["path"])
        sidecar = library_ui.sidecar_path_for(self.root / relative)
        valid = json.loads(sidecar.read_text(encoding="utf-8"))

        malformed = dict(valid)
        malformed["authors"] = "not-an-array"
        sidecar.write_text(json.dumps(malformed), encoding="utf-8")
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertNotIn(relative, records)
        self.assertTrue(any("authors are invalid" in warning for warning in warnings))

        unknown_subject = dict(valid)
        unknown_subject["subject_id"] = ["not-a-subject"]
        sidecar.write_text(json.dumps(unknown_subject), encoding="utf-8")
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertEqual(records[relative]["subject_id"], "other")
        self.assertTrue(any("Unknown subject" in warning for warning in warnings))

        sidecar.write_bytes(b" " * (library_ui.MAX_SIDECAR_BYTES + 1))
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertNotIn(relative, records)
        self.assertTrue(any("metadata exceeds" in warning for warning in warnings))

        sidecar.write_bytes(b"{\"title\":\xff}")
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertNotIn(relative, records)
        self.assertTrue(any("UTF-8 JSON" in warning for warning in warnings))

    def test_syncthing_conflicts_are_warned_and_payload_copy_is_not_indexed(self) -> None:
        payload_conflict = (
            self.root / "books" / "signals.sync-conflict-20260821-120000-ABCDEF.pdf"
        )
        payload_conflict.write_bytes(PDF_BYTES)
        sidecar_conflict = (
            self.root
            / "books"
            / "signals.pdf.library.sync-conflict-20260821-120000-ABCDEF.json"
        )
        sidecar_conflict.write_text("{}", encoding="utf-8")

        library = library_ui.build_library(self.root)
        self.assertEqual(library["materials"], [])
        self.assertTrue(
            any("payload conflict" in warning for warning in library["metadataWarnings"])
        )
        self.assertTrue(
            any("metadata conflict" in warning for warning in library["metadataWarnings"])
        )

    def test_taxonomy_reload_updates_library_and_future_imports_together(self) -> None:
        taxonomy = {
            "schema_version": 1,
            "default_import_subject_id": "physics",
            "catalog_default_subject_id": "computer-science",
            "subjects": [
                {"id": "computer-science", "name": "Computer Science"},
                {"id": "physics", "name": "Physical Sciences"},
                {"id": "other", "name": "Other"},
            ],
            "topic_defaults": {},
            "work_assignments": {},
        }
        (self.root / "library-taxonomy.json").write_text(
            json.dumps(taxonomy),
            encoding="utf-8",
        )
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            with urllib.request.urlopen(self.base + "/api/library", timeout=3) as response:
                library = json.loads(response.read())
            if any(subject["name"] == "Physical Sciences" for subject in library["subjects"]):
                break
            time.sleep(0.08)
        else:
            self.fail("Watcher did not reload the taxonomy")
        self.assertEqual(self.server.taxonomy["defaultImportSubjectId"], "physics")

        status, imported = self.request(
            body=PDF_BYTES,
            filename="Mechanics.pdf",
            token=self.server.action_token,
        )
        self.assertEqual(status, 201)
        self.assertEqual(imported["metadata"]["subject_id"], "physics")

        (self.root / "library-taxonomy.json").write_text("{invalid", encoding="utf-8")
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            with urllib.request.urlopen(self.base + "/api/health", timeout=3) as response:
                health = json.loads(response.read())
            if health["refreshError"]:
                break
            time.sleep(0.08)
        else:
            self.fail("Watcher did not report the rejected taxonomy refresh")
        self.assertEqual(self.server.taxonomy["defaultImportSubjectId"], "physics")
        with urllib.request.urlopen(self.base + "/api/library", timeout=3) as response:
            unchanged = json.loads(response.read())
        self.assertTrue(
            any(subject["name"] == "Physical Sciences" for subject in unchanged["subjects"])
        )

    def test_invalid_utf8_json_is_400_and_head_does_not_leak_body(self) -> None:
        request = urllib.request.Request(
            self.base + "/api/metadata",
            data=b"{\"path\":\xff}",
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Library-Token": self.server.action_token,
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("HEAD", "/api/import-status?id=missing")
        missing = connection.getresponse()
        self.assertEqual(missing.status, 404)
        self.assertEqual(missing.read(), b"")
        connection.request("GET", "/api/health")
        health = connection.getresponse()
        self.assertEqual(health.status, 200)
        health.read()
        connection.close()

    def test_import_status_recovers_the_current_job_by_payload_path(self) -> None:
        _status, imported = self.request(
            body=PDF_BYTES,
            filename="Recovered status.pdf",
            token=self.server.action_token,
        )
        relative = str(imported["path"])
        with self.server._job_lock:
            self.server._import_jobs["replacement-job"] = {
                "id": "replacement-job",
                "path": relative,
                "status": "enriching",
                "message": "Recovered after restart",
            }
        query = urllib.parse.urlencode({"id": "obsolete-job", "path": relative})
        with urllib.request.urlopen(
            f"{self.base}/api/import-status?{query}",
            timeout=3,
        ) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["id"], "replacement-job")
        self.assertEqual(payload["path"], relative)


class ImportLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "library"
        self.ui = fixture_library(self.root)
        self.servers: list[library_ui.LibraryHTTPServer] = []
        self.release_events: list[threading.Event] = []

    def tearDown(self) -> None:
        for event in self.release_events:
            event.set()
        for server in reversed(self.servers):
            server.server_close()
        self.temporary.cleanup()

    def new_server(self) -> library_ui.LibraryHTTPServer:
        server = library_ui.create_server(0, root=self.root, ui_root=self.ui)
        self.servers.append(server)
        return server

    def close_server(self, server: library_ui.LibraryHTTPServer) -> None:
        server.server_close()
        self.servers.remove(server)

    def install(
        self,
        server: library_ui.LibraryHTTPServer,
        label: str,
        *,
        kind: str = "book",
    ) -> tuple[dict[str, object], bytes]:
        body = distinct_pdf(label)
        result = server.install_import(
            io.BytesIO(body),
            content_length=len(body),
            encoded_filename=urllib.parse.quote(f"{label}.pdf", safe=""),
            kind=kind,
        )
        return result, body

    def seed_pending(
        self,
        label: str,
        *,
        body: bytes | None = None,
        kind: str = "book",
    ) -> str:
        payload_bytes = body or distinct_pdf(label)
        directory = library_ui.IMPORT_KINDS[kind]
        relative = f"{directory}/{library_ui.slugify(label)}.pdf"
        payload = self.root / relative
        payload.write_bytes(payload_bytes)
        metadata = library_ui._initial_import_metadata(
            relative=relative,
            original_name=f"{label}.pdf",
            kind=kind,
            size=len(payload_bytes),
            digest=hashlib.sha256(payload_bytes).hexdigest(),
            embedded={},
            taxonomy=library_ui.load_taxonomy(self.root),
        )
        library_ui._atomic_write_json(library_ui.sidecar_path_for(payload), metadata)
        return relative

    def wait_for_queue_idle(
        self,
        server: library_ui.LibraryHTTPServer,
        timeout: float = 4,
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if server._enrichment_queue.unfinished_tasks == 0:
                return
            time.sleep(0.01)
        self.fail("enrichment queue did not become idle")

    def manual_edit(self, server: library_ui.LibraryHTTPServer, relative: str, title: str) -> None:
        server.update_import_metadata(
            {
                "path": relative,
                "title": title,
                "authors": ["Manual Author"],
                "year": 2025,
                "edition": "manual",
                "subjectId": "other",
                "topics": ["manual"],
            }
        )

    def test_manual_edit_wins_successful_enrichment_race(self) -> None:
        started = threading.Event()
        release = threading.Event()
        self.release_events.append(release)

        def blocked_enrichment(*_args: object) -> dict[str, object]:
            started.set()
            self.assertTrue(release.wait(3))
            return enriched_metadata("AI title")

        with mock.patch.object(
            library_ui, "codex_login_status", return_value=ready_ai_status()
        ), mock.patch.object(
            library_ui, "enrich_metadata_with_codex", side_effect=blocked_enrichment
        ):
            server = self.new_server()
            imported, _body = self.install(server, "manual-success-race")
            self.assertTrue(started.wait(2))
            relative = str(imported["path"])
            self.manual_edit(server, relative, "Manual title")
            release.set()
            self.wait_for_queue_idle(server)
            job = wait_for_job(server, str(imported["jobId"]))

        metadata = json.loads(
            library_ui.sidecar_path_for(self.root / relative).read_text(encoding="utf-8")
        )
        self.assertEqual(job["status"], "manual")
        self.assertEqual(metadata["title"], "Manual title")
        self.assertEqual(metadata["metadata_status"], "manual")

    def test_manual_edit_wins_failed_enrichment_race(self) -> None:
        started = threading.Event()
        release = threading.Event()
        self.release_events.append(release)

        def failing_enrichment(*_args: object) -> dict[str, object]:
            started.set()
            self.assertTrue(release.wait(3))
            raise RuntimeError("model unavailable")

        with mock.patch.object(
            library_ui, "codex_login_status", return_value=ready_ai_status()
        ), mock.patch.object(
            library_ui, "enrich_metadata_with_codex", side_effect=failing_enrichment
        ):
            server = self.new_server()
            imported, _body = self.install(server, "manual-failure-race")
            self.assertTrue(started.wait(2))
            relative = str(imported["path"])
            self.manual_edit(server, relative, "Manual survives failure")
            release.set()
            self.wait_for_queue_idle(server)
            job = wait_for_job(server, str(imported["jobId"]))

        metadata = json.loads(
            library_ui.sidecar_path_for(self.root / relative).read_text(encoding="utf-8")
        )
        self.assertEqual(job["status"], "manual")
        self.assertEqual(metadata["title"], "Manual survives failure")
        self.assertEqual(metadata["metadata_status"], "manual")

    def test_bounded_worker_uses_deterministic_capacity_fallback(self) -> None:
        started = threading.Event()
        release = threading.Event()
        self.release_events.append(release)
        calls = 0

        def blocked_first(metadata: dict[str, object], _taxonomy: object) -> dict[str, object]:
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                self.assertTrue(release.wait(3))
            return enriched_metadata(f"AI {metadata['title']}")

        with mock.patch.object(library_ui, "AI_QUEUE_CAPACITY", 1), mock.patch.object(
            library_ui, "codex_login_status", return_value=ready_ai_status()
        ), mock.patch.object(
            library_ui, "enrich_metadata_with_codex", side_effect=blocked_first
        ):
            server = self.new_server()
            first, _body = self.install(server, "capacity-one")
            self.assertTrue(started.wait(2))
            second, _body = self.install(server, "capacity-two")
            third, _body = self.install(server, "capacity-three")

            third_job = wait_for_job(server, str(third["jobId"]))
            third_metadata = json.loads(
                library_ui.sidecar_path_for(self.root / str(third["path"])).read_text(
                    encoding="utf-8"
                )
            )
            workers = [
                thread
                for thread in threading.enumerate()
                if thread.name.startswith("lattice-ai-")
            ]
            self.assertEqual(workers, [server._ai_worker])
            self.assertEqual(third_job["status"], "fallback")
            self.assertEqual(third_metadata["metadata_status"], "local-fallback")
            self.assertEqual(third_metadata["ai"]["status"], "queue-full")

            release.set()
            self.assertEqual(wait_for_job(server, str(first["jobId"]))["status"], "complete")
            self.assertEqual(wait_for_job(server, str(second["jobId"]))["status"], "complete")
            self.wait_for_queue_idle(server)

    def test_pending_sidecar_is_recovered_after_restart(self) -> None:
        with mock.patch.object(
            library_ui.LibraryHTTPServer,
            "_start_enrichment",
            return_value="interrupted-job",
        ):
            first_server = self.new_server()
            imported, _body = self.install(first_server, "restart-recovery")
        relative = str(imported["path"])
        self.close_server(first_server)
        pending = json.loads(
            library_ui.sidecar_path_for(self.root / relative).read_text(encoding="utf-8")
        )
        self.assertEqual(pending["metadata_status"], "pending-ai")

        with mock.patch.object(
            library_ui, "codex_login_status", return_value=ready_ai_status()
        ), mock.patch.object(
            library_ui,
            "enrich_metadata_with_codex",
            return_value=enriched_metadata("Recovered title"),
        ):
            second_server = self.new_server()
            deadline = time.monotonic() + 3
            job_id = ""
            while time.monotonic() < deadline and not job_id:
                with second_server._job_lock:
                    job_id = next(
                        (
                            str(job["id"])
                            for job in second_server._import_jobs.values()
                            if job.get("path") == relative
                        ),
                        "",
                    )
                if not job_id:
                    time.sleep(0.01)
            self.assertTrue(job_id)
            self.assertEqual(wait_for_job(second_server, job_id)["status"], "complete")

        recovered = json.loads(
            library_ui.sidecar_path_for(self.root / relative).read_text(encoding="utf-8")
        )
        self.assertEqual(recovered["title"], "Recovered title")
        self.assertEqual(recovered["metadata_status"], "ai-enriched")

    def test_duplicate_pending_import_reuses_a_live_recovery_job(self) -> None:
        body = distinct_pdf("duplicate-pending")
        with mock.patch.object(
            library_ui, "codex_login_status", return_value=ready_ai_status()
        ), mock.patch.object(
            library_ui,
            "enrich_metadata_with_codex",
            return_value=enriched_metadata("Recovered duplicate"),
        ):
            server = self.new_server()
            relative = self.seed_pending("duplicate-pending", body=body)
            duplicate = server.install_import(
                io.BytesIO(body),
                content_length=len(body),
                encoded_filename="another-name.pdf",
                kind="book",
            )
            self.assertTrue(duplicate["duplicate"])
            self.assertEqual(duplicate["path"], relative)
            self.assertTrue(duplicate["jobId"])
            self.assertEqual(
                wait_for_job(server, str(duplicate["jobId"]))["status"],
                "complete",
            )

    def test_unexpected_worker_and_fallback_write_failure_is_terminal(self) -> None:
        server = self.new_server()
        relative = self.seed_pending("terminal-worker-failure")
        server._run_enrichment = mock.Mock(side_effect=RuntimeError("unexpected worker error"))
        with mock.patch.object(
            library_ui, "_atomic_write_json", side_effect=OSError("disk full")
        ):
            job_id = server._start_enrichment(relative)
            job = wait_for_job(server, job_id)
        self.assertEqual(job["status"], "failed")
        self.assertIn("fallback metadata could not be saved", str(job["message"]))


class CodexMetadataTests(unittest.TestCase):
    def test_descriptive_validation_matches_the_persisted_sidecar_contract(self) -> None:
        taxonomy = library_ui.load_taxonomy(ROOT)
        value = {
            "title": "Untitled notes",
            "authors": [],
            "year": None,
            "edition": "",
            "subjectId": "mathematics",
            "topics": [],
        }
        normalized = library_ui._validated_descriptive_metadata(value, taxonomy)
        self.assertEqual(normalized["authors"], ["Unknown author"])

        with self.assertRaisesRegex(ValueError, "publication year"):
            library_ui._validated_descriptive_metadata({**value, "year": True}, taxonomy)
        with self.assertRaisesRegex(ValueError, "subject"):
            library_ui._validated_descriptive_metadata({**value, "subjectId": []}, taxonomy)

    def test_malformed_or_missing_required_taxonomy_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            malformed = json.loads((ROOT / "library-taxonomy.json").read_text(encoding="utf-8"))
            malformed["default_import_subject_id"] = []
            (root / "library-taxonomy.json").write_text(
                json.dumps(malformed),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "default_import_subject_id"):
                library_ui.load_taxonomy(root, required=True)
            malformed["default_import_subject_id"] = "other"
            malformed["schema_version"] = True
            (root / "library-taxonomy.json").write_text(
                json.dumps(malformed),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "schema_version"):
                library_ui.load_taxonomy(root, required=True)
            (root / "library-taxonomy.json").unlink()
            with self.assertRaisesRegex(ValueError, "Required library taxonomy"):
                library_ui.load_taxonomy(root, required=True)

    def test_pdf_page_tokens_are_never_treated_as_bibliographic_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            path = Path(temporary_name) / "private.pdf"
            path.write_bytes(
                b"%PDF-1.4\n"
                b"1 0 obj<</Length 61>>stream\n"
                b"BT /F1 12 Tf (PRIVATE PAGE CONTENT /Title (Do Not Send)) Tj ET\n"
                b"endstream endobj\n%%EOF\n"
            )
            self.assertEqual(library_ui._validate_import_payload(path, ".pdf"), {})

    def test_luna_receives_only_filename_and_embedded_metadata(self) -> None:
        taxonomy = library_ui.load_taxonomy(ROOT)
        metadata = {
            "path": "books/private-text.pdf",
            "material_type": "book",
            "embedded_metadata": {"title": "Private Text", "authors": ["A. Author"]},
        }
        seen_command: list[str] = []
        seen_prompt = ""

        def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            nonlocal seen_command, seen_prompt
            seen_command = command
            seen_prompt = str(kwargs["input"])
            output_index = command.index("--output-last-message") + 1
            Path(command[output_index]).write_text(
                json.dumps(
                    {
                        "title": "Private Text",
                        "authors": ["A. Author"],
                        "year": 2024,
                        "edition": "1e",
                        "subjectId": "mathematics",
                        "topics": ["proofs"],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(
            library_ui,
            "_codex_executable_command",
            side_effect=lambda arguments: ["codex", *arguments],
        ), mock.patch.object(library_ui.subprocess, "run", side_effect=fake_run):
            result = library_ui.enrich_metadata_with_codex(metadata, taxonomy)
        self.assertEqual(result["subject_id"], "mathematics")
        self.assertIn("--ignore-user-config", seen_command)
        self.assertEqual(seen_command[seen_command.index("--model") + 1], "gpt-5.6-luna")
        self.assertEqual(seen_command[seen_command.index("--sandbox") + 1], "read-only")
        self.assertIn('model_reasoning_effort="low"', seen_command)
        disabled = {
            seen_command[index + 1]
            for index, value in enumerate(seen_command[:-1])
            if value == "--disable"
        }
        self.assertTrue(
            {
                "shell_tool",
                "unified_exec",
                "view_image",
                "browser_use",
                "computer_use",
                "apps",
                "remote_plugin",
                "plugin_sharing",
                "image_generation",
                "skill_search",
                "multi_agent",
                "multi_agent_v2",
                "code_mode_host",
                "workspace_dependencies",
            }.issubset(disabled)
        )
        self.assertIn("private-text.pdf", seen_prompt)
        self.assertIn("Private Text", seen_prompt)
        self.assertNotIn(str(ROOT), seen_prompt)
        self.assertNotIn("sha256", seen_prompt.lower())


if __name__ == "__main__":
    unittest.main()
