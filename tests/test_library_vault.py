from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_vault  # noqa: E402


PAYLOAD_BYTES = b"fixture book payload\n" * 5000


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BookVaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.base = Path(self._temporary.name)
        self.library = self.base / "library"
        self.vault_base = self.base / "device-vault"
        (self.library / "books").mkdir(parents=True)
        self.relative = "books/sample-book.pdf"
        self.payload = self.library / self.relative
        self.payload.write_bytes(PAYLOAD_BYTES)
        self.digest = digest_of(PAYLOAD_BYTES)
        self.sidecar = self.payload.with_name(self.payload.name + ".library.json")
        self.sidecar.write_text(
            json.dumps({"sha256": self.digest, "bytes": len(PAYLOAD_BYTES)}),
            encoding="utf-8",
        )
        self.write_stignore(["!/books", "!/books/**", "*"])
        self.vault = library_vault.BookVault(
            self.library,
            "syncthing:test-library-id",
            vault_root=self.vault_base,
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def write_stignore(self, lines: list[str]) -> None:
        (self.library / ".stignore").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def state(self) -> dict:
        return json.loads(self.vault.state_path.read_text(encoding="utf-8"))

    def entry(self, relative: str | None = None) -> dict:
        return self.state()["entries"][relative or self.relative]

    def copy_for(self, relative: str | None = None) -> Path:
        return self.vault.copy_path(self.entry(relative)["copyName"])

    def test_check_out_stages_verified_private_copy_and_keeps_local(self) -> None:
        result = self.vault.check_out(self.relative)
        self.assertEqual(result["availability"], "local")
        self.assertTrue(self.payload.is_file())
        self.assertTrue(self.sidecar.is_file())
        self.assertNotEqual(self.vault.root, self.vault_base)
        copy = self.copy_for()
        self.assertEqual(copy.read_bytes(), PAYLOAD_BYTES)
        self.assertEqual(self.entry()["phase"], "local")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.vault.root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(copy.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.vault.state_path.stat().st_mode), 0o600)

    def test_check_in_installs_first_matching_ignore_before_payload_deletion(self) -> None:
        self.vault.check_out(self.relative)
        result = self.vault.check_in(self.relative)
        self.assertEqual(result["availability"], "away")
        self.assertFalse(self.payload.exists())
        self.assertTrue(self.sidecar.is_file(), "payload-only tiering must preserve metadata")
        lines = (self.library / ".stignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "/books/sample-book.pdf")
        self.assertLess(lines.index("/books/sample-book.pdf"), lines.index("!/books/**"))
        self.assertEqual(self.entry()["phase"], "away")
        self.assertTrue(self.entry()["ignoreAdded"])

    def test_restore_round_trip_is_identical_and_removes_owned_ignore(self) -> None:
        self.vault.check_out(self.relative)
        self.vault.check_in(self.relative)
        result = self.vault.restore(self.relative)
        self.assertEqual(result["availability"], "local")
        self.assertEqual(self.payload.read_bytes(), PAYLOAD_BYTES)
        self.assertTrue(self.sidecar.is_file())
        self.assertNotIn(
            "/books/sample-book.pdf",
            (self.library / ".stignore").read_text(encoding="utf-8"),
        )
        self.assertEqual(self.vault.status()["checkedOut"], {})

    def test_preexisting_exact_ignore_is_preserved_after_restore(self) -> None:
        self.write_stignore(["!/books", "!/books/**", "/books/sample-book.pdf", "*"])
        self.vault.check_out(self.relative)
        self.vault.check_in(self.relative)
        self.assertFalse(self.entry()["ignoreAdded"])
        self.vault.restore(self.relative)
        lines = (self.library / ".stignore").read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "/books/sample-book.pdf")
        self.assertEqual(lines.count("/books/sample-book.pdf"), 1)

    def test_full_round_trip_across_instances(self) -> None:
        self.vault.check_out(self.relative)
        reopened = library_vault.BookVault(
            self.library,
            "syncthing:test-library-id",
            vault_root=self.vault_base,
        )
        reopened.check_in(self.relative)
        reopened.restore(self.relative)
        self.assertEqual(self.payload.read_bytes(), PAYLOAD_BYTES)

    def test_stable_identity_survives_library_relocation(self) -> None:
        self.vault.check_out(self.relative)
        moved = self.base / "moved-library"
        self.library.rename(moved)
        reopened = library_vault.BookVault(
            moved,
            "syncthing:test-library-id",
            vault_root=self.vault_base,
        )
        self.assertEqual(reopened.root, self.vault.root)
        self.assertEqual(reopened.status()["checkedOut"][self.relative]["phase"], "local")

    def test_different_libraries_are_isolated_and_do_not_prune_each_other(self) -> None:
        self.vault.check_out(self.relative)
        first_copy = self.copy_for()
        other_library = self.base / "other-library"
        (other_library / "books").mkdir(parents=True)
        other = library_vault.BookVault(
            other_library,
            "syncthing:another-library",
            vault_root=self.vault_base,
        )
        self.assertNotEqual(other.root, self.vault.root)
        self.assertEqual(other.reconcile()["prunedCopies"], [])
        self.assertTrue(first_copy.is_file())

    def test_identical_payloads_at_different_paths_have_distinct_copies(self) -> None:
        second_relative = "books/another/sample-book.pdf"
        second = self.library / second_relative
        second.parent.mkdir(parents=True)
        second.write_bytes(PAYLOAD_BYTES)
        second.with_name(second.name + ".library.json").write_text(
            json.dumps({"sha256": self.digest, "bytes": len(PAYLOAD_BYTES)}),
            encoding="utf-8",
        )
        self.vault.check_out(self.relative)
        self.vault.check_out(second_relative)
        first_copy = self.copy_for(self.relative)
        second_copy = self.copy_for(second_relative)
        self.assertNotEqual(first_copy.name, second_copy.name)
        self.vault.check_in(self.relative)
        self.vault.check_in(second_relative)
        self.vault.restore(self.relative)
        self.assertTrue(second_copy.is_file())
        self.vault.restore(second_relative)
        self.assertEqual(second.read_bytes(), PAYLOAD_BYTES)

    def test_local_mutation_after_checkout_blocks_check_in_without_deleting(self) -> None:
        self.vault.check_out(self.relative)
        changed = b"newer local revision"
        self.payload.write_bytes(changed)
        with self.assertRaisesRegex(library_vault.VaultError, "changed after"):
            self.vault.check_in(self.relative)
        self.assertEqual(self.payload.read_bytes(), changed)
        self.assertNotIn("/books/sample-book.pdf", (self.library / ".stignore").read_text())
        self.assertEqual(self.entry()["phase"], "local")

    def test_restore_conflict_never_overwrites_unexpected_local_payload(self) -> None:
        self.vault.check_out(self.relative)
        self.vault.check_in(self.relative)
        conflict = b"remote or user-created replacement"
        self.payload.write_bytes(conflict)
        with self.assertRaises(library_vault.VaultError):
            self.vault.restore(self.relative)
        self.assertEqual(self.payload.read_bytes(), conflict)
        report = self.vault.reconcile()
        self.assertNotIn(self.relative, report["completedRestores"])
        self.assertEqual(self.entry()["phase"], "away")

    def test_corrupt_vault_copy_blocks_check_in_and_preserves_payload(self) -> None:
        self.vault.check_out(self.relative)
        self.copy_for().write_bytes(b"corrupted")
        with self.assertRaises(library_vault.VaultError):
            self.vault.check_in(self.relative)
        self.assertEqual(self.payload.read_bytes(), PAYLOAD_BYTES)

    def test_sidecar_mismatch_blocks_checkout(self) -> None:
        self.sidecar.write_text(json.dumps({"sha256": "0" * 64}), encoding="utf-8")
        with self.assertRaises(library_vault.VaultError):
            self.vault.check_out(self.relative)

    def test_ignore_failure_rolls_back_journal_and_preserves_payload(self) -> None:
        self.vault.check_out(self.relative)
        with mock.patch.object(
            self.vault,
            "_ensure_ignore",
            side_effect=library_vault.VaultError("ignore rejected"),
        ):
            with self.assertRaises(library_vault.VaultError):
                self.vault.check_in(self.relative)
        self.assertTrue(self.payload.is_file())
        self.assertEqual(self.entry()["phase"], "local")

    def test_invalid_or_glob_paths_are_rejected(self) -> None:
        for bad in (
            "../outside.pdf",
            "/abs/path.pdf",
            "",
            "books/.hidden.pdf",
            "..\\escape.pdf",
            "books/name[1].pdf",
            "books/star*.pdf",
            "books/trailing .pdf",
        ):
            with self.subTest(path=bad):
                with self.assertRaises(library_vault.VaultError):
                    self.vault.check_out(bad)

    def test_vault_inside_synchronized_library_is_rejected(self) -> None:
        with self.assertRaises(library_vault.VaultError):
            library_vault.BookVault(
                self.library,
                "syncthing:unsafe",
                vault_root=self.library / "device-vault",
            )

    def test_corrupt_state_fails_closed_and_preserves_every_copy(self) -> None:
        self.vault.check_out(self.relative)
        copy = self.copy_for()
        self.vault.state_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(library_vault.VaultError):
            self.vault.reconcile()
        self.assertTrue(copy.is_file())

    def test_library_id_mismatch_fails_closed(self) -> None:
        self.vault.check_out(self.relative)
        state = self.state()
        state["libraryId"] = "wrong-library"
        self.vault.state_path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(library_vault.VaultError, "different library"):
            self.vault.status()

    def test_reconcile_finalizes_completed_return_and_keeps_sidecar(self) -> None:
        self.vault.check_out(self.relative)
        state = self.state()
        state["entries"][self.relative].update(
            {"phase": "return-pending", "ignoreAdded": True}
        )
        self.vault._write_state(state)
        self.vault._ensure_ignore(self.relative)
        self.payload.unlink()
        report = self.vault.reconcile()
        self.assertIn(self.relative, report["finalizedReturns"])
        self.assertEqual(self.entry()["phase"], "away")
        self.assertTrue(self.sidecar.is_file())

    def test_reconcile_reverts_return_when_payload_survived(self) -> None:
        self.vault.check_out(self.relative)
        state = self.state()
        state["entries"][self.relative].update(
            {"phase": "return-pending", "ignoreAdded": True}
        )
        self.vault._write_state(state)
        self.vault._ensure_ignore(self.relative)
        report = self.vault.reconcile()
        self.assertIn(self.relative, report["revertedReturns"])
        self.assertEqual(self.entry()["phase"], "local")
        self.assertNotIn("/books/sample-book.pdf", (self.library / ".stignore").read_text())

    def test_reconcile_completes_interrupted_restore_and_drops_vault_entry(self) -> None:
        self.vault.check_out(self.relative)
        self.vault.check_in(self.relative)
        state = self.state()
        state["entries"][self.relative]["phase"] = "restore-pending"
        self.vault._write_state(state)
        copy = self.copy_for()
        report = self.vault.reconcile()
        self.assertIn(self.relative, report["completedRestores"])
        self.assertEqual(self.payload.read_bytes(), PAYLOAD_BYTES)
        self.assertEqual(self.vault.status()["checkedOut"], {})
        self.assertFalse(copy.exists())

    def test_reconcile_self_heals_missing_local_entry_to_away(self) -> None:
        self.vault.check_out(self.relative)
        self.payload.unlink()
        report = self.vault.reconcile()
        self.assertIn(self.relative, report["selfHealedAway"])
        self.assertEqual(self.entry()["phase"], "away")
        self.assertEqual(
            (self.library / ".stignore").read_text().splitlines()[0],
            "/books/sample-book.pdf",
        )

    def test_reconcile_prunes_managed_orphan_but_preserves_unknown_files(self) -> None:
        self.vault.check_out(self.relative)
        managed_name = (
            "vault-"
            + "1" * 64
            + "-"
            + "2" * 64
            + ".pdf"
        )
        managed = self.vault.root / managed_name
        managed.write_bytes(b"orphan")
        unknown = self.vault.root / "user-note.txt"
        unknown.write_text("preserve me", encoding="utf-8")
        report = self.vault.reconcile()
        self.assertIn(managed_name, report["prunedCopies"])
        self.assertFalse(managed.exists())
        self.assertTrue(unknown.is_file())


if __name__ == "__main__":
    unittest.main()
