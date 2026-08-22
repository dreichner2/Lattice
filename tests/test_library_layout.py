from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_library_layout  # noqa: E402


class LibraryLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = json.loads((ROOT / "library-layout.json").read_text(encoding="utf-8"))

    def test_checked_in_layout_is_clone_ready(self) -> None:
        self.assertEqual(validate_library_layout.validate_layout(ROOT), [])

    def test_content_scaffold_covers_catalog_collections(self) -> None:
        self.assertEqual(
            self.layout["content_directories"],
            [
                "books",
                "books/art-of-hpc",
                "books/software-foundations",
                "papers",
                "papers/mit-6006",
                "lectures",
            ],
        )

    def test_syncthing_scope_contains_library_data_not_app_state(self) -> None:
        syncthing = self.layout["syncthing"]
        self.assertEqual(syncthing["folder_id"], "cs-library-3b8290f24f15")
        self.assertEqual(syncthing["folder_label"], "CS Library")
        self.assertEqual(syncthing["folder_type"], "sendreceive")
        shared = set(syncthing["shared_paths"])
        self.assertEqual(
            shared,
            {
                "books",
                "papers",
                "lectures",
            },
        )
        self.assertTrue(
            shared.isdisjoint(
                {".git", ".library-cache", "work", "windows/build", "CATALOG.md", "metadata"}
            )
        )


if __name__ == "__main__":
    unittest.main()
