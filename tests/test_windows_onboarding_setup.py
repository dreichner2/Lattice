from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETUP = ROOT / "windows" / "setup"
ENTRY = SETUP / "Setup-LatticeWindows.ps1"
MODULE = SETUP / "LatticeWindowsSetup.psm1"
LAUNCHER = SETUP / "Install Lattice and Connect.cmd"
GUIDE = SETUP / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-app.yml"
INSTALLER = ROOT / "windows" / "install.ps1"


class WindowsOnboardingSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entry = ENTRY.read_text(encoding="utf-8")
        cls.module = MODULE.read_text(encoding="utf-8")
        cls.launcher = LAUNCHER.read_text(encoding="utf-8")
        cls.guide = GUIDE.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_entry_defaults_to_clone_root_and_pinned_release(self) -> None:
        parameter_block = self.entry.split('$ErrorActionPreference = "Stop"', 1)[0]
        self.assertNotIn("$PSScriptRoot", parameter_block)
        self.assertIn(
            'if ([string]::IsNullOrWhiteSpace($LibraryRoot))',
            self.entry,
        )
        self.assertIn(
            '$LibraryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\\.."))',
            self.entry,
        )
        self.assertIn('-LibraryRoot "%~dp0..\\.."', self.launcher)
        self.assertRegex(self.entry, r'\$LatticeVersion\s*=\s*"v2\.2\.9"')
        self.assertIn("-PlanOnly", self.guide)
        self.assertIn("Lattice-Windows-win-x64.zip", self.module)
        self.assertIn(".sha256", self.module)
        self.assertIn("Get-FileHash", self.module)
        self.assertIn("SHA256", self.module)
        self.assertIn("-ExpectedVersion $requestedLatticeVersion", self.module)

    def test_exact_hub_and_folder_ids_are_configured(self) -> None:
        self.assertIn(
            "MTECQEG-YI6OB3G-LI5UG6T-VTGJGQ2-MBBUWW2-G4VVCNS-3DGDGL6-AV4JJAQ",
            self.module,
        )
        self.assertIn("cs-library-3b8290f24f15", self.module)
        self.assertIn('"sendreceive"', self.module)
        self.assertIn('"/rest/config/defaults/device"', self.module)
        self.assertIn('"/rest/config/defaults/folder"', self.module)
        self.assertIn('"/rest/config/devices/$encodedHub"', self.module)
        self.assertIn('"/rest/config/folders/$encodedFolder"', self.module)
        self.assertIn('Set-ObjectProperty $folder "path" $LibraryRoot', self.module)
        self.assertIn('"--scope", "user"', self.module)

    def test_credentials_stay_local_and_are_not_printed_or_put_on_command_line(self) -> None:
        self.assertIn("$localStateRoot = $env:LOCALAPPDATA", self.module)
        self.assertIn('Join-Path $localStateRoot "Syncthing"', self.module)
        self.assertIn("SyncthingHome must stay outside the synchronized clone", self.module)
        self.assertIn('@{ "X-API-Key" = $ApiKey }', self.module)
        self.assertNotRegex(self.module, r"Write-(?:Host|Output|Verbose).*\$(?:apiKey|ApiKey)")
        self.assertNotIn("--gui-apikey", self.module.lower())
        self.assertNotIn("--gui-password", self.module.lower())
        self.assertNotIn("MTECQEG", self.launcher)

    def test_setup_is_idempotent_and_refuses_ambiguous_existing_state(self) -> None:
        self.assertIn("Test-LatticeInstall", self.module)
        self.assertIn("Get-ActiveLatticeExecutable", self.module)
        self.assertIn('Join-Path $InstallDestination "active-version.json"', self.module)
        self.assertIn('Join-Path $InstallDestination "versions"', self.module)
        self.assertIn('"update-package.json"', self.module)
        self.assertIn("Get-SyncthingApiObjectOrNull", self.module)
        self.assertIn("already points at", self.module)
        self.assertIn("-ReplaceSavedLibraryRoot", self.module)
        self.assertIn('Join-Path $env:LOCALAPPDATA "CS Library"', self.module)
        self.assertIn("Another Syncthing instance owns", self.module)

    def test_stale_install_uses_only_the_requested_pinned_package(self) -> None:
        self.assertIn("$requestedLatticeVersion = $LatticeVersion.Substring(1)", self.module)
        self.assertIn("$activeLatticeVersion", self.module)
        self.assertIn("$needsLatticeInstall", self.module)
        self.assertIn("-ExpectedVersion $requestedLatticeVersion", self.module)
        self.assertIn("Lattice $requestedLatticeVersion is not active", self.module)
        reuse = self.module.index("Using the existing complete Lattice $activeLatticeVersion")
        comparison = self.module.index("$needsLatticeInstall = (")
        self.assertLess(comparison, reuse)

    def test_startup_and_hub_approval_are_explicit(self) -> None:
        self.assertIn("Lattice Syncthing.lnk", self.module)
        self.assertIn("--no-browser", self.module)
        self.assertIn("--no-console", self.module)
        self.assertIn("Hub approval is still required", self.module)
        self.assertIn('Get-Command "Set-Clipboard"', self.module)
        self.assertIn("Set-Clipboard -Value $localDeviceId", self.module)
        self.assertNotIn("Set-Clipboard -Value $connection.ApiKey", self.module)
        self.assertRegex(self.guide, r"cannot approve\s+itself")
        self.assertIn("Setup-LatticeWindows.ps1", self.launcher)

    def test_windows_ci_runs_real_offline_syncthing_onboarding_twice(self) -> None:
        self.assertIn("Smoke-test one-click onboarding with Syncthing", self.workflow)
        self.assertIn("syncthing-windows-amd64-v$($syncthingVersion).zip", self.workflow)
        self.assertIn(
            "c0b79cffa6ce5dad5ed41ede86454f3325d13ccac33447a528cb59d65fbc3a21",
            self.workflow,
        )
        self.assertIn("Windows PowerShell 5.1 onboarding smoke failed", self.workflow)
        self.assertIn("Idempotent onboarding rerun failed", self.workflow)
        self.assertGreaterEqual(self.workflow.count("& powershell.exe @arguments"), 2)
        self.assertIn('"globalAnnounceEnabled"', self.workflow)
        self.assertIn('"crashReportingEnabled"', self.workflow)
        self.assertIn("--shutdown-syncthing", self.workflow)
        self.assertIn("$disconnect.syncthingStopped -ne $true", self.workflow)
        self.assertIn("$reconnect.syncthingStarted -ne $true", self.workflow)
        self.assertIn("--resume-existing-pause", self.workflow)
        self.assertIn("$preserved.folderPaused -ne $true", self.workflow)
        self.assertIn("$resumed.resumedExistingPause -ne $true", self.workflow)
        self.assertIn("The dedicated Lattice Syncthing process still exists", self.workflow)

    def test_no_obvious_hard_coded_secret_assignment(self) -> None:
        secret_assignment = re.compile(
            r"(?im)^\s*\$(?:password|api_?key|token)\s*=\s*['\"][^$'\"]+['\"]"
        )
        self.assertIsNone(secret_assignment.search(self.module))

    @unittest.skipUnless(
        shutil.which("powershell.exe") or shutil.which("pwsh"),
        "PowerShell is required for the Windows-native setup check",
    )
    def test_powershell_parses_and_plan_only_runs_without_mutation(self) -> None:
        shell = shutil.which("powershell.exe") or shutil.which("pwsh")
        assert shell is not None
        escaped_paths = [str(path).replace("'", "''") for path in (MODULE, INSTALLER)]
        parse_command = (
            "$failed=$false; "
            + "; ".join(
                "$tokens=$null; $errors=$null; "
                f"[System.Management.Automation.Language.Parser]::ParseFile('{path}', "
                "[ref]$tokens, [ref]$errors) > $null; "
                "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_ }; $failed=$true }"
                for path in escaped_paths
            )
            + "; if ($failed) { exit 1 }"
        )
        subprocess.run(
            [shell, "-NoLogo", "-NoProfile", "-Command", parse_command],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        result = subprocess.run(
            [
                shell,
                "-NoLogo",
                "-NoProfile",
                "-File",
                str(ENTRY),
                "-PlanOnly",
            ],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("Lattice Windows onboarding plan (no changes)", result.stdout)
        self.assertIn("cs-library-3b8290f24f15", result.stdout)


if __name__ == "__main__":
    unittest.main()
