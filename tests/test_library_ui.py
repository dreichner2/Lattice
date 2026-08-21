from __future__ import annotations

import http.client
import json
import re
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


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_ui  # noqa: E402


def write_test_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="EPUB/book.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""",
        )
        archive.writestr(
            "EPUB/book.opf",
            """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">fixture</dc:identifier><dc:title>Fixture EPUB</dc:title>
    <dc:creator>Test Author</dc:creator><dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="one" href="text/one.xhtml" media-type="application/xhtml+xml"/>
    <item id="two" href="text/two.xhtml" media-type="application/xhtml+xml"/>
    <item id="style" href="styles/book.css" media-type="text/css"/>
    <item id="image" href="images/diagram.svg" media-type="image/svg+xml" properties="cover-image"/>
  </manifest>
  <spine><itemref idref="one"/><itemref idref="two"/></spine>
</package>""",
        )
        archive.writestr(
            "EPUB/nav.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<body><nav epub:type="toc" role="doc-toc"><ol>
<li><a href="text/one.xhtml#start">The Beginning</a><ol><li><a href="text/one.xhtml#details">Details</a></li></ol></li>
<li><a href="text/two.xhtml">The End</a></li>
</ol></nav></body></html>""",
        )
        archive.writestr(
            "EPUB/text/one.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><head><link rel="stylesheet" href="../styles/book.css"/></head><body><h1 id="start">The Beginning</h1><p id="details">Readable text.</p><img src="../images/diagram.svg"/></body></html>""",
        )
        archive.writestr(
            "EPUB/text/two.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>The End</h1></body></html>""",
        )
        archive.writestr("EPUB/styles/book.css", "body { color: #222; }")
        archive.writestr(
            "EPUB/images/diagram.svg",
            "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"10\" height=\"10\"><rect width=\"10\" height=\"10\"/></svg>",
        )


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.library = library_ui.build_library(ROOT)

    def test_catalog_shape(self) -> None:
        self.assertEqual(self.library["stats"]["works"], 83)
        if not (ROOT / "books").is_dir():
            self.assertEqual(self.library["stats"]["artifacts"], 0)
            self.assertEqual(self.library["stats"]["indexedArtifacts"], 112)
            self.assertFalse(self.library["stats"]["allPresent"])
            return
        self.assertEqual(self.library["stats"]["artifacts"], 112)
        self.assertEqual(self.library["stats"]["present"], 112)
        self.assertEqual(self.library["stats"]["subjects"], 11)
        self.assertTrue(self.library["stats"]["allPresent"])
        self.assertEqual(
            self.library["stats"]["materialCounts"],
            {
                "book": 53,
                "lecture": 20,
                "course-volume": 7,
                "paper": 28,
                "specification": 2,
                "standard": 2,
            },
        )

    def test_every_artifact_is_present_and_unique(self) -> None:
        if not (ROOT / "books").is_dir():
            self.skipTest("local book payloads are intentionally not committed")
        files = [file for work in self.library["works"] for file in work["files"]]
        paths = [file["path"] for file in files]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(all(file["exists"] for file in files))

    def test_collection_sizes(self) -> None:
        by_id = {work["id"]: work for work in self.library["works"]}
        self.assertEqual(by_id["mit-6006"]["fileCount"], 20)
        self.assertEqual(by_id["software-foundations"]["fileCount"], 7)

    def test_source_bundles_are_readable_editions(self) -> None:
        by_id = {work["id"]: work for work in self.library["works"]}
        self.assertEqual(
            by_id["crafting-interpreters"]["files"][0]["path"],
            "books/crafting-interpreters.epub",
        )
        self.assertEqual(
            by_id["software-engineering-google"]["files"][0]["path"],
            "books/software-engineering-google.epub",
        )
        self.assertEqual(
            by_id["pbrt"]["files"][0]["path"],
            "books/pbrt-4e.epub",
        )
        software_foundations = by_id["software-foundations"]["files"]
        self.assertEqual(len(software_foundations), 7)
        self.assertTrue(all(file["path"].endswith(".epub") for file in software_foundations))

    def test_payload_resolution_rejects_escape_and_unknown_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "books").mkdir()
            fixture = root / "books" / "fixture.pdf"
            fixture.write_bytes(b"%PDF-1.1\n%%EOF\n")
            allowed = {"books/fixture.pdf"}
            self.assertEqual(library_ui.resolve_payload(root, "books/fixture.pdf", allowed), fixture.resolve())
            for value in ("../CATALOG.md", "/etc/passwd", "books/unknown.pdf"):
                with self.assertRaises(ValueError):
                    library_ui.resolve_payload(root, value, allowed)

    def test_byte_ranges(self) -> None:
        self.assertEqual(library_ui.parse_byte_range("bytes=0-4", 100), (0, 4))
        self.assertEqual(library_ui.parse_byte_range("bytes=95-", 100), (95, 99))
        self.assertEqual(library_ui.parse_byte_range("bytes=-5", 100), (95, 99))
        with self.assertRaises(ValueError):
            library_ui.parse_byte_range("bytes=100-101", 100)

    def test_uncataloged_readable_file_becomes_clean_new_arrival(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "books").mkdir()
            (root / "metadata").mkdir()
            (root / "manifests").mkdir()
            (root / "CATALOG.md").write_text("# Empty catalog\n", encoding="utf-8")
            (root / "books" / "a-new-ai-book-2e.pdf").write_bytes(b"%PDF-1.1\n%%EOF\n")
            library = library_ui.build_library(root)
        self.assertEqual(library["stats"]["works"], 1)
        self.assertEqual(library["stats"]["newArrivals"], 1)
        self.assertEqual(library["works"][0]["title"], "A New AI Book 2e")
        self.assertEqual(library["materials"][0]["title"], "A New AI Book 2e")
        self.assertFalse(library["works"][0]["cataloged"])

    def test_fetch_catalog_detail_block_becomes_new_arrival(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "books").mkdir()
            (root / "metadata" / "books").mkdir(parents=True)
            (root / "manifests").mkdir()
            (root / "books" / "new-book.pdf").write_bytes(b"%PDF-1.1\n%%EOF\n")
            (root / "metadata" / "books" / "new-book.json").write_text(
                json.dumps(
                    {
                        "title": "New Book",
                        "path": "books/new-book.pdf",
                        "authors": "Test Author",
                    }
                ),
                encoding="utf-8",
            )
            (root / "CATALOG.md").write_text(
                "\n".join(
                    (
                        "# Fixture catalog",
                        "",
                        "## Collection notes",
                        "",
                        "<!-- work: book:new-book -->",
                        "### [New Book](books/new-book.pdf)",
                        "",
                        "- Type: book",
                        "- Authors: Test Author",
                        "- Local path: `books/new-book.pdf`",
                    )
                ),
                encoding="utf-8",
            )
            library = library_ui.build_library(root)
        self.assertEqual(library["stats"]["works"], 1)
        self.assertEqual(library["stats"]["newArrivals"], 1)
        self.assertEqual(library["works"][0]["title"], "New Book")
        self.assertFalse(library["works"][0]["cataloged"])

    def test_study_guide_links_resolve_to_local_materials(self) -> None:
        if not (ROOT / "books").is_dir():
            self.skipTest("local book payloads are intentionally not committed")
        guide = (ROOT / "STUDY_GUIDE.md").read_text(encoding="utf-8")
        links = re.findall(r"\]\(((?:books|papers)/[^)]+)\)", guide)
        material_paths = {material["path"] for material in self.library["materials"]}
        unresolved = []
        for link in links:
            normalized = urllib.parse.unquote(link).rstrip("/")
            if normalized in material_paths:
                continue
            prefix = normalized + "/"
            if any(path.startswith(prefix) for path in material_paths):
                continue
            unresolved.append(link)
        self.assertGreaterEqual(len(links), 70)
        self.assertEqual(unresolved, [])


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
            self.assertEqual(payload["stats"]["works"], 83)
            self.assertTrue(payload["actionToken"])

    def test_pdf_range_request(self) -> None:
        if not (ROOT / "books" / "sicp.pdf").is_file():
            self.skipTest("local book payloads are intentionally not committed")
        request = urllib.request.Request(
            self.base + "/content/books/sicp.pdf",
            headers={"Range": "bytes=0-4"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(response.read(), b"%PDF-")
            self.assertEqual(response.headers["Accept-Ranges"], "bytes")
            self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")

    def test_live_event_stream_announces_current_revision(self) -> None:
        with urllib.request.urlopen(self.base + "/api/events?once=1", timeout=3) as response:
            payload = response.read().decode("utf-8")
            self.assertTrue(response.headers["Content-Type"].startswith("text/event-stream"))
            self.assertIn("event: library-ready", payload)
            self.assertIn("data: {\"revision\":", payload)

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


class EpubReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "books").mkdir()
        (self.root / "metadata" / "books").mkdir(parents=True)
        (self.root / "manifests").mkdir()
        self.epub_path = self.root / "books" / "fixture.epub"
        write_test_epub(self.epub_path)
        (self.root / "metadata" / "books" / "fixture.json").write_text(
            json.dumps(
                {
                    "title": "Fixture EPUB",
                    "path": "books/fixture.epub",
                    "authors": "Test Author",
                    "bytes": self.epub_path.stat().st_size,
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
                    "| <!-- work: fixture --> [Fixture EPUB](books/fixture.epub) | Test Author | 1e | Local | [Official](https://example.com) | Test |",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        self.server = library_ui.create_server(0, root=self.root)
        self.port = int(self.server.server_address[1])
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def test_package_exposes_spine_navigation_and_cover(self) -> None:
        package, media_types = library_ui.parse_epub_package(
            self.epub_path,
            "books/fixture.epub",
        )
        self.assertEqual(package["title"], "Fixture EPUB")
        self.assertEqual(package["authors"], ["Test Author"])
        self.assertEqual([chapter["label"] for chapter in package["chapters"]], ["The Beginning", "The End"])
        self.assertEqual(len(package["toc"]), 3)
        self.assertEqual(package["toc"][1]["depth"], 1)
        self.assertTrue(package["coverUrl"].endswith("/EPUB/images/diagram.svg"))
        self.assertEqual(media_types["EPUB/text/one.xhtml"], "application/xhtml+xml")

    def test_epub_api_and_same_origin_resource_route(self) -> None:
        query = urllib.parse.urlencode({"path": "books/fixture.epub"})
        with urllib.request.urlopen(f"{self.base}/api/epub?{query}", timeout=3) as response:
            package = json.loads(response.read())
        self.assertEqual(len(package["chapters"]), 2)

        with urllib.request.urlopen(self.base + package["chapters"][0]["url"], timeout=3) as response:
            chapter = response.read()
            self.assertEqual(response.headers["X-Frame-Options"], "SAMEORIGIN")
            self.assertIn("script-src 'none'", response.headers["Content-Security-Policy"])
            self.assertTrue(response.headers["Content-Type"].startswith("text/html"))
        self.assertIn(b"Readable text", chapter)

        style_url = package["chapters"][0]["url"].rsplit("/", 2)[0] + "/styles/book.css"
        with urllib.request.urlopen(self.base + style_url, timeout=3) as response:
            self.assertEqual(response.read(), b"body { color: #222; }")
            self.assertTrue(response.headers["Content-Type"].startswith("text/css"))

    def test_epub_resource_traversal_is_rejected(self) -> None:
        key = library_ui.encode_epub_key("books/fixture.epub")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(
                f"{self.base}/epub/{key}/EPUB/%2E%2E/META-INF/container.xml",
                timeout=3,
            )
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()


class LiveRefreshTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "books").mkdir()
        (self.root / "metadata" / "books").mkdir(parents=True)
        (self.root / "manifests").mkdir()
        fixture_bytes = b"%PDF-1.1\n%%EOF\n"
        (self.root / "books" / "fixture.pdf").write_bytes(fixture_bytes)
        (self.root / "metadata" / "books" / "fixture.json").write_text(
            json.dumps(
                {
                    "title": "Fixture Book",
                    "path": "books/fixture.pdf",
                    "bytes": len(fixture_bytes),
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
        self.server = library_ui.create_server(0, root=self.root)
        self.port = int(self.server.server_address[1])
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def _library(self) -> dict:
        with urllib.request.urlopen(self.base + "/api/library", timeout=3) as response:
            return json.loads(response.read())

    def _wait_for_artifacts(self, expected: int) -> dict:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            payload = self._library()
            if payload["stats"]["artifacts"] == expected:
                return payload
            time.sleep(0.08)
        self.fail(f"Live catalog did not reach {expected} artifacts")

    def test_added_and_removed_file_refresh_without_server_restart(self) -> None:
        initial = self._library()
        self.assertEqual(initial["stats"]["artifacts"], 1)
        initial_revision = initial["revision"]

        arrival = self.root / "books" / "live-refresh-book.pdf"
        arrival.write_bytes(b"%PDF-1.1\n% live refresh\n%%EOF\n")
        added = self._wait_for_artifacts(2)
        self.assertGreater(added["revision"], initial_revision)
        self.assertEqual(added["stats"]["newArrivals"], 1)
        self.assertIn("books/live-refresh-book.pdf", added["change"]["added"])

        arrival.unlink()
        removed = self._wait_for_artifacts(1)
        self.assertEqual(removed["stats"]["newArrivals"], 0)
        self.assertIn("books/live-refresh-book.pdf", removed["change"]["removed"])


if __name__ == "__main__":
    unittest.main()
