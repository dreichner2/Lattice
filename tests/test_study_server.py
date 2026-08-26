from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_ui  # noqa: E402
import study_lab  # noqa: E402


class StudyServerTests(unittest.TestCase):
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
        environment = dict(__import__("os").environ)
        environment["LATTICE_STUDY_ROOT"] = str(base / "study")
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

    def get(self, route: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self.url(route), timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as caught:
            return caught.code, json.loads(caught.read())

    def post(self, route: str, body: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            self.url(route),
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Library-Token": self.token(),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as caught:
            return caught.code, json.loads(caught.read())

    # ------------------------------------------------------------------ tests

    def test_health_reports_study_lab_availability(self) -> None:
        status, payload = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["studyLabAvailable"])
        self.assertEqual(payload["protocolVersion"], 4)

    def test_status_lists_only_latex_and_python_kinds(self) -> None:
        status, payload = self.get("/api/study/status")
        self.assertEqual(status, 200)
        self.assertTrue(payload["available"])
        self.assertEqual(payload["cellKinds"], ["latex", "python"])

    def test_full_notebook_lifecycle_over_http(self) -> None:
        status, created = self.post(
            "/api/study/notebooks",
            {"title": "Fourier notes", "workPath": "books/signals.pdf", "workTitle": "Signals"},
        )
        self.assertEqual(status, 201)
        notebook_id = created["notebook"]["id"]

        status, notebook = self.get(f"/api/study/notebook/{notebook_id}")
        self.assertEqual(status, 200)
        self.assertEqual(notebook["cells"], [])
        token = notebook["notebook"]["updatedAt"]

        status, added = self.post(
            f"/api/study/notebook/{notebook_id}/cells",
            {"kind": "latex", "source": "$\\nabla \\cdot E = \\rho$"},
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
            {"kind": "text", "source": "prose"},
        )
        self.assertEqual(status, 400)

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

    def test_katex_vendor_rejects_traversal(self) -> None:
        status, _body = self.get("/vendor/katex/..%2F..%2F..%2Flibrary%2FCATALOG.md")
        self.assertEqual(status, 404)

    def test_mutations_require_token(self) -> None:
        request = urllib.request.Request(
            self.url("/api/study/notebooks"),
            data=b'{"title":"nope"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
