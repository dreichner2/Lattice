from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cross_platform_server  # noqa: E402


class CrossPlatformServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "library"
        self.ui = Path(self.temporary.name) / "ui"
        (self.root / "books").mkdir(parents=True)
        (self.root / "papers").mkdir()
        (self.root / "metadata" / "books").mkdir(parents=True)
        self.ui.mkdir()
        payload = b"%PDF-1.1\n%%EOF\n"
        (self.root / "books" / "fixture.pdf").write_bytes(payload)
        (self.root / "metadata" / "books" / "fixture.json").write_text(
            json.dumps(
                {
                    "title": "Fixture Book",
                    "path": "books/fixture.pdf",
                    "authors": "Test Author",
                    "bytes": len(payload),
                    "sha256": "fixture",
                    "license": "Test fixture",
                }
            ),
            encoding="utf-8",
        )
        (self.root / "CATALOG.md").write_text(
            "\n".join(
                [
                    "# Fixture catalog",
                    "",
                    "## Foundations & Programming",
                    "",
                    "| Title | Authors | Edition | Local | Source | Access |",
                    "|---|---|---|---|---|---|",
                    "| <!-- work: fixture --> [Fixture Book](books/fixture.pdf) | Test Author | 1e | Local | [Official](https://example.com) | Test |",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (self.root / "library-taxonomy.json").write_bytes(
            (ROOT / "library-taxonomy.json").read_bytes()
        )
        (self.ui / "index.html").write_text("<h1>Fixture</h1>", encoding="utf-8")
        (self.ui / "styles.css").write_text("", encoding="utf-8")
        (self.ui / "app.js").write_text("", encoding="utf-8")
        self.database = Path(self.temporary.name) / "reader-state.sqlite3"
        self.server = cross_platform_server.create_server(
            0,
            root=self.root,
            ui_root=self.ui,
            state_database=self.database,
        )
        self.port = int(self.server.server_address[1])
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        with urllib.request.urlopen(self.base + "/api/library", timeout=3) as response:
            self.library = json.loads(response.read())
        self.token = self.library["actionToken"]

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict | None = None,
        token: str | None = None,
    ) -> tuple[int, dict]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {}
        if token is not None:
            headers["X-Library-Token"] = token
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())

    def test_health_uses_the_base_protocol_and_library_identity(self) -> None:
        with urllib.request.urlopen(self.base + "/api/health", timeout=3) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["protocolVersion"], cross_platform_server.PROTOCOL_VERSION)
        self.assertEqual(payload["libraryId"], cross_platform_server.library_identity(self.root))
        self.assertTrue(payload["instanceId"])
        self.assertEqual(
            cross_platform_server.find_matching_server(self.port, payload["libraryId"]),
            self.base,
        )

    def test_state_round_trip_export_and_import(self) -> None:
        status, payload = self.request(
            "/api/state/set",
            method="POST",
            payload={"namespace": "localStorage", "key": "cs-library:test", "value": '{"page":4}'},
            token=self.token,
        )
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

        query = urllib.parse.urlencode({"namespace": "localStorage"})
        _, snapshot = self.request(f"/api/state/snapshot?{query}", token=self.token)
        self.assertEqual(snapshot["values"]["cs-library:test"], '{"page":4}')

        _, exported = self.request("/api/state/export", token=self.token)
        self.assertEqual(exported["libraryId"], self.server.library_id)
        self.assertEqual(len(exported["states"]), 1)
        self.server.state_store.delete_value(
            self.server.library_id,
            "localStorage",
            "cs-library:test",
        )
        _, imported = self.request(
            "/api/state/import",
            method="POST",
            payload={"payload": exported},
            token=self.token,
        )
        self.assertEqual(imported["count"], 1)
        self.assertEqual(
            self.server.state_store.snapshot(self.server.library_id, "localStorage")["cs-library:test"],
            '{"page":4}',
        )

    def test_state_api_requires_the_action_token(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/state/snapshot")
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_state_is_scoped_to_the_selected_library(self) -> None:
        self.server.state_store.set_value(
            self.server.library_id,
            "localStorage",
            "cs-library:theme",
            '"dark"',
        )
        self.assertEqual(
            self.server.state_store.snapshot("different-library", "localStorage"),
            {},
        )

    def test_parent_owned_desktop_service_never_reuses_another_instance(self) -> None:
        class FakeServer:
            server_address = ("127.0.0.1", 8770)
            library_id = "test-library"

            def __init__(self) -> None:
                self.served = False
                self.closed = False

            def serve_forever(self, poll_interval: float) -> None:
                self.served = poll_interval == 0.25

            def server_close(self) -> None:
                self.closed = True

        fake = FakeServer()
        with mock.patch.object(
            cross_platform_server,
            "find_matching_server",
            side_effect=AssertionError("a parent-owned service must not attach to another instance"),
        ), mock.patch.object(
            cross_platform_server,
            "create_server",
            return_value=fake,
        ) as create, mock.patch("signal.signal"):
            result = cross_platform_server.run_server(
                8766,
                root=self.root,
                ui_root=self.ui,
                state_database=self.database,
                parent_pid=12345,
                open_browser=False,
            )
        self.assertEqual(result, 0)
        self.assertTrue(fake.served)
        self.assertTrue(fake.closed)
        self.assertEqual(create.call_args.kwargs["parent_pid"], 12345)


if __name__ == "__main__":
    unittest.main()
