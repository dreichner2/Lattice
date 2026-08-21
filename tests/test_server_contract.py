from __future__ import annotations

import json
import stat
import sys
import tempfile
import threading
import unittest
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_ui  # noqa: E402


def minimal_library(root: Path) -> None:
    (root / "metadata").mkdir(parents=True)
    (root / "books").mkdir()
    (root / "CATALOG.md").write_text("# Empty catalog\n", encoding="utf-8")


class ServerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "library"
        self.ui = Path(self.temporary.name) / "ui"
        minimal_library(self.root)
        self.ui.mkdir()
        (self.ui / "index.html").write_text("<!doctype html><title>Bundled fixture UI</title>", encoding="utf-8")
        (self.ui / "styles.css").write_text("body{}", encoding="utf-8")
        (self.ui / "app.js").write_text("'use strict';", encoding="utf-8")
        self.server = library_ui.create_server(0, root=self.root, ui_root=self.ui)
        self.port = int(self.server.server_address[1])
        self.base = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def test_health_binds_protocol_to_canonical_library(self) -> None:
        with urllib.request.urlopen(self.base + "/api/health", timeout=3) as response:
            payload = json.loads(response.read())
        self.assertEqual(payload["app"], "cs-library")
        self.assertEqual(payload["protocolVersion"], library_ui.PROTOCOL_VERSION)
        self.assertEqual(payload["libraryId"], library_ui.library_identity(self.root))
        self.assertEqual(payload["root"], str(self.root.resolve()))
        self.assertEqual(library_ui.find_running_library(self.port, payload["libraryId"]), self.base)
        self.assertIsNone(library_ui.find_running_library(self.port, "wrong-library"))

    def test_ui_can_be_bundled_separately_from_content(self) -> None:
        with urllib.request.urlopen(self.base + "/", timeout=3) as response:
            self.assertIn(b"Bundled fixture UI", response.read())
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

    def test_cli_accepts_native_app_lifecycle_arguments(self) -> None:
        args = library_ui.build_parser().parse_args([
            "--root", str(self.root), "--ui-root", str(self.ui), "--parent-pid", "42", "--port", "0", "--no-browser",
        ])
        self.assertEqual(args.root, self.root)
        self.assertEqual(args.ui_root, self.ui)
        self.assertEqual(args.parent_pid, 42)


class EpubSafetyTests(unittest.TestCase):
    def _archive(self, entries: list[tuple[zipfile.ZipInfo | str, bytes]]) -> zipfile.ZipFile:
        temporary = tempfile.NamedTemporaryFile(suffix=".epub", delete=False)
        temporary.close()
        self.addCleanup(lambda: Path(temporary.name).unlink(missing_ok=True))
        with zipfile.ZipFile(temporary.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries:
                archive.writestr(name, payload)
        archive = zipfile.ZipFile(temporary.name)
        self.addCleanup(archive.close)
        return archive

    def test_rejects_symlinks_active_content_and_traversal(self) -> None:
        symlink = zipfile.ZipInfo("EPUB/link.xhtml")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        for entries in (
            [(symlink, b"target")],
            [("EPUB/reader.js", b"alert(1)")],
            [("../outside.xhtml", b"bad")],
        ):
            with self.subTest(entries=entries[0][0]):
                with self.assertRaises(ValueError):
                    library_ui._epub_archive_entries(self._archive(entries))

    def test_rejects_extreme_compression_ratio(self) -> None:
        archive = self._archive([("EPUB/huge.txt", b"A" * (library_ui.EPUB_XML_LIMIT + 1))])
        with self.assertRaises(ValueError):
            library_ui._epub_archive_entries(archive)


if __name__ == "__main__":
    unittest.main()
