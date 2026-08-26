from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import library_ui  # noqa: E402

PAYLOAD_BYTES = b"vault server fixture payload\n" * 4000
IMPORTED_ACCESS = "User-provided local copy; redistribution not authorized"


def digest_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_sidecar(payload: Path, relative: str) -> None:
    digest = digest_of(PAYLOAD_BYTES)
    record = {
        "access": IMPORTED_ACCESS,
        "added_at": "2026-08-25T00:00:00+00:00",
        "ai": {},
        "authors": ["Fixture Author"],
        "bytes": len(PAYLOAD_BYTES),
        "edition": "",
        "embedded_metadata": {},
        "import": {"method": "lattice-ui", "originalFilename": payload.name},
        "material_type": "book",
        "metadata_status": "local-fallback",
        "path": relative,
        "schema_version": 2,
        "sha256": digest,
        "subject_ids": ["other"],
        "title": "Vault Fixture Book",
        "topics": [],
        "work_id": f"local-{digest[:16]}",
        "year": None,
    }
    payload.with_name(payload.name + ".library.json").write_text(
        json.dumps(record),
        encoding="utf-8",
    )


class VaultServerTests(unittest.TestCase):
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
        cls.relative = "books/vault-fixture.pdf"
        cls.payload = cls.library_root / "books" / "vault-fixture.pdf"
        cls.payload.write_bytes(PAYLOAD_BYTES)
        write_sidecar(cls.payload, cls.relative)

        import os

        environment = dict(os.environ)
        environment["LATTICE_VAULT_ROOT"] = str(base / "device-vault")
        patcher = unittest.mock.patch.dict(library_ui.os.environ, environment, clear=False)
        patcher.start()
        cls._patcher = patcher
        try:
            cls.server = library_ui.create_server(0, root=cls.library_root, ui_root=ROOT / "ui")
        except BaseException:
            patcher.stop()
            raise
        cls.port = int(cls.server.server_address[1])
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    # Imported lazily so the class-level patch context stays tidy.
    import unittest.mock  # noqa: E402

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls._patcher.stop()
        cls._temporary.cleanup()

    def get_json(self, route: str) -> dict:
        with urllib.request.urlopen(self.base_url + route, timeout=5) as response:
            return json.loads(response.read())

    def post_json(self, route: str, body: dict, token: str | None) -> tuple[int, dict]:
        request = urllib.request.Request(
            self.base_url + route,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"X-Library-Token": token} if token else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as caught:
            return caught.code, json.loads(caught.read())

    def token(self) -> str:
        return self.get_json("/api/library")["actionToken"]

    def material_paths(self) -> list[str]:
        return [item["path"] for item in self.get_json("/api/library")["materials"]]

    def wait_until(self, condition, timeout: float = 8.0) -> bool:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.2)
        return condition()

    def reset_fixture(self) -> None:
        """Deterministic pre-test state: payload present, vault empty."""
        import json as json_module

        self.payload.write_bytes(PAYLOAD_BYTES)
        state_path = self.server.vault.state_path
        state = {
            "version": 1,
            "libraryId": self.server.library_id,
            "entries": {},
        }
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json_module.dumps(state), encoding="utf-8")

    def setUp(self) -> None:
        self.reset_fixture()

    # ------------------------------------------------------------------ tests

    def test_vault_status_endpoint_reports_ready(self) -> None:
        status = self.get_json("/api/vault")
        self.assertTrue(status["available"])
        self.assertIsInstance(status["checkedOut"], dict)

    def test_unauthenticated_mutation_is_rejected(self) -> None:
        status, body = self.post_json("/api/vault/checkout", {"path": self.relative}, None)
        self.assertEqual(status, 403)

    def test_checkout_keeps_local_copy_and_catalog_entry(self) -> None:
        status, body = self.post_json(
            "/api/vault/checkout", {"path": self.relative}, self.token()
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["availability"], "local")
        self.assertTrue(self.payload.is_file())
        self.assertIn(self.relative, self.material_paths())

    def test_full_cycle_away_and_restore(self) -> None:
        token = self.token()
        status, _body = self.post_json("/api/vault/checkout", {"path": self.relative}, token)
        self.assertEqual(status, 200)

        status, _body = self.post_json("/api/vault/checkin", {"path": self.relative}, token)
        self.assertEqual(status, 200)
        self.assertFalse(self.payload.is_file())
        self.assertTrue(
            self.wait_until(lambda: self.relative not in self.material_paths()),
            "catalog never dropped the released payload",
        )

        library = self.get_json("/api/library")
        self.assertTrue(library["vault"]["available"])

        status, body = self.post_json("/api/vault/restore", {"path": self.relative}, token)
        self.assertEqual(status, 200)
        self.assertEqual(body["availability"], "local")
        self.assertEqual(self.payload.read_bytes(), PAYLOAD_BYTES)
        self.assertTrue(
            self.wait_until(lambda: self.relative in self.material_paths()),
            "catalog never restored the payload",
        )

    def test_double_checkin_conflicts(self) -> None:
        token = self.token()
        status, _body = self.post_json("/api/vault/checkout", {"path": self.relative}, token)
        self.assertEqual(status, 200)
        status, _body = self.post_json("/api/vault/checkin", {"path": self.relative}, token)
        self.assertEqual(status, 200)
        status, _body = self.post_json("/api/vault/checkin", {"path": self.relative}, token)
        self.assertEqual(status, 409)

    def test_checkout_rejects_uncataloged_path(self) -> None:
        status, _body = self.post_json(
            "/api/vault/checkout",
            {"path": "../../etc/passwd"},
            self.token(),
        )
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
