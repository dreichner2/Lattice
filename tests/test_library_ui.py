from __future__ import annotations

import http.client
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_ui  # noqa: E402


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = library_ui.build_library(ROOT)

    def test_catalog_shape(self) -> None:
        self.assertEqual(self.library["stats"]["works"], 47)
        self.assertEqual(self.library["stats"]["artifacts"], 72)
        self.assertEqual(self.library["stats"]["present"], 72)
        self.assertEqual(self.library["stats"]["subjects"], 9)
        self.assertTrue(self.library["stats"]["allPresent"])
        self.assertEqual(
            self.library["stats"]["materialCounts"],
            {
                "book": 39,
                "lecture": 20,
                "course-volume": 7,
                "paper": 2,
                "specification": 2,
                "standard": 2,
            },
        )

    def test_every_artifact_is_present_and_unique(self) -> None:
        files = [file for work in self.library["works"] for file in work["files"]]
        paths = [file["path"] for file in files]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(all(file["exists"] for file in files))

    def test_collection_sizes(self) -> None:
        by_id = {work["id"]: work for work in self.library["works"]}
        self.assertEqual(by_id["mit-6006"]["fileCount"], 20)
        self.assertEqual(by_id["software-foundations"]["fileCount"], 7)

    def test_payload_resolution_rejects_escape_and_unknown_paths(self) -> None:
        allowed = {"books/sicp.pdf"}
        self.assertEqual(
            library_ui.resolve_payload(ROOT, "books/sicp.pdf", allowed),
            (ROOT / "books/sicp.pdf").resolve(),
        )
        for value in ("../CATALOG.md", "/etc/passwd", "books/unknown.pdf"):
            with self.assertRaises(ValueError):
                library_ui.resolve_payload(ROOT, value, allowed)

    def test_byte_ranges(self) -> None:
        self.assertEqual(library_ui.parse_byte_range("bytes=0-4", 100), (0, 4))
        self.assertEqual(library_ui.parse_byte_range("bytes=95-", 100), (95, 99))
        self.assertEqual(library_ui.parse_byte_range("bytes=-5", 100), (95, 99))
        with self.assertRaises(ValueError):
            library_ui.parse_byte_range("bytes=100-101", 100)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = library_ui.create_server(0, root=ROOT)
        cls.port = int(cls.server.server_address[1])
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_home_and_api(self) -> None:
        with urllib.request.urlopen(self.base + "/", timeout=3) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"Your computer science library", response.read())
            self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        with urllib.request.urlopen(self.base + "/api/library", timeout=3) as response:
            payload = json.loads(response.read())
            self.assertEqual(payload["stats"]["works"], 47)
            self.assertTrue(payload["actionToken"])

    def test_pdf_range_request(self) -> None:
        request = urllib.request.Request(
            self.base + "/content/books/sicp.pdf",
            headers={"Range": "bytes=0-4"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"%PDF-")
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")

    def test_action_requires_token(self) -> None:
        request = urllib.request.Request(
            self.base + "/api/action",
            data=b'{"action":"open","path":"books/sicp.pdf"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=3)
        self.assertEqual(caught.exception.code, 403)
        caught.exception.close()

    def test_non_loopback_host_is_rejected(self) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request("GET", "/api/health", headers={"Host": "example.com"})
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        connection.close()

    def test_running_library_is_detected(self) -> None:
        self.assertEqual(library_ui.find_running_library(self.port), self.base)


if __name__ == "__main__":
    unittest.main()
