"""Static contract tests for the Windows-native Lattice shell.

These checks are intentionally runnable on macOS/Linux CI. The Windows workflow
can additionally exercise the packaged WPF/WebView2 process through its bounded
``--smoke-test`` launch mode.
"""

from __future__ import annotations

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "windows" / "CSLibrary.Windows"
APP_XAML = WINDOWS / "App.xaml"
APP_CODE = WINDOWS / "App.xaml.cs"
WINDOW_XAML = WINDOWS / "MainWindow.xaml"
WINDOW_CODE = WINDOWS / "MainWindow.xaml.cs"
UPDATE_CANDIDATE_CODE = WINDOWS / "UpdateCandidateSession.cs"
UPDATE_STARTUP_CODE = WINDOWS / "UpdateStartupRedirect.cs"
UPDATE_MODELS_CODE = WINDOWS / "UpdateModels.cs"
UPDATE_SERVICE_CODE = WINDOWS / "UpdateService.cs"
LIBRARY_MOVE_CODE = WINDOWS / "LibraryMoveClient.cs"
NATIVE_EJECT_CODE = WINDOWS / "NativeDriveEjector.cs"
EJECT_HELPER_CODE = WINDOWS / "EjectHelperWindow.cs"
PORTABLE_LAUNCHER_CODE = WINDOWS / "PortableLauncherUpdate.cs"
EXTERNAL_VOLUME_CODE = WINDOWS / "ExternalLibraryVolumeRecord.cs"
WINDOWS_BUILD = ROOT / "windows" / "build-windows.ps1"
WINDOWS_INSTALLER = ROOT / "windows" / "install.ps1"
XAML_NAME = "{http://schemas.microsoft.com/winfx/2006/xaml}Name"
XAML_KEY = "{http://schemas.microsoft.com/winfx/2006/xaml}Key"


def named_element(tree: ET.ElementTree, name: str) -> ET.Element:
    for element in tree.iter():
        if element.attrib.get(XAML_NAME) == name:
            return element
    raise AssertionError(f"Missing x:Name={name!r}")


class WindowsNativeShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app_tree = ET.parse(APP_XAML)
        cls.window_tree = ET.parse(WINDOW_XAML)
        cls.app_xaml = APP_XAML.read_text(encoding="utf-8")
        cls.app_code = APP_CODE.read_text(encoding="utf-8")
        cls.window_xaml = WINDOW_XAML.read_text(encoding="utf-8")
        cls.window_code = WINDOW_CODE.read_text(encoding="utf-8")
        cls.update_candidate_code = UPDATE_CANDIDATE_CODE.read_text(encoding="utf-8")
        cls.update_startup_code = UPDATE_STARTUP_CODE.read_text(encoding="utf-8")
        cls.update_models_code = UPDATE_MODELS_CODE.read_text(encoding="utf-8")
        cls.update_service_code = UPDATE_SERVICE_CODE.read_text(encoding="utf-8")
        cls.library_move_code = LIBRARY_MOVE_CODE.read_text(encoding="utf-8")
        cls.native_eject_code = NATIVE_EJECT_CODE.read_text(encoding="utf-8")
        cls.eject_helper_code = EJECT_HELPER_CODE.read_text(encoding="utf-8")
        cls.portable_launcher_code = PORTABLE_LAUNCHER_CODE.read_text(encoding="utf-8")
        cls.external_volume_code = EXTERNAL_VOLUME_CODE.read_text(encoding="utf-8")
        cls.windows_build = WINDOWS_BUILD.read_text(encoding="utf-8")
        cls.windows_installer = WINDOWS_INSTALLER.read_text(encoding="utf-8")

    def test_native_palette_matches_shared_lattice_surface(self) -> None:
        keyed_values = {
            element.attrib[XAML_KEY]: (element.text or "").strip()
            for element in self.app_tree.iter()
            if XAML_KEY in element.attrib
        }
        self.assertEqual(keyed_values["LatticeCanvasColor"], "#F4F3EF")
        self.assertEqual(keyed_values["LatticeRaisedColor"], "#F8F7F4")
        self.assertEqual(keyed_values["LatticeInkColor"], "#17191F")
        self.assertEqual(keyed_values["LatticeAccentColor"], "#5362D9")
        self.assertEqual(keyed_values["LatticeSuccessColor"], "#3F8B67")
        self.assertIn("Segoe UI Variable Text", self.app_xaml)
        self.assertIn("Georgia", self.app_xaml)
        self.assertNotIn("#0D0F14", self.window_xaml)

    def test_duplicate_command_bar_is_removed_and_loading_state_stays_native(self) -> None:
        for name in (
            "BackButton",
            "HomeButton",
            "ReloadButton",
            "StatusPill",
            "LibraryPathButton",
            "AddMaterialsButton",
            "MoreButton",
            "MoveLibraryMenuItem",
            "UpdateMenuItem",
            "TopChrome",
            "TopChromeRow",
        ):
            self.assertNotIn(f'x:Name="{name}"', self.window_xaml)

        for name in (
            "UpdateProgress",
            "LoadingOverlay",
            "LoadingCard",
            "RetryButton",
            "ChooseFolderButton",
        ):
            named_element(self.window_tree, name)

        loading_card = named_element(self.window_tree, "LoadingCard")
        self.assertEqual(loading_card.attrib.get("Focusable"), "True")
        self.assertEqual(
            loading_card.attrib.get("AutomationProperties.Name"),
            "Lattice status",
        )
        self.assertIn('AutomationProperties.LiveSetting="Polite"', self.window_xaml)
        self.assertIn('KeyboardNavigation.TabNavigation="Cycle"', self.window_xaml)
        self.assertNotIn('Height="58"', self.window_xaml)
        self.assertIn('Height="2"', self.window_xaml)

    def test_webview_and_native_add_contract_remain_compatible(self) -> None:
        browser = named_element(self.window_tree, "Browser")
        self.assertEqual(browser.attrib.get("AllowExternalDrop"), "True")
        self.assertEqual(browser.attrib.get("DefaultBackgroundColor"), "#F4F3EF")
        for contract in (
            '"CS Library"',
            '"SharedReaderState.js"',
            "NativeBridgeBootstrapScript",
            "WebMessageReceived",
            '"app.checkForUpdates"',
            '"app.moveLibrary"',
            '"app.disconnectLibrary"',
            '"app.reconnectLibrary"',
            '"app.openLibraryFolder"',
            '"app.chooseLibrary"',
            '"app.reload"',
            "sharedLibraryChooseFiles",
            '"addFilesInput"',
            "?app=windows",
            '"LatticeServer.exe"',
            '"SharedLibraryServer.exe"',
            '"CSLibraryServer.exe"',
        ):
            self.assertIn(contract, self.window_code)

    def test_all_xaml_handlers_have_code_behind_methods(self) -> None:
        handlers: set[str] = set()
        for element in self.window_tree.iter():
            for attribute, value in element.attrib.items():
                if attribute.rsplit("}", 1)[-1] in {
                    "Click",
                    "Loaded",
                    "Closing",
                    "SizeChanged",
                    "PreviewKeyDown",
                }:
                    handlers.add(value)
        for handler in handlers:
            self.assertRegex(
                self.window_code,
                rf"\b{re.escape(handler)}\s*\(",
                f"XAML handler {handler} has no code-behind method",
            )

    def test_switching_loading_and_bounds_behaviors_are_present(self) -> None:
        self.assertIn("if (_openingLibrary) return;", self.window_code)
        self.assertIn("SetLibrarySwitchingEnabled(false);", self.window_code)
        self.assertIn("Browser.Visibility = Visibility.Hidden;", self.window_code)
        self.assertIn("Browser.Visibility = Visibility.Visible;", self.window_code)
        self.assertIn("RestoreWindowBounds();", self.window_code)
        self.assertIn("SaveWindowBounds();", self.window_code)
        self.assertIn("SystemParameters.VirtualScreenWidth", self.window_code)
        self.assertIn('string.Equals(title, "Lattice"', self.window_code)
        self.assertIn("IsOwnedServerUri", self.window_code)
        self.assertIn("!uri.IsLoopback", self.window_code)

    def test_move_library_is_native_verified_and_syncthing_aware(self) -> None:
        self.assertIn("MoveLibrary_Click", self.window_code)
        self.assertIn("LibraryMoveClient.MoveAsync", self.window_code)
        self.assertIn(
            "The installed app, updater, and private reader data stay on this PC",
            self.window_code,
        )
        self.assertIn("including its publications and adjacent metadata", self.window_code)
        self.assertIn("copy and verify every file", self.window_code)
        self.assertIn("redirect the same Syncthing folder ID", self.window_code)
        self.assertIn("_libraryMoveInProgress", self.window_code)
        self.assertIn("_serverProcess is null || _serverProcess.HasExited", self.window_code)
        self.assertIn("LatticeStorage.exe", self.library_move_code)
        self.assertIn("cs-library-3b8290f24f15", self.library_move_code)
        self.assertIn('start.ArgumentList.Add("--protected-path")', self.library_move_code)
        self.assertIn("scripts\\move_library.py", self.windows_build)
        self.assertIn("--name LatticeStorage", self.windows_build)
        self.assertIn("Tools\\LatticeStorage.exe", self.windows_build)
        self.assertIn("Tools/LatticeStorage.exe", self.windows_installer)
        self.assertGreaterEqual(
            self.windows_installer.count("Tools\\LatticeStorage.exe"),
            2,
        )

    def test_external_drive_disconnect_releases_and_reconnects_syncthing(self) -> None:
        self.assertIn("DisconnectLibrary_Click", self.window_code)
        self.assertIn("ReconnectLibrary_Click", self.window_code)
        self.assertIn("LibraryMoveClient.DisconnectAsync", self.window_code)
        self.assertIn("LibraryMoveClient.ReconnectAsync", self.window_code)
        self.assertIn("StopOwnedServer();", self.window_code)
        self.assertIn("Application.Current.Shutdown();", self.window_code)
        self.assertIn('"--operation"', self.library_move_code)
        self.assertIn('"disconnect"', self.library_move_code)
        self.assertIn('"reconnect"', self.library_move_code)
        self.assertIn('"--start-if-needed"', self.library_move_code)
        self.assertIn('"--resume-existing-pause"', self.library_move_code)
        self.assertIn('"--shutdown-syncthing"', self.library_move_code)
        self.assertIn("SyncthingStopped", self.window_code)
        self.assertIn("outcome.FolderPaused", self.window_code)
        self.assertIn("Resume this exact folder, rescan it, and wait for Up to Date now?", self.window_code)
        self.assertIn('"--previous-source"', self.library_move_code)

    def test_external_drive_eject_uses_only_native_configuration_manager(self) -> None:
        for contract in (
            "CM_Request_Device_EjectW",
            "CM_Locate_DevNodeW",
            "CM_Get_Parent",
            "IOCTL_STORAGE_GET_DEVICE_NUMBER",
            "53F56307-B6BF-11D0-94F2-00A0C91EFB8B",
            "PNP_VetoOutstandingOpen",
            "Veto type:",
            "Veto name:",
            "Configuration Manager result:",
        ):
            self.assertIn(contract, self.native_eject_code)

        native_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in WINDOWS.glob("*.cs")
        )
        for forbidden in (
            "FSCTL_LOCK_VOLUME",
            "FSCTL_DISMOUNT_VOLUME",
            "IOCTL_VOLUME_OFFLINE",
            "DeleteVolumeMountPoint",
            "SetVolumeMountPoint",
        ):
            self.assertNotIn(forbidden, native_sources)

        disconnect = self.window_code[
            self.window_code.index("private async void DisconnectLibrary_Click") :
            self.window_code.index("private async void ReconnectLibrary_Click")
        ]
        self.assertLess(
            disconnect.index("LibraryMoveClient.DisconnectAsync"),
            disconnect.index("StopOwnedServerForEject"),
        )
        self.assertLess(
            disconnect.index("StopOwnedServerForEject"),
            disconnect.index("ExternalLibraryVolumeRecord.Save"),
        )
        self.assertLess(
            disconnect.index("ExternalLibraryVolumeRecord.Save"),
            disconnect.index("CaptureWebViewProcessIdentities"),
        )
        self.assertLess(
            disconnect.index("CaptureWebViewProcessIdentities"),
            disconnect.index("Browser.Dispose()"),
        )
        self.assertLess(
            disconnect.index("Browser.Dispose()"),
            disconnect.index("LaunchNativeEjectHelper"),
        )
        self.assertIn('"Ejecting…"', disconnect)
        self.assertNotIn("NativeDriveEjector.RequestEject", disconnect)
        self.assertIn("Application.Current.Shutdown();", disconnect)

        launch_helper = self.window_code[
            self.window_code.index("private static Process LaunchNativeEjectHelper") :
            self.window_code.index("private async Task ReleaseLibraryWebViewAsync")
        ]
        self.assertIn("Environment.ProcessPath", launch_helper)
        self.assertIn("Environment.CurrentDirectory = SettingsRoot", launch_helper)
        self.assertIn("WorkingDirectory = SettingsRoot", launch_helper)
        self.assertIn("target.DriveRoot", launch_helper)
        self.assertIn("waitProcesses", launch_helper)

        capture_processes = self.window_code[
            self.window_code.index("private IReadOnlyList<EjectProcessIdentity> CaptureWebViewProcessIdentities") :
            self.window_code.index("private static Process LaunchNativeEjectHelper")
        ]
        self.assertIn("webView.Environment", capture_processes)
        self.assertIn("GetProcessInfos()", capture_processes)
        self.assertIn("webView.BrowserProcessId", capture_processes)
        self.assertIn("process.StartTime.ToUniversalTime().Ticks", capture_processes)

        helper_start = self.app_code.index("EjectHelperOptions.IsRequested(e.Args)")
        update_redirect = self.app_code.index("UpdateStartupRedirect.TryRedirectToActiveVersion(e.Args)")
        self.assertLess(helper_start, update_redirect)
        self.assertIn('private const string HelperSwitch = "--eject-helper"', self.eject_helper_code)
        self.assertIn('private const string WaitProcessOption = "--wait-process"', self.eject_helper_code)
        wait_for_parent = self.eject_helper_code.index("await WaitForTrackedProcessesExitAsync(_options)")
        request_eject = self.eject_helper_code.index("NativeDriveEjector.RequestEject(")
        self.assertLess(wait_for_parent, request_eject)
        self.assertIn("process.StartTime.ToUniversalTime().Ticks", self.eject_helper_code)
        self.assertIn("MaximumEjectAttempts = 8", self.eject_helper_code)
        self.assertIn("TrackedProcessExitTimeout = TimeSpan.FromSeconds(45)", self.eject_helper_code)
        self.assertIn("HandleDrainDelay = TimeSpan.FromSeconds(2)", self.eject_helper_code)
        self.assertIn("NativeDriveEjector.IsTransientCloseVeto(result)", self.eject_helper_code)
        self.assertIn("PNP_VetoPendingClose", self.native_eject_code)
        self.assertIn("PNP_VetoOutstandingOpen", self.native_eject_code)
        self.assertIn("actualDeviceInstanceId", self.native_eject_code)
        self.assertIn('"last-eject-diagnostic.txt"', self.eject_helper_code)
        self.assertIn("after every tracked Lattice process exited", self.eject_helper_code)
        veto_branch = self.eject_helper_code.index("if (!result.Success)")
        safe_to_unplug = self.eject_helper_code.rindex('"Safe to unplug"')
        self.assertLess(veto_branch, safe_to_unplug)

    def test_external_volume_record_drives_automatic_verified_reconnect(self) -> None:
        for contract in (
            "VolumeName",
            "RelativeLibraryPath",
            "DeviceInstanceId",
            "SyncthingManaged",
            "Directory.GetLogicalDrives()",
            "NativeDriveEjector.GetVolumeName",
        ):
            self.assertIn(contract, self.external_volume_code)
        for contract in (
            "ExternalLibraryVolumeRecord.TryResolveLibraryRoot",
            "ReconnectLibrarySyncAsync",
            "previousSource: externalVolume?.OriginalLibraryRoot",
            "Restarting Syncthing, rescanning the folder, and waiting for Up to Date",
            "ExternalLibraryVolumeRecord.Delete",
        ):
            self.assertIn(contract, self.window_code)

    def test_bounded_packaged_smoke_mode_emits_proof_contract(self) -> None:
        for option in ("--smoke-test", "--library-root", "--smoke-output", "--smoke-pdf"):
            self.assertIn(option, self.app_code)
        self.assertIn('"lattice-smoke.json"', self.app_code)
        self.assertIn('"lattice-webview.png"', self.app_code)
        self.assertIn('"lattice-pdf-reader.png"', self.app_code)
        self.assertIn("TimeSpan.FromSeconds(50)", self.window_code)
        self.assertIn("CapturePreviewAsync", self.window_code)
        self.assertIn("CoreWebView2CapturePreviewImageFormat.Png", self.window_code)
        self.assertIn('document.getElementById("addButton")', self.window_code)
        self.assertIn('document.getElementById("libraryGrid")', self.window_code)
        self.assertIn('brand === "Lattice"', self.window_code)
        self.assertIn("hasNativeAddBridge", self.window_code)
        self.assertIn("hasNativeDesktopBridge", self.window_code)
        self.assertIn("hasInlineDesktopMenu", self.window_code)
        self.assertIn("WaitForPdfReaderAsync", self.window_code)
        self.assertIn("WaitForPdfShelfReturnAsync", self.window_code)
        self.assertIn(
            "querySelector('button[data-layout=\"spread\"]')",
            self.window_code,
        )
        self.assertIn('key: "ArrowRight"', self.window_code)
        self.assertIn("arrowNavigationWorked", self.window_code)
        self.assertIn('getElementById("closeButton")', self.window_code)
        self.assertIn("ShelfReturnWorked", self.window_code)
        self.assertIn("Application.Current.Shutdown(exitCode);", self.window_code)

    def test_pdf_reader_can_request_true_native_fullscreen(self) -> None:
        self.assertIn("ContainsFullScreenElementChanged", self.window_code)
        self.assertIn("ContainsFullScreenElement", self.window_code)
        self.assertIn("SetWebContentFullscreen", self.window_code)
        self.assertNotIn("TopChrome", self.window_code)
        self.assertIn("WindowStyle = WindowStyle.None", self.window_code)
        self.assertIn("ResizeMode = ResizeMode.NoResize", self.window_code)
        self.assertIn("|| _webContentFullscreen", self.window_code)
        self.assertIn('"pdf-reader-lifecycle.mjs"', self.windows_build)

    def test_native_caption_customization_keeps_high_contrast_system_chrome(self) -> None:
        self.assertIn("DwmSetWindowAttribute", self.app_code)
        self.assertIn("SystemParameters.HighContrast", self.app_code)
        self.assertIn("OperatingSystem.IsWindowsVersionAtLeast", self.app_code)

    def test_updater_is_health_gated_consent_driven_and_nonblocking(self) -> None:
        redirect = self.app_code.index("UpdateStartupRedirect.TryRedirectToActiveVersion(e.Args)")
        construct_window = self.app_code.index("new MainWindow(options)")
        self.assertLess(redirect, construct_window)
        self.assertIn("UpdateCandidateSession.TryOpenFromCurrentProcess", self.window_code)
        self.assertIn("ReportServerHealthyAsync(", self.window_code)
        self.assertIn("ownedServer", self.window_code)
        self.assertIn(
            'start.ArgumentList.Add(_candidateLaunchRequested ? "0" : "8766");',
            self.window_code,
        )
        navigation = self.window_code[
            self.window_code.index("private async void NavigationCompleted") :
            self.window_code.index("private void NewWindowRequested")
        ]
        interface_probe = navigation.index("await WaitForSharedUiAsync(interfaceTimeout.Token)")
        navigation_health = navigation.index(
            "ReportWebViewNavigationHealthy(navigatedUri, e.IsSuccess)"
        )
        self.assertLess(interface_probe, navigation_health)
        self.assertIn("or System.Security.Cryptography.CryptographicException", self.app_code)
        self.assertIn("_candidatePromotionError", self.window_code)
        self.assertIn("StartBackgroundUpdateCheckOnce", self.window_code)
        self.assertIn("(_candidateLaunchRequested && !_candidatePromoted)", self.window_code)
        self.assertIn("private string DisplayVersion", self.window_code)
        self.assertIn("version = DisplayVersion", self.window_code)
        self.assertIn('$"Version {_updateCandidate.CandidateVersion}"', self.window_code)
        self.assertIn("_updateCheckTask ??=", self.window_code)

        consent = self.window_code.index("MessageBoxButton.YesNo")
        download = self.window_code.index("DownloadAndStageAsync(")
        launch = self.window_code.index("LaunchCandidate(staged, _libraryRoot)")
        self.assertLess(consent, download)
        self.assertLess(download, launch)
        self.assertIn("closes automatically only after", self.window_code)
        self.assertIn("desktop launcher will then be replaced at that same path", self.window_code)
        self.assertIn("private void ShowUpdateProgress", self.window_code)
        self.assertIn("_updateProgressValue = Math.Clamp(value, 0, 100)", self.window_code)
        self.assertIn("UpdateProgress.Value = _updateProgressValue", self.window_code)
        self.assertIn("PostNativeStatus();", self.window_code)

        # The promoted candidate dismisses only the exact superseded Lattice
        # executable. A launcher PID protects current handoffs, while the
        # canonical-path fallback lets the first fixed release cleanly update
        # from 2.0.1 activation records that do not contain that field.
        self.assertIn("public int? LauncherProcessId", self.update_models_code)
        self.assertIn(
            "LauncherProcessId = Environment.ProcessId",
            self.update_service_code,
        )
        promotion = self.update_candidate_code.index("_promoted = true;")
        shutdown = self.update_candidate_code.index(
            "RequestSupersededLauncherShutdown();"
        )
        self.assertLess(promotion, shutdown)
        self.assertIn(
            "Process.GetProcessById(launcherProcessId)",
            self.update_candidate_code,
        )
        self.assertIn(
            'Process.GetProcessesByName("Lattice")',
            self.update_candidate_code,
        )
        self.assertIn("process.CloseMainWindow()", self.update_candidate_code)
        self.assertIn("expectedExecutable", self.update_candidate_code)

        for field in (
            "LauncherProcessStartTimeUtcTicks",
            "LauncherExecutablePath",
            "LauncherMirrorPath",
            "LauncherMirrorSha256",
        ):
            self.assertIn(f"public {('long?' if field == 'LauncherProcessStartTimeUtcTicks' else 'string?')} {field}", self.update_models_code)
        self.assertIn('LauncherMirrorOption = "--launcher-mirror"', self.portable_launcher_code)
        self.assertIn('HelperSwitch = "--portable-update-helper"', self.portable_launcher_code)
        self.assertIn("Environment.SpecialFolder.DesktopDirectory", self.portable_launcher_code)
        self.assertIn("ComputeSha256(fullPath)", self.portable_launcher_code)
        self.assertIn("WaitForExactParentExitAsync(options)", self.portable_launcher_code)
        self.assertIn("parent.StartTime.ToUniversalTime().Ticks", self.portable_launcher_code)
        self.assertIn("parent.MainModule?.FileName", self.portable_launcher_code)
        self.assertIn("File.Replace(temporary, target, backup", self.portable_launcher_code)
        self.assertIn("The portable Lattice launcher changed", self.portable_launcher_code)
        helper_dispatch = self.app_code.index("PortableUpdateHelperOptions.IsRequested(e.Args)")
        self.assertLess(helper_dispatch, redirect)
        self.assertIn('case "--launcher-mirror":', self.app_code)
        self.assertIn("TryRedirectPortableLauncher", self.update_startup_code)
        self.assertIn("LauncherMirrorOption", self.update_startup_code)
        portable_launch = self.update_candidate_code.index("LaunchPortableLauncherReplacement();")
        old_window_close = self.update_candidate_code.index("RequestSupersededLauncherShutdown();")
        self.assertLess(portable_launch, old_window_close)

        # A runtime failure after the candidate's health-gated commit must not
        # claim that the now-active version was rolled back or left unpromoted.
        self.assertGreaterEqual(
            self.window_code.count("_candidateLaunchRequested && !_candidatePromoted"),
            3,
        )
        record_failure = self.window_code.index(
            "private void RecordCandidatePromotionFailure"
        )
        record_failure_body = self.window_code[record_failure : record_failure + 220]
        self.assertIn("if (_candidatePromoted) return;", record_failure_body)


if __name__ == "__main__":
    unittest.main()
