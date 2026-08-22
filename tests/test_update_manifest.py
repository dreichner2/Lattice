from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_update_manifest import AssetInput, build_manifest, main


COMMIT = "0123456789abcdef0123456789abcdef01234567"


class UpdateManifestTests(unittest.TestCase):
    def test_builds_commit_pinned_asset_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "Lattice macOS.zip"
            archive.write_bytes(b"verified application bytes")

            manifest = build_manifest(
                commit=COMMIT,
                repository="dreichner2/cs-library",
                tag="latest-main",
                channel="main",
                assets=[AssetInput("macos-universal", archive)],
                published_at="2026-08-21T12:00:00Z",
            )

        asset = manifest["assets"]["macos-universal"]  # type: ignore[index]
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["commit"], COMMIT)
        self.assertEqual(asset["size"], len(b"verified application bytes"))
        self.assertEqual(asset["sha256"], hashlib.sha256(b"verified application bytes").hexdigest())
        self.assertEqual(
            asset["url"],
            "https://github.com/dreichner2/cs-library/releases/download/"
            "latest-main/Lattice%20macOS.zip",
        )

    def test_rejects_partial_commit_and_duplicate_platform(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "app.zip"
            archive.write_bytes(b"x")
            asset = AssetInput("windows-x64", archive)
            with self.assertRaisesRegex(ValueError, "40-character"):
                build_manifest(
                    commit="abc123",
                    repository="dreichner2/cs-library",
                    tag="latest-main",
                    channel="main",
                    assets=[asset],
                )
            with self.assertRaisesRegex(ValueError, "only once"):
                build_manifest(
                    commit=COMMIT,
                    repository="dreichner2/cs-library",
                    tag="latest-main",
                    channel="main",
                    assets=[asset, asset],
                )

    def test_cli_writes_deterministic_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "app.zip"
            output = root / "update-manifest.json"
            archive.write_bytes(b"archive")
            result = main(
                [
                    "--commit",
                    COMMIT,
                    "--repository",
                    "dreichner2/cs-library",
                    "--published-at",
                    "2026-08-21T12:00:00Z",
                    "--asset",
                    f"windows-x64={archive}",
                    "--output",
                    str(output),
                ]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, 0)
        self.assertEqual(payload["assets"]["windows-x64"]["size"], 7)


if __name__ == "__main__":
    unittest.main()
