from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_library_layout  # noqa: E402


class LibraryLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.layout = json.loads((ROOT / "library-layout.json").read_text(encoding="utf-8"))
        self.taxonomy = json.loads(
            (ROOT / "library-taxonomy.json").read_text(encoding="utf-8")
        )

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
        self.assertEqual(syncthing["folder_label"], "Lattice")
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

    def test_taxonomy_is_required_and_subject_agnostic(self) -> None:
        self.assertIn("library-taxonomy.json", self.layout["required_root_entries"])
        self.assertEqual(self.taxonomy["schema_version"], 1)
        self.assertEqual(self.taxonomy["default_import_subject_id"], "other")
        self.assertEqual(self.taxonomy["catalog_default_subject_id"], "computer-science")
        self.assertEqual(
            [subject["id"] for subject in self.taxonomy["subjects"]],
            [
                "computer-science",
                "electrical-engineering",
                "computer-engineering",
                "mathematics",
                "statistics-data-science",
                "physics",
                "mechanical-engineering",
                "civil-engineering",
                "chemical-engineering",
                "general-engineering",
                "interdisciplinary",
                "other",
            ],
        )
        subject_ids = {subject["id"] for subject in self.taxonomy["subjects"]}
        assignments = [
            *self.taxonomy["topic_defaults"].values(),
            *self.taxonomy["work_assignments"].values(),
        ]
        assigned_ids = {
            subject_id
            for assignment in assignments
            for subject_id in (assignment if isinstance(assignment, list) else [assignment])
        }
        self.assertTrue(assigned_ids <= subject_ids)
        self.assertEqual(
            self.taxonomy["topic_defaults"]["mathematics-statistics"],
            "mathematics",
        )
        self.assertEqual(
            self.taxonomy["work_assignments"]["books-riscv-spec-unprivileged-pdf"],
            ["computer-engineering", "computer-science"],
        )
        self.assertEqual(
            self.taxonomy["work_assignments"]["books-mackay-information-theory-pdf"],
            [
                "interdisciplinary",
                "electrical-engineering",
                "statistics-data-science",
                "computer-science",
                "mathematics",
            ],
        )
        self.assertEqual(
            self.taxonomy["work_assignments"]["art-of-hpc"],
            ["computer-science", "computer-engineering", "general-engineering"],
        )
        self.assertEqual(
            self.taxonomy["work_assignments"]["papers-shannon-1948-pdf"],
            [
                "electrical-engineering",
                "mathematics",
                "statistics-data-science",
                "computer-science",
            ],
        )

    def test_sidecars_append_suffix_to_full_payload_filename(self) -> None:
        sidecars = self.layout["sidecars"]
        self.assertEqual(sidecars["suffix"], ".library.json")
        self.assertIs(sidecars["append_to_full_filename"], True)
        self.assertEqual(sidecars["location"], "adjacent")
        self.assertIs(sidecars["shared_via_syncthing"], True)
        payload = Path("books") / "example.pdf"
        sidecar = payload.with_name(payload.name + sidecars["suffix"])
        self.assertEqual(sidecar.as_posix(), "books/example.pdf.library.json")

        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        stignore = (ROOT / ".stignore").read_text(encoding="utf-8").splitlines()
        for shared_root in self.layout["syncthing"]["shared_paths"]:
            self.assertIn(f"/{shared_root}/**", gitignore)
            self.assertIn(f"!/{shared_root}/**", stignore)
        self.assertLess(stignore.index("(?d).gitkeep"), stignore.index("!/books/**"))
        self.assertLess(stignore.index("(?d).syncthing.*.tmp"), stignore.index("!/books/**"))
        self.assertLess(stignore.index("/lectures/catalog.json"), stignore.index("!/lectures/**"))

    def test_taxonomy_validator_accepts_multi_subject_assignments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            taxonomy = json.loads(json.dumps(self.taxonomy))
            taxonomy["work_assignments"]["cross-disciplinary"] = [
                "computer-science",
                "mathematics",
            ]
            (root / "library-taxonomy.json").write_text(
                json.dumps(taxonomy),
                encoding="utf-8",
            )
            errors: list[str] = []
            validate_library_layout._validate_taxonomy(root, errors)
        self.assertEqual(errors, [])

    def test_taxonomy_validator_caps_subjects_at_sidecar_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            taxonomy = json.loads(json.dumps(self.taxonomy))
            taxonomy["subjects"].extend(
                {
                    "id": f"future-subject-{index}",
                    "name": f"Future subject {index}",
                    "description": "Future taxonomy fixture",
                }
                for index in range(
                    len(taxonomy["subjects"]),
                    validate_library_layout.MAX_ASSIGNED_SUBJECTS + 1,
                )
            )
            (root / "library-taxonomy.json").write_text(
                json.dumps(taxonomy),
                encoding="utf-8",
            )
            errors: list[str] = []
            validate_library_layout._validate_taxonomy(root, errors)
        self.assertTrue(any("must not exceed 64" in error for error in errors))

    def test_boolean_schema_versions_are_rejected(self) -> None:
        boolean_layout = {**self.layout, "schema_version": True}
        with mock.patch.object(
            validate_library_layout,
            "load_layout",
            return_value=boolean_layout,
        ):
            self.assertIn(
                "schema_version must be 1",
                validate_library_layout.validate_layout(ROOT),
            )

        boolean_taxonomy = {**self.taxonomy, "schema_version": True}
        errors: list[str] = []
        with mock.patch.object(
            validate_library_layout,
            "load_taxonomy",
            return_value=boolean_taxonomy,
        ):
            validate_library_layout._validate_taxonomy(ROOT, errors)
        self.assertIn("library-taxonomy.json schema_version must be 1", errors)


if __name__ == "__main__":
    unittest.main()
