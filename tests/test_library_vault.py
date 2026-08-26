from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


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
        self.vault_root = self.base / "device-vault"
        (self.library / "books").mkdir(parents=True)
        self.payload = self.library / "books" / "sample-book.pdf"
        self.payload.write_bytes(PAYLOAD_BYTES)
        self.digest = digest_of(PAYLOAD_BYTES)
        (self.library / "books" / "sample-book.pdf.library.json").write_text(
            json.dumps({"sha256": self.digest, "bytes": len(PAYLOAD_BYTES)}),
            encoding="utf-8",
        )
        self.relative = "books/sample-book.pdf"
        self.vault = library_vault.BookVault(
            self.library,
            "test-library-id",
            vault_root=self.vault_root,
        )

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def write_stignore(self, lines: list[str]) -> None:
        (self.library / ".stignore").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---------------------------------------------------------------- happy path

    def test_check_out_stages_verified_copy_and_keeps_local(self) -> None:
        result = self.vault.check_out(self.relative)
        self.assertTrue(result["ok"])
        self.assertEqual(result["availability"], "local")
        self.assertTrue(self.payload.is_file())

        status = self.vault.status()
        entry = status["checkedOut"][self.relative]
        self.assertEqual(entry["phase"], "local")
        self.assertTrue(entry["vaultCopyReady"])
        self.assertEqual(entry["bytes"], len(PAYLOAD_BYTES))

        copy_name = json.loads(self.vault.state_path.read_text(encoding="utf-8"))["entries"][
            self.relative
        ]["copyName"]
        copy = self.vault_root / copy_name
        self.assertTrue(copy.is_file())
        self.assertEqual(digest_of(copy.read_bytes()), self.digest)

    def test_check_in_releases_local_and_ignores_path(self) -> None:
        self.write_stignore(["!/books", "!/books/**", "*"])
        self.vault.check_out(self.relative)

        result = self.vault.check_in(self.relative)
        self.assertEqual(result["availability"], "away")
        self.assertFalse(self.payload.exists())
        self.assertIn("/books/sample-book.pdf", (self.library / ".stignore").read_text(encoding="utf-8"))
        checked_out = self.vault.status()["checkedOut"]
        self.assertEqual(checked_out[self.relative]["phase"], "away")
        self.assertTrue(checked_out[self.relative]["vaultCopyReady"])

    def test_restore_round_trip_returns_identical_bytes(self) -> None:
        self.write_stignore(["!/books", "!/books/**", "/books/sample-book.pdf", "*"])
        self.vault.check_out(self.relative)
        self.vault.check_in(self.relative)

        result = self.vault.restore(self.relative)
        self.assertEqual(result["availability"], "local")
        self.assertEqual(self.payload.read_bytes(), PAYLOAD_BYTES)
        stignore = (self.library / ".stignore").read_text(encoding="utf-8")
        self.assertNotIn("sample-book.pdf", stignore)
        self.assertEqual(list(self.vault.status()["checkedOut"]), [])

    def test_full_round_trip_across_instances(self) -> None:
        self.vault.check_out(self.relative)
        reopened = library_vault.BookVault(
            self.library,
            "test-library-id",
            vault_root=self.vault_root,
        )
        reopened.check_in(self.relative)
        self.assertFalse(self.payload.exists())
        reopened.restore(self.relative)
        self.assertEqual(self.payload.read_bytes(), PAYLOAD_BYTES)

    def test_away_entry_keeps_vault_copy_across_reconcile(self) -> None:
        self.vault.check_out(self.relative)
        self.vault.check_in(self.relative)
        report = self.vault.reconcile()
        self.assertNotIn(self.relative, report["prunedCopies"])
        self.assertEqual(
            self.vault.status()["checkedOut"][self.relative]["phase"],
            "away",
        )
        # The away copy can still be restored afterwards.
        result = self.vault.restore(self.relative)
        self.assertEqual(result["availability"], "local")
        self.assertEqual(self.payload.read_bytes(), PAYLOAD_BYTES)

    # ---------------------------------------------------------------- rejections

    def test_double_check_out_is_rejected(self) -> None:
        self.vault.check_out(self.relative)
        with self.assertRaises(library_vault.VaultError):
            self.vault.check_out(self.relative)

    def test_check_in_without_checkout_is_rejected(self) -> None:
        with self.assertRaises(library_vault.VaultError):
            self.vault.check_in(self.relative)

    def test_check_out_missing_payload_is_rejected(self) -> None:
        self.payload.unlink()
        with self.assertRaises(library_vault.VaultError):
            self.vault.check_out(self.relative)

    def test_sidecar_mismatch_blocks_checkout(self) -> None:
        sidecar = self.payload.with_name(self.payload.name + ".library.json")
        record = json.loads(sidecar.read_text(encoding="utf-8"))
        record["sha256"] = "0" * 64
        sidecar.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(library_vault.VaultError):
            self.vault.check_out(self.relative)

    def test_corrupt_vault_copy_blocks_check_in(self) -> None:
        self.vault.check_out(self.relative)
        copy_name = json.loads(self.vault.state_path.read_text(encoding="utf-8"))["entries"][
            self.relative
        ]["copyName"]
        (self.vault_root / copy_name).write_bytes(b"corrupted!")
        with self.assertRaises(library_vault.VaultError):
            self.vault.check_in(self.relative)
        self.assertTrue(self.payload.exists())

    def test_invalid_relative_paths_are_rejected(self) -> None:
        for bad in ("../outside.pdf", "/abs/path.pdf", "", "books/.hidden.pdf", "..\\escape.pdf"):
            with self.assertRaises(library_vault.VaultError):
                self.vault.check_out(bad)

    def test_library_id_mismatch_resets_state(self) -> None:
        self.vault.check_out(self.relative)
        foreign = library_vault.BookVault(
            self.library,
            "another-library",
            vault_root=self.vault_root,
        )
        self.assertEqual(foreign.status()["checkedOut"], {})

    # ---------------------------------------------------------------- reconcile

    def test_reconcile_finalizes_completed_return(self) -> None:
        self.vault.check_out(self.relative)
        state = json.loads(self.vault.state_path.read_text(encoding="utf-8"))
        state["entries"][self.relative]["phase"] = "return-pending"
        self.vault.state_path.write_text(json.dumps(state), encoding="utf-8")
        self.payload.unlink()

        report = self.vault.reconcile()
        self.assertIn(self.relative, report["finalizedReturns"])
        checked_out = self.vault.status()["checkedOut"]
        self.assertEqual(checked_out[self.relative]["phase"], "away")
        self.assertTrue(checked_out[self.relative]["vaultCopyReady"])
        self.assertFalse(self.payload.exists())
        self.assertIn(
            "/books/sample-book.pdf",
            (self.library / ".stignore").read_text(encoding="utf-8"),
        )

    def test_reconcile_reverts_return_when_payload_survived(self) -> None:
        self.vault.check_out(self.relative)
        state = json.loads(self.vault.state_path.read_text(encoding="utf-8"))
        state["entries"][self.relative]["phase"] = "return-pending"
        self.vault.state_path.write_text(json.dumps(state), encoding="utf-8")

        report = self.vault.reconcile()
        self.assertIn(self.relative, report["revertedReturns"])
        self.assertEqual(
            self.vault.status()["checkedOut"][self.relative]["phase"],
            "local",
        )
        self.assertTrue(self.payload.exists())

    def test_reconcile_completes_interrupted_restore(self) -> None:
        self.vault.check_out(self.relative)
        state = json.loads(self.vault.state_path.read_text(encoding="utf-8"))
        state["entries"][self.relative]["phase"] = "restore-pending"
        self.vault.state_path.write_text(json.dumps(state), encoding="utf-8")
        self.payload.unlink()

        report = self.vault.reconcile()
        self.assertIn(self.relative, report["completedRestores"])
        self.assertEqual(self.payload.read_bytes(), PAYLOAD_BYTES)
        checked_out = self.vault.status()["checkedOut"]
        # The staged vault copy survives as a ``local`` entry, matching the
        # state a fresh check-out would have produced.
        self.assertEqual(checked_out[self.relative]["phase"], "local")

    def test_reconcile_prunes_orphan_copies(self) -> None:
        orphan = self.vault_root / "orphan-copy.pdf"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_bytes(b"nobody references me")

        report = self.vault.reconcile()
        self.assertIn("orphan-copy.pdf", report["prunedCopies"])
        self.assertFalse(orphan.exists())
        self.assertTrue(self.vault.state_path.is_file())


if __name__ == "__main__":
    unittest.main()
