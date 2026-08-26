from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import study_lab  # noqa: E402
from study_lab import StudyConflict, StudyError, StudyLab  # noqa: E402


class StudyLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.base = Path(self._temporary.name)
        self.library = self.base / "library"
        self.library.mkdir(parents=True)
        self.study_root = self.base / "study"
        self.lab = StudyLab(
            self.library,
            "study-test-library",
            study_root=self.study_root,
        )

    def tearDown(self) -> None:
        self.lab.close()
        self._temporary.cleanup()

    def make_notebook(self, title: str = "Chapter 3 notes") -> dict:
        return self.lab.create_notebook({"title": title})

    # ------------------------------------------------------------------ notebooks

    def test_create_and_get_notebook(self) -> None:
        created = self.make_notebook()
        notebook_id = created["notebook"]["id"]
        fetched = self.lab.get_notebook(notebook_id)
        self.assertEqual(fetched["notebook"]["title"], "Chapter 3 notes")
        self.assertEqual(fetched["cells"], [])
        self.assertEqual(created["notebook"]["cellCount"], 0)

    def test_database_lives_in_private_root_not_library(self) -> None:
        self.make_notebook()
        self.assertTrue((self.study_root / "Study.sqlite").is_file())
        tracked = [p.name for p in self.library.rglob("*")]
        self.assertNotIn("Study.sqlite", tracked)

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not authoritative")
    def test_private_storage_permissions(self) -> None:
        root_mode = stat.S_IMODE(self.study_root.stat().st_mode)
        database_mode = stat.S_IMODE((self.study_root / "Study.sqlite").stat().st_mode)
        self.assertEqual(root_mode, 0o700)
        self.assertEqual(database_mode, 0o600)

    def test_rejects_storage_inside_library(self) -> None:
        with self.assertRaises(StudyError):
            StudyLab(
                self.library,
                "inside-library",
                study_root=self.library / ".private-study",
            )

    def test_rejects_filesystem_root_as_storage(self) -> None:
        with self.assertRaises(StudyError):
            StudyLab(
                self.library,
                "unsafe-root",
                study_root=Path(Path.cwd().anchor),
            )

    def test_rejects_linked_storage_root(self) -> None:
        target = self.base / "linked-target"
        target.mkdir()
        linked = self.base / "linked-study"
        try:
            linked.symlink_to(target, target_is_directory=True)
        except (NotImplementedError, OSError):
            self.skipTest("Symbolic links are unavailable")
        with self.assertRaises(StudyError):
            StudyLab(self.library, "linked-library", study_root=linked)

    def test_rejects_linked_sqlite_sidecar(self) -> None:
        root = self.base / "sidecar-study"
        root.mkdir()
        target = self.base / "outside-wal"
        target.write_bytes(b"")
        try:
            (root / "Study.sqlite-wal").symlink_to(target)
        except (NotImplementedError, OSError):
            self.skipTest("Symbolic links are unavailable")
        with self.assertRaises(StudyError):
            StudyLab(self.library, "sidecar-library", study_root=root)

    def test_default_storage_namespace_is_safe_and_stable(self) -> None:
        first = study_lab.default_study_root("syncthing:folder/../unsafe")
        second = study_lab.default_study_root("syncthing:folder/../unsafe")
        self.assertEqual(first, second)
        self.assertRegex(first.name, r"^[0-9a-f]{64}$")

    def test_list_orders_by_recent_update(self) -> None:
        first = self.make_notebook("first")
        second = self.make_notebook("second")
        listed = self.lab.list_notebooks()["notebooks"]
        self.assertEqual([item["id"] for item in listed], [second["notebook"]["id"], first["notebook"]["id"]])

    def test_renames_require_fresh_revision(self) -> None:
        created = self.make_notebook()
        notebook = created["notebook"]
        renamed = self.lab.rename_notebook(
            notebook["id"],
            {"title": "Renamed", "baseUpdatedAt": notebook["updatedAt"]},
        )
        self.assertEqual(renamed["notebook"]["title"], "Renamed")
        with self.assertRaises(StudyConflict):
            self.lab.rename_notebook(
                notebook["id"],
                {"title": "Stale write", "baseUpdatedAt": notebook["updatedAt"]},
            )

    def test_invalid_titles_are_rejected(self) -> None:
        with self.assertRaises(StudyError):
            self.lab.create_notebook({"title": ""})
        with self.assertRaises(StudyError):
            self.lab.create_notebook({"title": "x" * 201})

    def test_link_notebook_to_work(self) -> None:
        created = self.make_notebook()
        notebook_id = created["notebook"]["id"]
        linked = self.lab.set_link(
            notebook_id,
            {
                "workPath": "books/sample.pdf",
                "workTitle": "Sample",
                "baseUpdatedAt": created["notebook"]["updatedAt"],
            },
        )
        self.assertEqual(linked["notebook"]["workPath"], "books/sample.pdf")
        cleared = self.lab.set_link(
            notebook_id,
            {
                "baseUpdatedAt": linked["notebookUpdatedAt"],
            },
        )
        self.assertEqual(cleared["notebook"]["workPath"], "")

    def test_invalid_work_links_are_rejected(self) -> None:
        notebook = self.make_notebook()["notebook"]
        for work_path in ("../outside.pdf", "/absolute.pdf", "books\\bad.pdf"):
            with self.assertRaises(StudyError):
                self.lab.set_link(
                    notebook["id"],
                    {
                        "workPath": work_path,
                        "baseUpdatedAt": notebook["updatedAt"],
                    },
                )

    def test_existing_notebook_mutations_require_revision(self) -> None:
        notebook = self.make_notebook()["notebook"]
        with self.assertRaises(StudyConflict):
            self.lab.rename_notebook(notebook["id"], {"title": "No revision"})
        with self.assertRaises(StudyConflict):
            self.lab.set_link(notebook["id"], {"workPath": "books/sample.pdf"})
        with self.assertRaises(StudyConflict):
            self.lab.add_cell(
                notebook["id"],
                {"kind": "python", "source": "print(1)"},
            )
        with self.assertRaises(StudyConflict):
            self.lab.delete_notebook(notebook["id"], {})

    def test_revision_tokens_increase_strictly(self) -> None:
        notebook = self.make_notebook()["notebook"]
        first = self.lab.rename_notebook(
            notebook["id"],
            {"title": "First", "baseUpdatedAt": notebook["updatedAt"]},
        )
        second = self.lab.rename_notebook(
            notebook["id"],
            {"title": "Second", "baseUpdatedAt": first["notebookUpdatedAt"]},
        )
        self.assertGreater(second["notebookUpdatedAt"], first["notebookUpdatedAt"])

    def test_delete_notebook_cascades_cells(self) -> None:
        created = self.make_notebook()
        notebook = created["notebook"]
        cell = self.lab.add_cell(
            notebook["id"],
            {
                "kind": "python",
                "source": "print(1)",
                "baseUpdatedAt": notebook["updatedAt"],
            },
        )["cell"]
        fresh = self.lab.get_notebook(notebook["id"])["notebook"]
        self.lab.delete_notebook(
            notebook["id"],
            {"baseUpdatedAt": fresh["updatedAt"]},
        )
        remaining = self.lab.list_notebooks()["notebooks"]
        self.assertEqual(remaining, [])
        with self.assertRaises(StudyError):
            self.lab.get_notebook(cell["notebookId"])

    # ------------------------------------------------------------------ cells

    def test_add_latex_and_python_cells(self) -> None:
        created = self.make_notebook()
        notebook = created["notebook"]
        latex_cell = self.lab.add_cell(
            notebook["id"],
            {
                "kind": "latex",
                "source": "\\begin{equation} e^{i\\pi} + 1 = 0 \\end{equation}",
                "baseUpdatedAt": notebook["updatedAt"],
            },
        )
        python_cell = self.lab.add_cell(
            notebook["id"],
            {
                "kind": "python",
                "source": "import numpy as np",
                "baseUpdatedAt": latex_cell["notebookUpdatedAt"],
            },
        )
        self.assertEqual(latex_cell["cell"]["kind"], "latex")
        self.assertEqual(python_cell["cell"]["kind"], "python")
        fetched = self.lab.get_notebook(notebook["id"])
        self.assertEqual(
            [cell["position"] for cell in fetched["cells"]],
            [0, 1],
        )

    def test_text_kind_is_not_supported(self) -> None:
        created = self.make_notebook()
        notebook = created["notebook"]
        with self.assertRaises(StudyError):
            self.lab.add_cell(
                notebook["id"],
                {"kind": "text", "source": "prose", "baseUpdatedAt": notebook["updatedAt"]},
            )
        with self.assertRaises(StudyError):
            self.lab.add_cell(
                notebook["id"],
                {"kind": "mixed", "source": "# heading", "baseUpdatedAt": notebook["updatedAt"]},
            )

    def test_update_cell_with_conflict_protection(self) -> None:
        created = self.make_notebook()
        notebook_id = created["notebook"]["id"]
        cell = self.lab.add_cell(
            notebook_id,
            {
                "kind": "python",
                "source": "x = 1",
                "baseUpdatedAt": created["notebook"]["updatedAt"],
            },
        )["cell"]
        token = self.fresh_notebook(notebook_id)["updatedAt"]
        updated = self.lab.update_cell(
            {"cellId": cell["id"], "source": "x = 2", "baseUpdatedAt": token}
        )
        self.assertEqual(updated["cell"]["source"], "x = 2")
        with self.assertRaises(StudyConflict):
            self.lab.update_cell(
                {"cellId": cell["id"], "source": "x = 3", "baseUpdatedAt": token}
            )

    def test_oversized_source_is_rejected(self) -> None:
        created = self.make_notebook()
        notebook = created["notebook"]
        with self.assertRaises(StudyError):
            self.lab.add_cell(
                notebook["id"],
                {
                    "kind": "latex",
                    "source": "$" + "a" * (study_lab.MAX_CELL_SOURCE_CHARS + 1),
                    "baseUpdatedAt": notebook["updatedAt"],
                },
            )

    def fresh_notebook(self, notebook_id: str) -> dict:
        return self.lab.get_notebook(notebook_id)["notebook"]

    def test_move_up_down_and_boundaries(self) -> None:
        created = self.make_notebook()
        notebook_id = created["notebook"]["id"]
        first_result = self.lab.add_cell(
            notebook_id,
            {
                "kind": "latex",
                "source": "one",
                "baseUpdatedAt": created["notebook"]["updatedAt"],
            },
        )
        second_result = self.lab.add_cell(
            notebook_id,
            {
                "kind": "python",
                "source": "two",
                "baseUpdatedAt": first_result["notebookUpdatedAt"],
            },
        )
        third_result = self.lab.add_cell(
            notebook_id,
            {
                "kind": "latex",
                "source": "three",
                "baseUpdatedAt": second_result["notebookUpdatedAt"],
            },
        )
        first = first_result["cell"]
        second = second_result["cell"]
        third = third_result["cell"]
        base = {"baseUpdatedAt": third_result["notebookUpdatedAt"]}

        moved = self.lab.move_cell({"cellId": third["id"], "direction": "up", **base})
        self.assertEqual(moved["cell"]["position"], 1)
        unchanged = self.lab.move_cell(
            {
                "cellId": first["id"],
                "direction": "up",
                "baseUpdatedAt": moved["notebookUpdatedAt"],
            }
        )
        self.assertTrue(unchanged["unchanged"])

        cells = self.lab.get_notebook(notebook_id)["cells"]
        self.assertEqual([c["id"] for c in cells], [first["id"], third["id"], second["id"]])
        self.assertEqual([c["position"] for c in cells], [0, 1, 2])

    def test_delete_cell_compacts_positions(self) -> None:
        created = self.make_notebook()
        notebook_id = created["notebook"]["id"]
        one_result = self.lab.add_cell(
            notebook_id,
            {
                "kind": "latex",
                "source": "1",
                "baseUpdatedAt": created["notebook"]["updatedAt"],
            },
        )
        two_result = self.lab.add_cell(
            notebook_id,
            {
                "kind": "python",
                "source": "2",
                "baseUpdatedAt": one_result["notebookUpdatedAt"],
            },
        )
        three_result = self.lab.add_cell(
            notebook_id,
            {
                "kind": "latex",
                "source": "3",
                "baseUpdatedAt": two_result["notebookUpdatedAt"],
            },
        )
        one = one_result["cell"]
        two = two_result["cell"]
        three = three_result["cell"]
        self.lab.delete_cell(
            {
                "cellId": two["id"],
                "baseUpdatedAt": three_result["notebookUpdatedAt"],
            }
        )
        cells = self.lab.get_notebook(notebook_id)["cells"]
        self.assertEqual([c["id"] for c in cells], [one["id"], three["id"]])
        self.assertEqual([c["position"] for c in cells], [0, 1])

    def test_stale_write_after_change_conflicts(self) -> None:
        created = self.make_notebook()
        notebook_id = created["notebook"]["id"]
        added = self.lab.add_cell(
            notebook_id,
            {
                "kind": "python",
                "source": "x = 1",
                "baseUpdatedAt": created["notebook"]["updatedAt"],
            },
        )
        cell = added["cell"]
        # A second window saves first; our now-stale base must be rejected.
        current = self.lab.update_cell(
            {
                "cellId": cell["id"],
                "source": "x = 2",
                "baseUpdatedAt": added["notebookUpdatedAt"],
            }
        )["cell"]
        with self.assertRaises(StudyConflict):
            self.lab.update_cell(
                {
                    "cellId": cell["id"],
                    "source": "x = 3",
                    "baseUpdatedAt": added["notebookUpdatedAt"],
                }
            )
        final = self.lab.get_notebook(notebook_id)["cells"][0]
        self.assertEqual(final["source"], "x = 2")
        self.assertEqual(final["updatedAt"], current["updatedAt"])


if __name__ == "__main__":
    unittest.main()
