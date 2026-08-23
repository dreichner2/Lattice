from __future__ import annotations

import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lattice_tutor  # noqa: E402


def minimal_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        f"<< /Length {len(escaped) + 31} >>\nstream\nBT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\nendstream".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode())
        payload.extend(body)
        payload.extend(b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(payload)


def source_record(path: Path, root: Path, work_id: str = "work-one") -> dict[str, object]:
    stat = path.stat()
    return {
        "path": path.relative_to(root).as_posix(),
        "workId": work_id,
        "title": path.stem,
        "workTitle": "Fixture work",
        "authors": "Fixture Author",
        "format": path.suffix.removeprefix(".").upper(),
        "bytes": stat.st_size,
        "modifiedNs": stat.st_mtime_ns,
        "sha256": "",
        "kind": "file",
        "searchText": f"fixture {path.stem}".casefold(),
    }


class TutorExtractionTests(unittest.TestCase):
    def test_vendored_pdf_parser_extracts_page_text_and_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "source.pdf"
            path.write_bytes(minimal_pdf("Consensus requires independent verification"))
            chunks = lattice_tutor.extract_source_chunks(path, threading.Event())
        self.assertTrue(any("Consensus requires" in chunk["text"] for chunk in chunks))
        self.assertEqual(chunks[0]["locator"], "page 1")

    def test_private_index_searches_and_prunes_ineligible_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "library"
            cache = Path(temporary) / "cache"
            path = root / "books" / "distributed.txt"
            path.parent.mkdir(parents=True)
            path.write_text(
                "Lamport clocks provide a partial ordering for distributed events.",
                encoding="utf-8",
            )
            source = source_record(path, root)
            index = lattice_tutor.TutorSourceIndex(root, "fixture", cache_root=cache)
            try:
                index.refresh_sources([source])
                for future in index.schedule([source]):
                    future.result(timeout=5)
                results = index.search("How do Lamport clocks order events?", {source["path"]})
                self.assertTrue(results)
                self.assertIn("partial ordering", results[0]["text"])
                index.refresh_sources([])
                with closing(sqlite3.connect(index.database_path)) as connection:
                    self.assertEqual(connection.execute("SELECT count(*) FROM tutor_files").fetchone()[0], 0)
                    self.assertEqual(connection.execute("SELECT count(*) FROM tutor_chunks").fetchone()[0], 0)
            finally:
                index.close()


class TutorManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "library"
        self.cache = Path(self.temporary.name) / "cache"
        self.source = self.root / "books" / "algorithms.txt"
        self.source.parent.mkdir(parents=True)
        self.source.write_text(
            "Dijkstra's algorithm settles the nearest unsettled vertex first.",
            encoding="utf-8",
        )
        record = source_record(self.source, self.root)
        self.library = {
            "works": [
                {
                    "id": "eligible-work",
                    "title": "Algorithms",
                    "authors": "Fixture Author",
                    "subject": "Computer science",
                    "topic": "Algorithms",
                    "topics": [],
                    "tutorEligible": True,
                    "files": [
                        {
                            **record,
                            "exists": True,
                            "tutorEligible": True,
                            "title": "Algorithms notes",
                        }
                    ],
                },
                {
                    "id": "restricted-work",
                    "title": "Human study edition",
                    "tutorEligible": False,
                    "tutorRestriction": "Publisher terms reserve this work for human study.",
                    "files": [
                        {
                            "path": "books/restricted.pdf",
                            "exists": True,
                            "tutorEligible": False,
                        }
                    ],
                },
            ]
        }
        self.catalog = {
            "courses": [
                {
                    "id": "course-one",
                    "title": "Algorithms lectures",
                    "code": "CS 1",
                    "institution": "Fixture University",
                    "term": "Fall",
                    "subject": "Computer science",
                    "level": "Undergraduate",
                    "description": "An algorithms course.",
                    "lectures": [{"id": "video-one", "title": "Shortest paths"}],
                }
            ]
        }
        self.manager = lattice_tutor.TutorManager(
            self.root,
            "fixture",
            command_builder=lambda arguments: ["codex", *arguments],
            login_status=lambda: {"available": True, "authenticated": True, "ready": True},
            cache_root=self.cache,
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary.cleanup()

    def test_status_exposes_models_reasoning_and_source_boundaries(self) -> None:
        status = self.manager.status(self.library, self.catalog)
        self.assertEqual([item["label"] for item in status["models"]], ["Luna", "Terra", "Sol"])
        self.assertEqual([item["id"] for item in status["efforts"]], ["low", "medium", "high", "xhigh", "max"])
        self.assertEqual(status["sources"]["eligibleWorks"], 1)
        self.assertEqual(status["sources"]["restrictedWorks"], 1)
        self.assertEqual(status["sources"]["videoContent"], "catalog-metadata-only")

    def test_selected_scope_rejects_restricted_and_unknown_works(self) -> None:
        for work_id in ("restricted-work", "missing-work"):
            with self.subTest(work_id=work_id), self.assertRaises(lattice_tutor.TutorRequestError):
                self.manager._resolve_scope(
                    {"scope": "selected", "workIds": [work_id]},
                    self.library,
                    self.catalog,
                )

    def test_chat_returns_only_validated_source_citations(self) -> None:
        response = {
            "answer": "Dijkstra chooses the nearest unsettled vertex. [1]",
            "citations": [
                {"source": "books/algorithms.txt", "locator": "document"},
                {"source": "books/restricted.pdf", "locator": "page 1"},
            ],
        }
        with mock.patch.object(self.manager, "_run_codex", return_value=response) as run:
            result = self.manager.chat(
                {
                    "sessionId": "0123456789abcdefghij",
                    "message": "Explain Dijkstra's choice.",
                    "model": "gpt-5.6-terra",
                    "effort": "high",
                    "scope": "selected",
                    "workIds": ["eligible-work"],
                    "courseIds": [],
                },
                self.library,
                self.catalog,
            )
        self.assertEqual(result["sessionId"], "0123456789abcdefghij")
        self.assertEqual(len(result["citations"]), 1)
        self.assertEqual(result["citations"][0]["path"], "books/algorithms.txt")
        self.assertEqual(run.call_args.kwargs["allowed_paths"], [self.source.resolve()])
        self.assertEqual(run.call_args.kwargs["denied_paths"], [])

    def test_video_scope_is_metadata_only(self) -> None:
        scope = self.manager._resolve_scope(
            {"scope": "selected", "courseIds": ["course-one"]},
            self.library,
            self.catalog,
        )
        context = self.manager._course_context("shortest paths", scope["courses"])
        self.assertEqual(scope["sources"], [])
        self.assertEqual(context[0]["source"], "video:course-one")
        self.assertIn("Lecture 1: Shortest paths", context[0]["text"])

    def test_whole_library_scope_still_grants_only_eligible_exact_files(self) -> None:
        with mock.patch.object(
            self.manager,
            "_run_codex",
            return_value={"answer": "The eligible shelf is available.", "citations": []},
        ) as run:
            result = self.manager.chat(
                {
                    "sessionId": "whole-library-0123456789",
                    "message": "What is available to study?",
                    "model": "gpt-5.6-sol",
                    "effort": "max",
                    "scope": "all",
                },
                self.library,
                self.catalog,
            )
        self.assertEqual(result["scope"], {"mode": "all", "works": 1, "courses": 1, "files": 1})
        self.assertEqual(run.call_args.kwargs["allowed_paths"], [self.source.resolve()])
        self.assertNotIn(self.root / "books" / "restricted.pdf", run.call_args.kwargs["allowed_paths"])

    def test_codex_invocation_is_ephemeral_read_only_and_config_independent(self) -> None:
        captured: list[str] = []
        response = json.dumps({"answer": "Grounded answer [1]", "citations": []})
        child = (
            "import json,sys; sys.stdin.read(); "
            f"print(json.dumps({{'type':'item.completed','item':{{'type':'agent_message','text':{response!r}}}}}))"
        )

        def command_builder(arguments: list[str]) -> list[str]:
            captured.extend(arguments)
            return [sys.executable, "-c", child]

        manager = lattice_tutor.TutorManager(
            self.root,
            "invocation",
            command_builder=command_builder,
            login_status=lambda: {"ready": True},
            cache_root=Path(self.temporary.name) / "invocation-cache",
        )
        try:
            result = manager._run_codex(
                model="gpt-5.6-sol",
                effort="max",
                prompt="fixture",
                allowed_paths=[self.source.resolve()],
                denied_paths=[],
                session={"process": None},
            )
        finally:
            manager.close()
        self.assertEqual(result["answer"], "Grounded answer [1]")
        self.assertIn("--ephemeral", captured)
        self.assertIn("--ignore-user-config", captured)
        self.assertIn("--ignore-rules", captured)
        self.assertIn("permissions.lattice-tutor.network.enabled=false", captured)
        permission = next(value for value in captured if value.startswith("permissions.lattice-tutor.filesystem="))
        self.assertIn(str(self.source.resolve()), permission)
        self.assertNotIn(str(self.root / "books"), permission.replace(str(self.source.resolve()), ""))

    def test_child_environment_drops_api_keys_and_proxy_credentials(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "should-not-leak",
                "HTTPS_PROXY": "https://secret@example.invalid",
                "PATH": "/usr/bin",
            },
            clear=False,
        ):
            environment = lattice_tutor._safe_process_environment()
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("HTTPS_PROXY", environment)
        self.assertEqual(environment["PATH"], "/usr/bin")


if __name__ == "__main__":
    unittest.main()
