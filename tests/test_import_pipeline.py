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
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_ui  # noqa: E402


PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"


def kobo_epub_bytes() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0"><rootfiles><rootfile full-path="EPUB/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""",
        )
        archive.writestr(
            "EPUB/book.opf",
            """<package xmlns="http://www.idpf.org/2007/opf" version="3.0"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Computational Imaging</dc:title><dc:creator>Fixture Author</dc:creator><dc:language>en</dc:language></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/><item id="kobo" href="js/kobo.js" media-type="text/javascript"/></manifest><spine><itemref idref="chapter"/></spine></package>""",
        )
        archive.writestr(
            "EPUB/chapter.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><head><script src="js/kobo.js"></script></head><body>Readable text</body></html>""",
        )
        archive.writestr("EPUB/js/kobo.js", "document.body.textContent = 'executed';")
    return payload.getvalue()


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
        "subject_ids": ["computer-science", "mathematics"],
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
        self.assertEqual(payload["metadata"]["subjectIds"], ["other"])
        self.assertEqual(payload["metadata"]["subjectId"], "other")
        self.assertEqual(payload["metadata"]["subject_id"], "other")
        sidecar = library_ui.sidecar_path_for(installed)
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(metadata["path"], relative)
        self.assertEqual(metadata["schema_version"], 2)
        self.assertEqual(metadata["subject_ids"], ["other"])
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

    def test_kobo_epub_imports_while_embedded_javascript_remains_inert(self) -> None:
        status, imported = self.request(
            body=kobo_epub_bytes(),
            filename="Computational Imaging.epub",
            token=self.server.action_token,
        )
        self.assertEqual(status, 201)
        relative = str(imported["path"])
        self.assertTrue(relative.startswith("books/computational-imaging-"))
        self.assertEqual(imported["metadata"]["title"], "Computational Imaging")
        deadline = time.monotonic() + 4
        while relative not in self.server.allowed_paths and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn(relative, self.server.allowed_paths)
        package, media_types, _path = self.server.epub_package(relative)
        self.assertEqual(len(package["chapters"]), 1)
        self.assertNotIn("EPUB/js/kobo.js", media_types)

        key = library_ui.encode_epub_key(relative)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(
                f"{self.base}/epub/{key}/EPUB/js/kobo.js",
                timeout=3,
            )
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()

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

    def test_windows_publish_uses_nonreplacing_rename_without_hard_links(self) -> None:
        source = self.root / "books" / ".syncthing.fixture.tmp"
        destination = self.root / "books" / "fixture.pdf"
        source.write_bytes(PDF_BYTES)

        with (
            mock.patch.object(library_ui.os, "name", "nt"),
            mock.patch.object(library_ui.os, "rename") as rename,
            mock.patch.object(library_ui.os, "link") as link,
        ):
            library_ui._publish_new_path(source, destination)

        rename.assert_called_once_with(source, destination)
        link.assert_not_called()

    def test_windows_publish_propagates_noncollision_errors(self) -> None:
        source = self.root / "books" / ".syncthing.fixture.tmp"
        destination = self.root / "books" / "fixture.pdf"
        source.write_bytes(PDF_BYTES)

        with (
            mock.patch.object(library_ui.os, "name", "nt"),
            mock.patch.object(
                library_ui.os,
                "rename",
                side_effect=PermissionError("volume is read-only"),
            ),
            self.assertRaisesRegex(PermissionError, "volume is read-only"),
        ):
            library_ui._publish_new_path(source, destination)

    def test_publish_new_never_replaces_an_existing_destination(self) -> None:
        source = self.root / "books" / ".syncthing.fixture.tmp"
        destination = self.root / "books" / "fixture.pdf"
        source.write_bytes(PDF_BYTES)
        existing = distinct_pdf("peer-created")
        destination.write_bytes(existing)

        with self.assertRaises(FileExistsError):
            library_ui._publish_new_path(source, destination)

        self.assertEqual(destination.read_bytes(), existing)
        self.assertEqual(source.read_bytes(), PDF_BYTES)

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
                "subjectIds": ["electrical-engineering", "computer-engineering"],
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
        self.assertEqual(
            updated["subject_ids"],
            ["electrical-engineering", "computer-engineering"],
        )
        self.assertEqual(updated["authors"], ["A. Engineer", "B. Scientist"])
        self.assertEqual(updated["access"], original["access"])
        self.assertEqual(updated["sha256"], original["sha256"])
        self.assertEqual(updated["metadata_status"], "manual")
        work = next(
            work
            for work in library_ui.build_library(self.root)["works"]
            if work["localPath"] == relative
        )
        self.assertEqual(
            work["subjectIds"],
            ["electrical-engineering", "computer-engineering"],
        )
        self.assertEqual(
            work["subjects"],
            ["Electrical Engineering", "Computer Engineering"],
        )
        self.assertEqual(work["subjectId"], "electrical-engineering")

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

        invalid_sidecar_bytes = sidecar.read_bytes()
        status, duplicate = self.request(
            body=PDF_BYTES,
            filename="Integrity duplicate.pdf",
            token=self.server.action_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("metadata is invalid or newer", duplicate["error"])
        self.assertEqual(sidecar.read_bytes(), invalid_sidecar_bytes)
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertNotIn(relative, records)
        self.assertTrue(any("SHA-256 does not match" in warning for warning in warnings))

        future = json.loads(invalid_sidecar_bytes)
        future["schema_version"] = 3
        future_sidecar_bytes = json.dumps(future, sort_keys=True).encode("utf-8")
        sidecar.write_bytes(future_sidecar_bytes)
        status, future_duplicate = self.request(
            body=PDF_BYTES,
            filename="Future duplicate.pdf",
            token=self.server.action_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("metadata is invalid or newer", future_duplicate["error"])
        self.assertEqual(sidecar.read_bytes(), future_sidecar_bytes)

    def test_orphan_sidecar_is_never_overwritten_during_import(self) -> None:
        body = distinct_pdf("orphan-sidecar")
        digest = hashlib.sha256(body).hexdigest()
        first_payload = self.root / "books" / f"orphan-sidecar-{digest[:10]}.pdf"
        orphan = library_ui.sidecar_path_for(first_payload)
        orphan_bytes = b'{"schema_version":3,"peer":"arrived-first"}\n'
        orphan.write_bytes(orphan_bytes)

        status, imported = self.request(
            body=body,
            filename="Orphan sidecar.pdf",
            token=self.server.action_token,
        )

        self.assertEqual(status, 201)
        self.assertEqual(
            imported["path"],
            f"books/orphan-sidecar-{digest[:16]}.pdf",
        )
        self.assertEqual(orphan.read_bytes(), orphan_bytes)
        self.assertFalse(first_payload.exists())
        self.assertTrue((self.root / str(imported["path"])).is_file())

    def test_both_deterministic_sidecar_paths_block_without_overwrite(self) -> None:
        body = distinct_pdf("two-orphan-sidecars")
        digest = hashlib.sha256(body).hexdigest()
        sidecars: list[tuple[Path, bytes]] = []
        for length in (10, 16):
            payload = self.root / "books" / f"blocked-{digest[:length]}.pdf"
            sidecar = library_ui.sidecar_path_for(payload)
            original = f'{{"schema_version":3,"length":{length}}}\n'.encode()
            sidecar.write_bytes(original)
            sidecars.append((sidecar, original))

        status, response = self.request(
            body=body,
            filename="Blocked.pdf",
            token=self.server.action_token,
        )

        self.assertEqual(status, 400)
        self.assertIn("occupies the deterministic import path", response["error"])
        for sidecar, original in sidecars:
            self.assertEqual(sidecar.read_bytes(), original)
            self.assertFalse(
                sidecar.with_name(sidecar.name[: -len(library_ui.SIDECAR_SUFFIX)]).exists()
            )

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

        floating_schema = dict(valid)
        floating_schema["schema_version"] = 2.0
        sidecar.write_text(json.dumps(floating_schema), encoding="utf-8")
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertNotIn(relative, records)
        self.assertTrue(any("schema_version" in warning for warning in warnings))

        unknown_subject = dict(valid)
        unknown_subject["subject_ids"] = ["not-a-subject"]
        sidecar.write_text(json.dumps(unknown_subject), encoding="utf-8")
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertEqual(records[relative]["subject_ids"], ["not-a-subject"])
        self.assertTrue(any("were preserved" in warning for warning in warnings))
        library = library_ui.build_library(self.root)
        work = next(work for work in library["works"] if work["localPath"] == relative)
        self.assertEqual(work["subjectIds"], ["not-a-subject"])
        self.assertTrue(
            any(
                subject["id"] == "not-a-subject" and subject.get("known") is False
                for subject in library["subjects"]
            )
        )

        sidecar.write_bytes(b" " * (library_ui.MAX_SIDECAR_BYTES + 1))
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertNotIn(relative, records)
        self.assertTrue(any("metadata exceeds" in warning for warning in warnings))

        sidecar.write_bytes(b"{\"title\":\xff}")
        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertNotIn(relative, records)
        self.assertTrue(any("UTF-8 JSON" in warning for warning in warnings))

    def test_version_one_sidecars_are_read_and_upgraded_on_edit(self) -> None:
        _status, imported = self.request(
            body=PDF_BYTES,
            filename="Legacy subject.pdf",
            token=self.server.action_token,
        )
        relative = str(imported["path"])
        sidecar = library_ui.sidecar_path_for(self.root / relative)
        legacy = json.loads(sidecar.read_text(encoding="utf-8"))
        legacy["schema_version"] = 1
        legacy["subject_id"] = "electrical-engineering"
        legacy.pop("subject_ids")
        sidecar.write_text(json.dumps(legacy), encoding="utf-8")
        legacy_bytes = sidecar.read_bytes()

        records, warnings = library_ui._read_synced_sidecars(self.root)
        self.assertEqual(warnings, [])
        self.assertEqual(records[relative]["schema_version"], 2)
        self.assertEqual(records[relative]["subject_ids"], ["electrical-engineering"])
        self.assertEqual(sidecar.read_bytes(), legacy_bytes)

        updated = self.server.update_import_metadata(
            {
                "path": relative,
                "title": "Legacy subject",
                "authors": ["A. Author"],
                "year": 2024,
                "edition": "1e",
                "subjectId": "mathematics",
                "topics": ["migration"],
            }
        )
        self.assertEqual(updated["schema_version"], 2)
        self.assertEqual(updated["subject_ids"], ["mathematics"])
        persisted = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertNotIn("subject_id", persisted)
        self.assertEqual(persisted["subject_ids"], ["mathematics"])

    def test_stale_taxonomy_preserves_future_subjects_across_edits(self) -> None:
        _status, imported = self.request(
            body=PDF_BYTES,
            filename="Future taxonomy.pdf",
            token=self.server.action_token,
        )
        relative = str(imported["path"])
        sidecar = library_ui.sidecar_path_for(self.root / relative)
        future = json.loads(sidecar.read_text(encoding="utf-8"))
        future["subject_ids"] = ["computer-science", "quantum-engineering"]
        sidecar.write_text(json.dumps(future), encoding="utf-8")

        updated = self.server.update_import_metadata(
            {
                "path": relative,
                "title": "Future taxonomy",
                "authors": ["A. Author"],
                "year": 2026,
                "edition": "1e",
                "subjectIds": ["mathematics"],
                "topics": ["migration"],
            }
        )
        self.assertEqual(
            updated["subject_ids"],
            ["mathematics", "quantum-engineering"],
        )
        persisted = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["subject_ids"],
            ["mathematics", "quantum-engineering"],
        )

        enriched = enriched_metadata("AI title")
        merged = library_ui._merge_descriptive_metadata(
            updated,
            enriched,
            self.server.taxonomy,
        )
        self.assertEqual(
            merged["subject_ids"],
            ["computer-science", "mathematics", "quantum-engineering"],
        )

    def test_edit_with_only_a_future_subject_preserves_it(self) -> None:
        _status, imported = self.request(
            body=distinct_pdf("future-only"),
            filename="Future only.pdf",
            token=self.server.action_token,
        )
        relative = str(imported["path"])
        sidecar = library_ui.sidecar_path_for(self.root / relative)
        future = json.loads(sidecar.read_text(encoding="utf-8"))
        future["subject_ids"] = ["quantum-engineering"]
        sidecar.write_text(json.dumps(future), encoding="utf-8")

        updated = self.server.update_import_metadata(
            {
                "path": relative,
                "title": "Future subject title edit",
                "authors": ["A. Author"],
                "year": 2026,
                "edition": "1e",
                "subjectIds": [],
                "subjectId": "other",
                "topics": ["migration"],
            }
        )

        self.assertEqual(updated["title"], "Future subject title edit")
        self.assertEqual(updated["subject_ids"], ["quantum-engineering"])
        persisted = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(persisted["subject_ids"], ["quantum-engineering"])

    def test_subject_merge_limit_rejects_without_writing(self) -> None:
        _status, imported = self.request(
            body=distinct_pdf("subject-limit"),
            filename="Subject limit.pdf",
            token=self.server.action_token,
        )
        relative = str(imported["path"])
        sidecar = library_ui.sidecar_path_for(self.root / relative)
        crowded = json.loads(sidecar.read_text(encoding="utf-8"))
        crowded["subject_ids"] = [
            f"future-subject-{index}" for index in range(library_ui.MAX_ASSIGNED_SUBJECTS)
        ]
        sidecar.write_text(json.dumps(crowded, sort_keys=True), encoding="utf-8")
        before = sidecar.read_bytes()

        with self.assertRaisesRegex(ValueError, "exceed.*64"):
            self.server.update_import_metadata(
                {
                    "path": relative,
                    "title": "Must not persist",
                    "authors": ["A. Author"],
                    "year": 2026,
                    "edition": "1e",
                    "subjectIds": ["mathematics"],
                    "topics": ["limits"],
                }
            )

        self.assertEqual(sidecar.read_bytes(), before)

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
        self.assertEqual(imported["metadata"]["subject_ids"], ["physics"])

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
                "subjectIds": ["other"],
                "topics": ["manual"],
            }
        )

    def test_manual_edit_wins_successful_enrichment_race(self) -> None:
        started = threading.Event()
        release = threading.Event()
        self.release_events.append(release)

        def blocked_enrichment(
            *_args: object,
            **_kwargs: object,
        ) -> dict[str, object]:
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

        def failing_enrichment(
            *_args: object,
            **_kwargs: object,
        ) -> dict[str, object]:
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

        def blocked_first(
            metadata: dict[str, object],
            _taxonomy: object,
            **_kwargs: object,
        ) -> dict[str, object]:
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


class CodexCommandResolutionTests(unittest.TestCase):
    def write_command(self, path: Path, *, executable: bool = True) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        if executable:
            path.chmod(0o700)

    def test_relative_and_library_path_entries_are_never_executed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name) / "library"
            root.mkdir()
            self.write_command(root / "codex")
            with mock.patch.dict(
                library_ui.os.environ,
                {"PATH": f".{library_ui.os.pathsep}{root}"},
                clear=False,
            ), mock.patch.object(
                library_ui,
                "_codex_explicit_directories",
                return_value=[],
            ):
                command = library_ui._codex_executable_command(
                    ["login", "status"],
                    library_root=root,
                )
        self.assertIsNone(command)

    def test_absolute_path_entry_outside_library_remains_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            root = temporary / "library"
            tools = temporary / "trusted-tools"
            root.mkdir()
            executable = tools / "codex"
            self.write_command(executable)
            with mock.patch.dict(
                library_ui.os.environ,
                {"PATH": str(tools)},
                clear=False,
            ), mock.patch.object(
                library_ui,
                "_codex_explicit_directories",
                return_value=[],
            ):
                command = library_ui._codex_executable_command(
                    ["login", "status"],
                    library_root=root,
                )
        self.assertEqual(command, [str(executable.resolve()), "login", "status"])

    def test_path_symlink_into_library_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            root = temporary / "library"
            tools = temporary / "trusted-tools"
            root.mkdir()
            tools.mkdir()
            malicious = root / "codex"
            self.write_command(malicious)
            (tools / "codex").symlink_to(malicious)
            with mock.patch.dict(
                library_ui.os.environ,
                {"PATH": str(tools)},
                clear=False,
            ), mock.patch.object(
                library_ui,
                "_codex_explicit_directories",
                return_value=[],
            ):
                command = library_ui._codex_executable_command(
                    ["login", "status"],
                    library_root=root,
                )
        self.assertIsNone(command)

    def test_windows_cmd_and_bat_install_wrappers_remain_supported(self) -> None:
        for suffix in (".cmd", ".bat"):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as temporary_name:
                temporary = Path(temporary_name)
                root = temporary / "library"
                official = temporary / "official-codex"
                system_root = temporary / "Windows"
                root.mkdir()
                executable = official / f"codex{suffix}"
                command_processor = system_root / "System32" / "cmd.exe"
                self.write_command(executable, executable=False)
                self.write_command(command_processor, executable=False)
                with mock.patch.dict(
                    library_ui.os.environ,
                    {
                        "PATH": str(root),
                        "COMSPEC": "",
                        "SystemRoot": str(system_root),
                        "WINDIR": "",
                    },
                    clear=False,
                ), mock.patch.object(
                    library_ui,
                    "_is_windows_platform",
                    return_value=True,
                ), mock.patch.object(
                    library_ui,
                    "_codex_explicit_directories",
                    return_value=[official],
                ):
                    command = library_ui._codex_executable_command(
                        ["exec", "book title"],
                        library_root=root,
                    )
                self.assertIsNotNone(command)
                assert command is not None
                self.assertEqual(
                    command[:4],
                    [str(command_processor.resolve()), "/d", "/s", "/c"],
                )
                self.assertIn(str(executable.resolve()), command[4])
                self.assertIn('"book title"', command[4])

    def test_windows_library_cmd_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            temporary = Path(temporary_name)
            root = temporary / "library"
            root.mkdir()
            self.write_command(root / "codex.cmd", executable=False)
            with mock.patch.dict(
                library_ui.os.environ,
                {"PATH": str(root)},
                clear=False,
            ), mock.patch.object(
                library_ui,
                "_is_windows_platform",
                return_value=True,
            ), mock.patch.object(
                library_ui,
                "_codex_explicit_directories",
                return_value=[],
            ):
                command = library_ui._codex_executable_command(
                    ["login", "status"],
                    library_root=root,
                )
        self.assertIsNone(command)


class CodexMetadataTests(unittest.TestCase):
    def test_codex_schema_uses_supported_array_constraints(self) -> None:
        taxonomy = library_ui.load_taxonomy(ROOT)
        subject_ids = [subject["id"] for subject in taxonomy["subjects"]]
        schema = library_ui._metadata_schema(subject_ids)
        subject_schema = schema["properties"]["subjectIds"]
        self.assertNotIn("uniqueItems", subject_schema)
        self.assertEqual(subject_schema["items"]["enum"], subject_ids)

        duplicate_subjects = {
            "title": "Duplicate categories",
            "authors": [],
            "year": None,
            "edition": "",
            "subjectIds": ["computer-science", "computer-science"],
            "topics": [],
        }
        with self.assertRaisesRegex(ValueError, "Invalid subjects"):
            library_ui._validated_descriptive_metadata(duplicate_subjects, taxonomy)

    def test_taxonomy_assignments_accept_ordered_subject_lists(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            taxonomy = json.loads(
                (ROOT / "library-taxonomy.json").read_text(encoding="utf-8")
            )
            taxonomy["work_assignments"]["cross-disciplinary"] = [
                "computer-science",
                "mathematics",
            ]
            (root / "library-taxonomy.json").write_text(
                json.dumps(taxonomy),
                encoding="utf-8",
            )
            loaded = library_ui.load_taxonomy(root, required=True)
        self.assertEqual(
            loaded["workAssignments"]["cross-disciplinary"],
            ["computer-science", "mathematics"],
        )
        self.assertEqual(
            [
                subject["id"]
                for subject in library_ui._subjects_for_catalog_work(
                    loaded,
                    "cross-disciplinary",
                    "Unsorted",
                )
            ],
            ["computer-science", "mathematics"],
        )

    def test_descriptive_validation_matches_the_persisted_sidecar_contract(self) -> None:
        taxonomy = library_ui.load_taxonomy(ROOT)
        value = {
            "title": "Untitled notes",
            "authors": [],
            "year": None,
            "edition": "",
            "subjectIds": ["mathematics", "computer-science"],
            "topics": [],
        }
        normalized = library_ui._validated_descriptive_metadata(value, taxonomy)
        self.assertEqual(normalized["authors"], ["Unknown author"])
        self.assertEqual(
            normalized["subject_ids"],
            ["mathematics", "computer-science"],
        )

        with self.assertRaisesRegex(ValueError, "publication year"):
            library_ui._validated_descriptive_metadata({**value, "year": True}, taxonomy)
        with self.assertRaisesRegex(ValueError, "subject"):
            library_ui._validated_descriptive_metadata({**value, "subjectIds": []}, taxonomy)

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

            too_many = json.loads(
                (ROOT / "library-taxonomy.json").read_text(encoding="utf-8")
            )
            too_many["subjects"].extend(
                {
                    "id": f"future-subject-{index}",
                    "name": f"Future subject {index}",
                    "description": "Future taxonomy fixture",
                }
                for index in range(
                    len(too_many["subjects"]),
                    library_ui.MAX_ASSIGNED_SUBJECTS + 1,
                )
            )
            (root / "library-taxonomy.json").write_text(
                json.dumps(too_many),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "cannot exceed 64"):
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
                        "subjectIds": ["mathematics", "computer-science"],
                        "topics": ["proofs"],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0)

        with mock.patch.object(
            library_ui,
            "_codex_executable_command",
            side_effect=lambda arguments, **_kwargs: ["codex", *arguments],
        ), mock.patch.object(library_ui.subprocess, "run", side_effect=fake_run):
            result = library_ui.enrich_metadata_with_codex(metadata, taxonomy)
        self.assertEqual(result["subject_ids"], ["mathematics", "computer-science"])
        self.assertIn("--ignore-user-config", seen_command)
        self.assertEqual(seen_command[seen_command.index("--model") + 1], "gpt-5.6-luna")
        self.assertEqual(seen_command[seen_command.index("--sandbox") + 1], "read-only")
        self.assertIn('model_reasoning_effort="medium"', seen_command)
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
