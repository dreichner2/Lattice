from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_ui  # noqa: E402
import study_lab  # noqa: E402
import study_python  # noqa: E402


class StudyServerTests(unittest.TestCase):
    private_token = "a" * 64

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        base = Path(cls._temporary.name)
        cls.library_root = base / "library"
        (cls.library_root / "books").mkdir(parents=True)
        (cls.library_root / "metadata").mkdir()
        (cls.library_root / "library-taxonomy.json").write_bytes(
            (ROOT / "library-taxonomy.json").read_bytes()
        )
        (cls.library_root / "CATALOG.md").write_text("# Lattice\n", encoding="utf-8")
        (cls.library_root / "books" / "signals.pdf").write_bytes(b"test-pdf")
        (cls.library_root / "metadata" / "signals.json").write_text(
            json.dumps(
                {
                    "path": "books/signals.pdf",
                    "title": "Signals and Systems",
                }
            ),
            encoding="utf-8",
        )
        environment = dict(__import__("os").environ)
        environment["LATTICE_STUDY_ROOT"] = str(base / "study")
        environment["LATTICE_PRIVATE_TOKEN"] = cls.private_token
        cls._patcher = mock.patch.dict(
            library_ui.os.environ, environment, clear=False
        )
        cls._patcher.start()
        try:
            cls.server = library_ui.create_server(0, root=cls.library_root, ui_root=ROOT / "ui")
        except BaseException:
            cls._patcher.stop()
            raise
        cls.port = int(cls.server.server_address[1])
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        if cls.server.study is not None:
            cls.server.study.close()
        cls.thread.join(timeout=2)
        cls._patcher.stop()
        cls._temporary.cleanup()

    def url(self, route: str) -> str:
        return self.base_url + route

    def token(self) -> str:
        with urllib.request.urlopen(self.url("/api/library"), timeout=5) as response:
            return json.loads(response.read())["actionToken"]

    def get(
        self,
        route: str,
        *,
        private_token: str | None = private_token,
    ) -> tuple[int, dict]:
        headers = (
            {"X-Lattice-Private-Token": private_token}
            if private_token is not None
            else {}
        )
        request = urllib.request.Request(self.url(route), headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as caught:
            with caught:
                return caught.code, json.loads(caught.read())

    def post(
        self,
        route: str,
        body: dict,
        *,
        private_token: str | None = private_token,
    ) -> tuple[int, dict]:
        headers = {
            "Content-Type": "application/json",
            "X-Library-Token": self.token(),
        }
        if private_token is not None:
            headers["X-Lattice-Private-Token"] = private_token
        request = urllib.request.Request(
            self.url(route),
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as caught:
            with caught:
                return caught.code, json.loads(caught.read())

    # ------------------------------------------------------------------ tests

    def test_health_reports_study_lab_availability(self) -> None:
        status, payload = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["studyLabAvailable"])
        self.assertEqual(payload["protocolVersion"], 4)

    def test_health_proves_the_owned_server_without_receiving_the_private_token(self) -> None:
        challenge = "c" * 64
        request = urllib.request.Request(
            self.url("/api/health"),
            headers={"X-Lattice-Health-Challenge": challenge},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        expected = hmac.new(
            self.private_token.encode("utf-8"),
            f"{challenge}:{self.port}:0".encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(payload["privateProof"], expected)

    def test_private_token_is_not_exposed_by_public_api(self) -> None:
        with urllib.request.urlopen(self.url("/api/library"), timeout=5) as response:
            payload = json.loads(response.read())
        self.assertNotIn("privateToken", payload)
        self.assertNotIn(self.private_token, json.dumps(payload))

    def test_study_reads_require_private_token(self) -> None:
        for provided in (None, "b" * 64):
            with self.subTest(provided=provided):
                status, payload = self.get(
                    "/api/study/notebooks",
                    private_token=provided,
                )
                self.assertEqual(status, 403)
                self.assertIn("private Study token", payload["error"])

    def test_status_lists_only_latex_and_python_kinds(self) -> None:
        status, payload = self.get("/api/study/status")
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["cellKinds"], ["latex", "python"])

    def test_full_notebook_lifecycle_over_http(self) -> None:
        status, created = self.post(
            "/api/study/notebooks",
            {
                "title": "Fourier notes",
                "workPath": "books/signals.pdf",
                "workTitle": "Untrusted client title",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["notebook"]["workTitle"], "Signals and Systems")
        notebook_id = created["notebook"]["id"]

        status, notebook = self.get(f"/api/study/notebook/{notebook_id}")
        self.assertEqual(status, 200)
        self.assertEqual(notebook["cells"], [])
        token = notebook["notebook"]["updatedAt"]

        status, added = self.post(
            f"/api/study/notebook/{notebook_id}/cells",
            {
                "kind": "latex",
                "source": "$\\nabla \\cdot E = \\rho$",
                "baseUpdatedAt": token,
            },
        )
        self.assertEqual(status, 200)
        cell_id = added["cell"]["id"]

        status, updated = self.post(
            "/api/study/cell/update",
            {
                "cellId": cell_id,
                "source": "$\\nabla \\times E = -\\partial B/\\partial t$",
                "baseUpdatedAt": added["notebookUpdatedAt"],
            },
        )
        self.assertEqual(status, 200)

        status, conflict = self.post(
            "/api/study/cell/update",
            {"cellId": cell_id, "source": "stale", "baseUpdatedAt": token},
        )
        self.assertEqual(status, 409)

        status, moved = self.post(
            "/api/study/cell/move",
            {
                "cellId": cell_id,
                "direction": "up",
                "baseUpdatedAt": updated["notebookUpdatedAt"],
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(moved["unchanged"])

        status, deleted = self.post(
            "/api/study/cell/delete",
            {
                "cellId": cell_id,
                "baseUpdatedAt": updated["notebookUpdatedAt"],
            },
        )
        self.assertEqual(status, 200)

        status, removed = self.post(
            f"/api/study/notebook/{notebook_id}/delete",
            {"baseUpdatedAt": deleted["notebookUpdatedAt"]},
        )
        self.assertEqual(status, 200)

    def test_text_cell_kind_is_rejected(self) -> None:
        status, created = self.post("/api/study/notebooks", {"title": "Kinds"})
        notebook_id = created["notebook"]["id"]
        status, body = self.post(
            f"/api/study/notebook/{notebook_id}/cells",
            {
                "kind": "text",
                "source": "prose",
                "baseUpdatedAt": created["notebook"]["updatedAt"],
            },
        )
        self.assertEqual(status, 400)

    def test_link_requires_revision_and_exact_catalog_path(self) -> None:
        status, created = self.post("/api/study/notebooks", {"title": "Links"})
        self.assertEqual(status, 201)
        notebook = created["notebook"]
        route = f"/api/study/notebook/{notebook['id']}/link"

        status, _body = self.post(route, {"workPath": "books/signals.pdf"})
        self.assertEqual(status, 409)
        status, _body = self.post(
            route,
            {
                "workPath": "books/missing.pdf",
                "baseUpdatedAt": notebook["updatedAt"],
            },
        )
        self.assertEqual(status, 400)
        status, linked = self.post(
            route,
            {
                "workPath": "books/signals.pdf",
                "baseUpdatedAt": notebook["updatedAt"],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(linked["notebook"]["workTitle"], "Signals and Systems")

    def test_study_lab_assets_are_served(self) -> None:
        for route, marker in (
            ("/study-lab.html", b"Study Lab"),
            ("/study-lab.js", b"cellStack"),
            ("/study-lab.css", b".cell-stack"),
            ("/vendor/katex/katex.min.css", b"KaTeX"),
            ("/vendor/katex/katex.min.js", b"katex"),
        ):
            with urllib.request.urlopen(self.url(route), timeout=5) as response:
                self.assertEqual(response.status, 200, route)
                body = response.read()
            self.assertIn(marker, body, route)

        katex_css = (ROOT / "ui" / "vendor" / "katex" / "katex.min.css").read_text(
            encoding="utf-8"
        )
        font_paths = sorted(set(re.findall(r"url\((fonts/[^)]+)\)", katex_css)))
        self.assertGreater(len(font_paths), 10)
        for relative in font_paths:
            with urllib.request.urlopen(
                self.url(f"/vendor/katex/{relative}"), timeout=5
            ) as response:
                self.assertEqual(response.status, 200, relative)
                self.assertGreater(int(response.headers["Content-Length"]), 0, relative)

    def test_katex_vendor_rejects_traversal(self) -> None:
        status, _body = self.get("/vendor/katex/..%2F..%2F..%2Flibrary%2FCATALOG.md")
        self.assertEqual(status, 404)

    def test_kernel_run_over_http(self) -> None:
        status, created = self.post("/api/study/notebooks", {"title": "Kernel nb"})
        notebook_id = created["notebook"]["id"]

        status, status_payload = self.get("/api/study/kernel/status")
        self.assertEqual(status, 200)
        self.assertTrue(status_payload["available"])

        status, run = self.post(
            "/api/study/kernel/run",
            {"notebookId": notebook_id, "source": "print('http')\n3 ** 2"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(run["ok"])
        stream = next(o for o in run["outputs"] if o["type"] == "stream")
        self.assertIn("http", stream["text"])
        value = next(o for o in run["outputs"] if o["type"] == "result")
        self.assertEqual(value["text"], "9")

        status, restarted = self.post(
            "/api/study/kernel/restart",
            {"notebookId": notebook_id},
        )
        self.assertEqual(status, 200)

        status, run = self.post(
            "/api/study/kernel/run",
            {"notebookId": notebook_id, "source": "print('again')"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(run["ok"])

    def test_kernel_rejects_empty_source(self) -> None:
        status, _body = self.post(
            "/api/study/kernel/run",
            {"notebookId": "nb", "source": "   "},
        )
        self.assertEqual(status, 400)

    def test_kernel_rejects_unknown_notebooks_and_oversized_source(self) -> None:
        status, _body = self.post(
            "/api/study/kernel/run",
            {"notebookId": "missing", "source": "40 + 2"},
        )
        self.assertEqual(status, 400)

        status, created = self.post("/api/study/notebooks", {"title": "Bounded"})
        self.assertEqual(status, 201)
        status, _body = self.post(
            "/api/study/kernel/run",
            {
                "notebookId": created["notebook"]["id"],
                "source": "x" * (study_lab.MAX_CELL_SOURCE_CHARS + 1),
            },
        )
        self.assertEqual(status, 400)

    def test_deleting_notebook_stops_its_kernel(self) -> None:
        status, created = self.post("/api/study/notebooks", {"title": "Disposable"})
        self.assertEqual(status, 201)
        notebook = created["notebook"]
        status, _run = self.post(
            "/api/study/kernel/run",
            {"notebookId": notebook["id"], "source": "kept = 42"},
        )
        self.assertEqual(status, 200)
        self.assertIn(notebook["id"], self.server.study_runtime._kernels)

        status, _deleted = self.post(
            f"/api/study/notebook/{notebook['id']}/delete",
            {"baseUpdatedAt": notebook["updatedAt"]},
        )
        self.assertEqual(status, 200)
        self.assertNotIn(notebook["id"], self.server.study_runtime._kernels)

    def test_delete_invalidates_an_inflight_run_without_waiting_for_timeout(self) -> None:
        created = self.server.study_create_notebook({"title": "Delete race"})
        notebook = created["notebook"]
        errors: list[BaseException] = []

        def run_cell() -> None:
            try:
                self.server.study_kernel_run({
                    "notebookId": notebook["id"],
                    "source": "import time\ntime.sleep(30)\n42",
                })
            except BaseException as exc:
                errors.append(exc)

        runner = threading.Thread(target=run_cell)
        runner.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            kernel = self.server.study_runtime._kernels.get(notebook["id"])
            if kernel is not None and kernel.busy:
                break
            time.sleep(0.01)
        else:
            self.fail("the kernel did not begin the controlled run")

        started = time.monotonic()
        self.server.study_delete_notebook(
            notebook["id"],
            {"baseUpdatedAt": notebook["updatedAt"]},
        )
        runner.join(timeout=5)
        self.assertFalse(runner.is_alive())
        self.assertLess(time.monotonic() - started, 3)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], study_python.KernelUnavailable)
        self.assertNotIn(notebook["id"], self.server.study_runtime._kernels)

    def test_kernel_endpoints_require_private_launch_capability(self) -> None:
        status, _body = self.get(
            "/api/study/kernel/status",
            private_token=None,
        )
        self.assertEqual(status, 403)

        status, created = self.post("/api/study/notebooks", {"title": "Private kernel"})
        self.assertEqual(status, 201)
        notebook_id = created["notebook"]["id"]
        for route, body in (
            (
                "/api/study/kernel/run",
                {"notebookId": notebook_id, "source": "40 + 2"},
            ),
            (
                "/api/study/kernel/restart",
                {"notebookId": notebook_id},
            ),
        ):
            with self.subTest(route=route):
                status, _body = self.post(route, body, private_token=None)
                self.assertEqual(status, 403)

    def test_mutations_require_token(self) -> None:
        request = urllib.request.Request(
            self.url("/api/study/notebooks"),
            data=b'{"title":"nope"}',
            headers={
                "Content-Type": "application/json",
                "X-Lattice-Private-Token": self.private_token,
            },
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        try:
            self.assertEqual(caught.exception.code, 403)
        finally:
            caught.exception.close()

    def test_mutations_require_private_token_too(self) -> None:
        status, payload = self.post(
            "/api/study/notebooks",
            {"title": "nope"},
            private_token="b" * 64,
        )
        self.assertEqual(status, 403)
        self.assertIn("private Study token", payload["error"])


if __name__ == "__main__":
    unittest.main()
