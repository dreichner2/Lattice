from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.build_update_manifest import ASSET_NAME, build_manifest, main, stable_version
from scripts.sign_update_manifest import (
    PRODUCTION_PUBLIC_KEY_SHA256,
    verify_private_key_identity,
)


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_KEY_SOURCE = ROOT / "windows" / "CSLibrary.Windows" / "UpdateSecurity.cs"
PROMOTION_SOURCE = ROOT / "windows" / "CSLibrary.Windows" / "UpdateCandidateSession.cs"
WINDOWS_BUILD_SOURCE = ROOT / "windows" / "build-windows.ps1"
WINDOWS_INSTALL_SOURCE = ROOT / "windows" / "install.ps1"


def production_public_der() -> bytes:
    source = PUBLIC_KEY_SOURCE.read_text(encoding="utf-8")
    match = re.search(
        r"-----BEGIN PUBLIC KEY-----(.*?)-----END PUBLIC KEY-----",
        source,
        flags=re.DOTALL,
    )
    if not match:
        raise AssertionError("embedded production public key is missing")
    return base64.b64decode("".join(match.group(1).split()), validate=True)


class UpdateManifestTests(unittest.TestCase):
    def test_builds_stable_version_pinned_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / ASSET_NAME
            archive.write_bytes(b"verified Windows application bytes")
            manifest = build_manifest(
                version="2.1.0",
                archive=archive,
                published_at="2026-08-21T12:00:00Z",
            )

        asset = manifest["assets"]["windows-x64"]  # type: ignore[index]
        self.assertEqual(manifest["schemaVersion"], 2)
        self.assertEqual(manifest["releaseVersion"], "2.1.0")
        self.assertEqual(manifest["releaseTag"], "v2.1.0")
        self.assertEqual(asset["size"], len(b"verified Windows application bytes"))
        self.assertEqual(
            asset["sha256"],
            hashlib.sha256(b"verified Windows application bytes").hexdigest(),
        )
        self.assertEqual(
            asset["url"],
            "https://github.com/dreichner2/cs-library/releases/download/"
            "v2.1.0/Lattice-Windows-win-x64.zip",
        )

    def test_rejects_prerelease_build_metadata_and_leading_zero(self) -> None:
        for value in ("2.1.0-beta.1", "2.1.0+build", "02.1.0", "2.1", "v2.1.0"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "stable"):
                stable_version(value)

    def test_rejects_wrong_repository_and_archive_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wrong_name = Path(temporary) / "app.zip"
            wrong_name.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, ASSET_NAME):
                build_manifest(
                    version="2.1.0",
                    archive=wrong_name,
                    published_at="2026-08-21T12:00:00Z",
                )
            right_name = Path(temporary) / ASSET_NAME
            right_name.write_bytes(b"x")
            with self.assertRaisesRegex(ValueError, "exactly"):
                build_manifest(
                    version="2.1.0",
                    archive=right_name,
                    repository="attacker/repository",
                    published_at="2026-08-21T12:00:00Z",
                )

    def test_cli_writes_deterministic_utf8_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / ASSET_NAME
            output = root / "update-manifest.json"
            archive.write_bytes(b"archive")
            result = main(
                [
                    "--version",
                    "2.1.0",
                    "--archive",
                    str(archive),
                    "--published-at",
                    "2026-08-21T12:00:00Z",
                    "--output",
                    str(output),
                ]
            )
            first = output.read_bytes()
            main(
                [
                    "--version",
                    "2.1.0",
                    "--archive",
                    str(archive),
                    "--published-at",
                    "2026-08-21T12:00:00Z",
                    "--output",
                    str(output),
                ]
            )
            second = output.read_bytes()
        self.assertEqual(result, 0)
        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertEqual(json.loads(first)["releaseTag"], "v2.1.0")

    def test_signing_fingerprint_matches_embedded_production_key(self) -> None:
        self.assertEqual(
            hashlib.sha256(production_public_der()).hexdigest(),
            PRODUCTION_PUBLIC_KEY_SHA256,
        )

    def test_signer_refuses_non_production_key_without_logging_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / "release.pem"
            key.write_text("sensitive test key material", encoding="utf-8")
            if os.name == "posix":
                key.chmod(0o600)
            with mock.patch(
                "scripts.sign_update_manifest.run_openssl",
                return_value=b"a different public key",
            ), self.assertRaisesRegex(ValueError, "does not match") as caught:
                verify_private_key_identity(key)
        self.assertNotIn("sensitive test key material", str(caught.exception))

    def test_signer_accepts_only_matching_public_key_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / "release.pem"
            key.write_text("not inspected by this unit test", encoding="utf-8")
            if os.name == "posix":
                key.chmod(0o600)
            with mock.patch(
                "scripts.sign_update_manifest.run_openssl",
                return_value=production_public_der(),
            ):
                result = verify_private_key_identity(key)
        self.assertEqual(result, production_public_der())

    def test_active_authority_is_written_before_shortcut_promotion(self) -> None:
        source = PROMOTION_SOURCE.read_text(encoding="utf-8")
        method = source[source.index("internal void PromoteIfReady()") :]
        method = method[: method.index("private void ArchiveActivationRecord")]
        self.assertLess(
            method.index("ActiveVersionAuthority.Promote("),
            method.index("EnsureActiveShortcut("),
        )

    def test_installer_validates_prior_authority_and_publishes_new_authority_first(self) -> None:
        source = WINDOWS_INSTALL_SOURCE.read_text(encoding="utf-8")
        self.assertIn("function Get-ValidatedActiveVersion", source)
        self.assertIn("Assert-StableSemanticVersion $ActiveVersion", source)
        self.assertNotIn('$PreviousVersion = "unknown"', source)
        self.assertIn("$ExistingVersionOrder -gt 0", source)
        self.assertIn("Refusing to replace active Lattice", source)
        self.assertIn("$ExistingVersionOrder -eq 0", source)
        self.assertIn("[string]$ExistingActive.PreviousVersion", source)

        activation = source[source.index('$ActivePath = Join-Path $Destination "active-version.json"') :]
        self.assertLess(
            activation.index("Write-JsonAtomically -Path $ActivePath"),
            activation.index("Set-LatticeShortcutAtomically -Executable $Executable"),
        )

    def test_powershell_scripts_avoid_net_core_only_relative_path_api(self) -> None:
        for path in (WINDOWS_BUILD_SOURCE, WINDOWS_INSTALL_SOURCE):
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("[IO.Path]::GetRelativePath", source)
        installer = WINDOWS_INSTALL_SOURCE.read_text(encoding="utf-8")
        self.assertNotIn('$item.Name -eq "update-files.json"', installer)
        self.assertIn("$itemPath -ceq $rootManifest", installer)


if __name__ == "__main__":
    unittest.main()
