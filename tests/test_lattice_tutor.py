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
        self.assertIsNone(result["artifact"])

    def test_chat_passes_through_validated_artifact(self) -> None:
        response = {
            "answer": "Here is the Cauchy-Schwarz inequality. [1]",
            "citations": [
                {"source": "books/algorithms.txt", "locator": "document"},
            ],
            "artifact": {
                "kind": "latex",
                "source": r"\begin{equation}\langle x,y\rangle^2\end{equation}",
                "label": "Cauchy-Schwarz",
            },
        }
        with mock.patch.object(self.manager, "_run_codex", return_value=response):
            result = self.manager.chat(
                {
                    "sessionId": "0123456789abcdefghij",
                    "message": "Derive Cauchy-Schwarz.",
                    "model": "gpt-5.6-terra",
                    "effort": "high",
                    "scope": "selected",
                    "workIds": ["eligible-work"],
                    "courseIds": [],
                },
                self.library,
                self.catalog,
            )
        self.assertEqual(result["artifact"]["kind"], "latex")
        self.assertIn("Cauchy", result["artifact"]["label"])

    def test_artifact_validation_strips_fences_and_rejects_bad_kinds(self) -> None:
        fenced = {
            "kind": "python",
            "source": "```python\nimport numpy as np\nprint(np.pi)\n```",
        }
        cleaned = self.manager._validate_artifact(fenced)
        self.assertEqual(cleaned["source"], "import numpy as np\nprint(np.pi)")

        for broken in (
            {"kind": "text", "source": "prose"},
            {"kind": "latex", "source": ""},
            {"kind": "latex"},
            "not-a-dict",
            None,
            {"kind": "latex", "source": "x" * (lattice_tutor.MAX_ARTIFACT_CHARS + 1)},
        ):
            self.assertIsNone(self.manager._validate_artifact(broken))

    def test_response_schema_models_optional_artifact_as_strict_nullable_field(self) -> None:
        schema = lattice_tutor._response_schema()
        self.assertEqual(
            schema["required"],
            ["answer", "citations", "artifact"],
        )
        artifact = schema["properties"]["artifact"]
        object_branch = artifact["anyOf"][0]
        self.assertEqual(
            object_branch["required"],
            ["kind", "source", "label"],
        )
        self.assertEqual(artifact["anyOf"][1], {"type": "null"})

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

    def test_citations_require_sources_in_the_staged_turn_context(self) -> None:
        response = {
            "answer": "The source might discuss Dijkstra. [1]",
            "citations": [
                {"source": "books/algorithms.txt", "locator": "document"},
            ],
        }
        with mock.patch.object(
            self.manager.index,
            "search",
            return_value=[],
        ), mock.patch.object(
            self.manager,
            "_run_codex",
            return_value=response,
        ):
            result = self.manager.chat(
                {
                    "sessionId": "windows-grounding-0123456789",
                    "message": "Explain Dijkstra's choice.",
                    "scope": "selected",
                    "workIds": ["eligible-work"],
                },
                self.library,
                self.catalog,
            )
        self.assertEqual(result["citations"], [])
        self.assertFalse(result["grounded"])

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

    def test_external_symlink_is_excluded_from_tutor_scope(self) -> None:
        outside = Path(self.temporary.name) / "private-note.txt"
        outside.write_text("private fixture", encoding="utf-8")
        alias = self.root / "books" / "linked-note.txt"
        try:
            alias.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"file symlinks are unavailable: {exc}")
        record = source_record(alias, self.root)
        self.library["works"][0]["files"].append(
            {**record, "exists": True, "tutorEligible": True}
        )

        scope = self.manager._resolve_scope(
            {"scope": "selected", "workIds": ["eligible-work"]},
            self.library,
            self.catalog,
        )

        self.assertEqual(
            [source["path"] for source in scope["sources"]],
            ["books/algorithms.txt"],
        )
        self.assertEqual(
            [source["path"] for source in scope["allEligibleSources"]],
            ["books/algorithms.txt"],
        )

    def test_chat_revalidates_a_source_swapped_to_external_symlink(self) -> None:
        outside = Path(self.temporary.name) / "private-note.txt"
        outside.write_text("private fixture", encoding="utf-8")
        original_resolve_scope = self.manager._resolve_scope

        def resolve_then_swap(*args: object, **kwargs: object) -> dict[str, object]:
            scope = original_resolve_scope(*args, **kwargs)
            self.source.unlink()
            try:
                self.source.symlink_to(outside)
            except OSError as exc:
                self.skipTest(f"file symlinks are unavailable: {exc}")
            return scope

        with mock.patch.object(
            self.manager,
            "_resolve_scope",
            side_effect=resolve_then_swap,
        ), mock.patch.object(
            self.manager,
            "_run_codex",
            return_value={"answer": "No safe local source is available.", "citations": []},
        ) as run:
            result = self.manager.chat(
                {
                    "sessionId": "symlink-race-0123456789",
                    "message": "Read the selected source.",
                    "scope": "selected",
                    "workIds": ["eligible-work"],
                },
                self.library,
                self.catalog,
            )

        self.assertEqual(run.call_args.kwargs["allowed_paths"], [])
        self.assertNotIn(str(outside), run.call_args.kwargs["prompt"])
        self.assertEqual(result["scope"]["files"], 0)

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
        self.assertIn('web_search="disabled"', captured)
        self.assertEqual(captured[captured.index("--sandbox") + 1], "read-only")
        self.assertNotIn("default_permissions=\"lattice-tutor\"", captured)
        self.assertFalse(
            any(value.startswith("permissions.lattice-tutor.") for value in captured)
        )
        disabled_features = {
            captured[index + 1]
            for index, value in enumerate(captured[:-1])
            if value == "--disable"
        }
        self.assertGreaterEqual(
            disabled_features,
            {"shell_tool", "unified_exec", "code_mode"},
        )
        self.assertNotIn(str(self.root), "\n".join(captured))
        self.assertNotIn(str(self.source.resolve()), "\n".join(captured))

    def test_every_platform_uses_one_disposable_read_only_excerpt_workspace(self) -> None:
        captured: list[str] = []
        observed: dict[str, object] = {}
        response = json.dumps({"answer": "Grounded answer [1]", "citations": []})
        child = (
            "import json,sys; sys.stdin.read(); "
            f"print(json.dumps({{'type':'item.completed','item':{{'type':'agent_message','text':{response!r}}}}}))"
        )
        prompt = "SELECTED EXCERPT: Dijkstra settles the nearest vertex."
        external_source = Path(r"E:\Lattice Library\books\algorithms.pdf")

        def command_builder(arguments: list[str]) -> list[str]:
            captured.extend(arguments)
            workspace = Path(arguments[arguments.index("-C") + 1])
            context_path = workspace / "turn-context.txt"
            schema_path = Path(arguments[arguments.index("--output-schema") + 1])
            observed["workspace"] = workspace
            observed["context"] = context_path.read_text(encoding="utf-8")
            observed["schema_parent"] = schema_path.parent
            return [sys.executable, "-c", child]

        manager = lattice_tutor.TutorManager(
            self.root,
            "windows-workspace",
            command_builder=command_builder,
            login_status=lambda: {"ready": True},
            cache_root=Path(self.temporary.name) / "windows-workspace-cache",
        )
        try:
            result = manager._run_codex(
                model="gpt-5.6-luna",
                effort="low",
                prompt=prompt,
                allowed_paths=[external_source],
                denied_paths=[],
                session={"process": None},
            )
        finally:
            manager.close()

        workspace = observed["workspace"]
        self.assertIsInstance(workspace, Path)
        self.assertEqual(result["answer"], "Grounded answer [1]")
        self.assertEqual(observed["context"], prompt)
        self.assertEqual(observed["schema_parent"], workspace)
        self.assertNotEqual(workspace, self.root)
        self.assertFalse(workspace.exists())
        self.assertEqual(captured[captured.index("--sandbox") + 1], "read-only")
        self.assertIn('web_search="disabled"', captured)
        self.assertNotIn("default_permissions=\"lattice-tutor\"", captured)
        self.assertFalse(
            any(value.startswith("permissions.lattice-tutor.") for value in captured)
        )
        disabled_features = {
            captured[index + 1]
            for index, value in enumerate(captured[:-1])
            if value == "--disable"
        }
        self.assertGreaterEqual(
            disabled_features,
            {"shell_tool", "unified_exec", "code_mode"},
        )
        self.assertNotIn(str(self.root), "\n".join(captured))
        self.assertNotIn(str(external_source), "\n".join(captured))

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

    def test_codex_stderr_is_preserved_and_failure_is_not_misreported_as_auth(self) -> None:
        child = (
            "import sys; sys.stdin.read(); "
            "sys.stderr.write('error: invalid filesystem permission map; expected quoted keys\\n'); "
            "raise SystemExit(17)"
        )
        cache = Path(self.temporary.name) / "stderr-cache"
        manager = lattice_tutor.TutorManager(
            self.root,
            "stderr",
            command_builder=lambda _arguments: [sys.executable, "-c", child],
            login_status=lambda: {"ready": True},
            cache_root=cache,
        )
        try:
            with self.assertRaises(lattice_tutor.TutorRequestError) as raised:
                manager._run_codex(
                    model="gpt-5.6-luna",
                    effort="low",
                    prompt="fixture",
                    allowed_paths=[self.source.resolve()],
                    denied_paths=[],
                    session={"process": None},
                )
        finally:
            manager.close()
        message = str(raised.exception)
        self.assertIn("Codex exited with code 17", message)
        self.assertNotIn("sign-in", message.casefold())
        self.assertNotIn("model access", message.casefold())
        diagnostic = cache / "last-codex-stderr.log"
        self.assertTrue(diagnostic.is_file())
        content = diagnostic.read_text(encoding="utf-8")
        self.assertIn("Outcome: failed", content)
        self.assertIn("ExitCode: 17", content)
        self.assertIn("invalid filesystem permission map", content)


if __name__ == "__main__":
    unittest.main()
