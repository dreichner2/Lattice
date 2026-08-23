using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

namespace CSLibrary.Windows;

internal static class UpdateStartupRedirect
{
    /// <summary>
    /// Redirects a stale taskbar pin or directly launched rollback executable to
    /// the healthy active version. Call before constructing the main window and
    /// shut this process down when the method returns true.
    /// </summary>
    internal static bool TryRedirectToActiveVersion(IReadOnlyList<string>? arguments = null)
    {
        var installation = UpdateInstallation.TryDetect();
        if (installation is null)
            return TryRedirectPortableLauncher(
                arguments ?? Environment.GetCommandLineArgs().Skip(1).ToArray());
        installation.AssertSafeRoots();
        var activePath = Path.Combine(installation.InstallRoot, "active-version.json");
        if (!File.Exists(activePath)) return false;
        if ((File.GetAttributes(activePath) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("The active-version record cannot be a reparse point.");

        var active = UpdateService.ReadBoundedJson<ActiveVersionRecord>(activePath, 16 * 1024);
        if (active.SchemaVersion != 1
            || !DateTimeOffset.TryParse(active.PromotedAt, out var promotedAt)
            || promotedAt.Offset != TimeSpan.Zero)
            throw new InvalidDataException("The active-version record is invalid.");
        var activeVersion = StableSemanticVersion.Parse(active.Version, "active version");
        var order = installation.Version.CompareTo(activeVersion);
        if (order == 0)
        {
            try
            {
                UpdateShortcutMaintenance.EnsureActiveShortcut(
                    installation,
                    active.PreviousVersion ?? "pre-versioned",
                    Guid.NewGuid().ToString("N"));
                if (active.PreviousVersion is not null)
                {
                    UpdateVersionRetention.PruneToActiveAndPrevious(
                        installation,
                        activeVersion,
                        StableSemanticVersion.Parse(active.PreviousVersion, "previous version"));
                }
            }
            catch (Exception error) when (error is IOException
                or UnauthorizedAccessException
                or InvalidOperationException
                or COMException)
            {
                UpdateMaintenance.RecordIssue(installation, "startup-repair", error);
            }
            return false;
        }
        if (order > 0)
        {
            // A manually opened staged candidate must never redirect backward.
            // It also cannot promote itself without the one-time health token.
            return false;
        }

        var activeDirectory = Path.Combine(installation.VersionsRoot, activeVersion.ToString());
        UpdateSecurity.ValidatePackageDirectory(activeDirectory, activeVersion);
        var executable = Path.Combine(activeDirectory, "Lattice.exe");
        var start = new ProcessStartInfo(executable)
        {
            UseShellExecute = true,
            WorkingDirectory = activeDirectory,
        };
        foreach (var argument in RemoveCandidateProof(arguments ?? Environment.GetCommandLineArgs().Skip(1).ToArray()))
            start.ArgumentList.Add(argument);
        if (Process.Start(start) is null)
            throw new InvalidOperationException("The active Lattice version did not start.");
        return true;
    }

    private static bool TryRedirectPortableLauncher(IReadOnlyList<string> arguments)
    {
        var processPath = Environment.ProcessPath;
        var localApplicationData = Environment.GetFolderPath(
            Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(processPath)
            || string.IsNullOrWhiteSpace(localApplicationData)
            || !File.Exists(processPath)
            || !string.Equals(Path.GetExtension(processPath), ".exe", StringComparison.OrdinalIgnoreCase)
            || (File.GetAttributes(processPath) & FileAttributes.ReparsePoint) != 0)
            return false;

        processPath = Path.GetFullPath(processPath);
        var installRoot = Path.GetFullPath(Path.Combine(localApplicationData, "Programs", "Lattice"));
        if (!PortableLauncherMaintenance.IsOutsideInstallRoot(processPath, installRoot)) return false;
        var activePath = Path.Combine(installRoot, "active-version.json");
        if (!File.Exists(activePath)) return false;
        if ((File.GetAttributes(activePath) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("The active-version record cannot be a reparse point.");

        var active = UpdateService.ReadBoundedJson<ActiveVersionRecord>(activePath, 16 * 1024);
        if (active.SchemaVersion != 1
            || !DateTimeOffset.TryParse(active.PromotedAt, out var promotedAt)
            || promotedAt.Offset != TimeSpan.Zero)
            throw new InvalidDataException("The active-version record is invalid.");
        var activeVersion = StableSemanticVersion.Parse(active.Version, "active version");
        var assemblyVersion = typeof(UpdateStartupRedirect).Assembly.GetName().Version
            ?? throw new InvalidDataException("The portable launcher has no application version.");
        var launcherVersion = new StableSemanticVersion(
            assemblyVersion.Major,
            assemblyVersion.Minor,
            assemblyVersion.Build);
        if (launcherVersion.CompareTo(activeVersion) > 0) return false;

        var versionsRoot = Path.Combine(installRoot, "versions");
        var activeDirectory = Path.Combine(versionsRoot, activeVersion.ToString());
        UpdateSecurity.ValidatePackageDirectory(activeDirectory, activeVersion);
        var executable = Path.Combine(activeDirectory, "Lattice.exe");
        var start = new ProcessStartInfo(executable)
        {
            UseShellExecute = true,
            WorkingDirectory = activeDirectory,
        };
        foreach (var argument in RemoveCandidateProof(arguments, removeLauncherMirror: true))
            start.ArgumentList.Add(argument);
        start.ArgumentList.Add(PortableLauncherMaintenance.LauncherMirrorOption);
        start.ArgumentList.Add(processPath);
        if (Process.Start(start) is null)
            throw new InvalidOperationException("The active Lattice version did not start.");
        return true;
    }

    private static IEnumerable<string> RemoveCandidateProof(
        IReadOnlyList<string> arguments,
        bool removeLauncherMirror = false)
    {
        for (var index = 0; index < arguments.Count; index++)
        {
            if (arguments[index] is "--update-candidate" or "--update-token"
                || (removeLauncherMirror
                    && arguments[index] == PortableLauncherMaintenance.LauncherMirrorOption))
            {
                if (index + 1 < arguments.Count) index += 1;
                continue;
            }
            yield return arguments[index];
        }
    }
}

internal static class UpdateShortcutMaintenance
{
    internal static void EnsureActiveShortcut(
        UpdateInstallation installation,
        string previousVersion,
        string operationId)
    {
        if (!OperatingSystem.IsWindows())
            throw new PlatformNotSupportedException("Lattice shortcut promotion requires Windows.");
        var executable = Path.Combine(installation.VersionDirectory, "Lattice.exe");
        var startMenu = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "Microsoft", "Windows", "Start Menu", "Programs");
        Directory.CreateDirectory(startMenu);
        var shortcutPath = Path.Combine(startMenu, "Lattice.lnk");
        if (File.Exists(shortcutPath)
            && string.Equals(ReadShortcutTarget(shortcutPath), executable, StringComparison.OrdinalIgnoreCase))
            return;

        var temporaryPath = Path.Combine(startMenu, $".Lattice-{operationId}.lnk");
        var rollbackRoot = Path.Combine(installation.InstallRoot, "rollback");
        Directory.CreateDirectory(rollbackRoot);
        var backupPath = Path.Combine(
            rollbackRoot,
            $"Lattice-{previousVersion}-{operationId}.lnk");
        CreateShortcut(temporaryPath, executable);
        try
        {
            if (File.Exists(shortcutPath))
                File.Replace(temporaryPath, shortcutPath, backupPath, ignoreMetadataErrors: true);
            else
                File.Move(temporaryPath, shortcutPath);
        }
        finally
        {
            if (File.Exists(temporaryPath)) File.Delete(temporaryPath);
        }
    }

    private static string? ReadShortcutTarget(string path)
    {
        object? shell = null;
        object? shortcut = null;
        try
        {
            var shellType = Type.GetTypeFromProgID("WScript.Shell")
                ?? throw new InvalidOperationException("Windows Script Host is unavailable.");
            shell = Activator.CreateInstance(shellType)
                ?? throw new InvalidOperationException("Windows Script Host did not start.");
            dynamic dynamicShell = shell;
            shortcut = dynamicShell.CreateShortcut(path);
            dynamic dynamicShortcut = shortcut;
            return dynamicShortcut.TargetPath as string;
        }
        finally
        {
            ReleaseCom(shortcut);
            ReleaseCom(shell);
        }
    }

    private static void CreateShortcut(string path, string executable)
    {
        object? shell = null;
        object? shortcut = null;
        try
        {
            var shellType = Type.GetTypeFromProgID("WScript.Shell")
                ?? throw new InvalidOperationException("Windows Script Host is unavailable.");
            shell = Activator.CreateInstance(shellType)
                ?? throw new InvalidOperationException("Windows Script Host did not start.");
            dynamic dynamicShell = shell;
            shortcut = dynamicShell.CreateShortcut(path);
            dynamic dynamicShortcut = shortcut;
            dynamicShortcut.TargetPath = executable;
            dynamicShortcut.WorkingDirectory = Path.GetDirectoryName(executable)!;
            dynamicShortcut.IconLocation = $"{executable},0";
            dynamicShortcut.Description = "A shared knowledge library";
            dynamicShortcut.Save();
        }
        finally
        {
            ReleaseCom(shortcut);
            ReleaseCom(shell);
        }
        if (!File.Exists(path))
            throw new IOException("The replacement Lattice shortcut was not created.");
    }

    private static void ReleaseCom(object? value)
    {
        if (value is not null && Marshal.IsComObject(value)) Marshal.FinalReleaseComObject(value);
    }
}

internal static class UpdateMaintenance
{
    internal static void RecordIssue(UpdateInstallation installation, string operation, Exception error)
    {
        try
        {
            Directory.CreateDirectory(installation.UpdatesRoot);
            var message = error.Message.Replace('\r', ' ').Replace('\n', ' ');
            if (message.Length > 1000) message = message[..1000];
            File.AppendAllText(
                Path.Combine(installation.UpdatesRoot, "maintenance.log"),
                $"[{DateTimeOffset.UtcNow:O}] {operation}: {message}{Environment.NewLine}");
        }
        catch (Exception writeError) when (writeError is IOException or UnauthorizedAccessException)
        {
            // Maintenance logging cannot change activation state.
        }
    }
}

internal static class UpdateVersionRetention
{
    internal static void PruneToActiveAndPrevious(
        UpdateInstallation installation,
        StableSemanticVersion active,
        StableSemanticVersion previous)
    {
        installation.AssertSafeRoots();
        var runningExecutables = ReadRunningLatticeExecutables(out var processInventoryComplete);
        if (!processInventoryComplete) return;
        foreach (var directory in Directory.EnumerateDirectories(installation.VersionsRoot))
        {
            StableSemanticVersion version;
            try
            {
                version = StableSemanticVersion.Parse(Path.GetFileName(directory), "retained version");
            }
            catch (InvalidDataException)
            {
                continue;
            }
            // Retention is allowed to prune only versions older than the
            // authority it was given. A concurrently staged or newly promoted
            // higher version must survive maintenance from an older process.
            if (version == active
                || version == previous
                || version.CompareTo(active) > 0) continue;
            if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0) continue;
            var executable = Path.GetFullPath(Path.Combine(directory, "Lattice.exe"));
            if (runningExecutables.Contains(executable)) continue;

            // Only delete a complete, recognized Lattice version directory.
            // Unknown content and staging directories are left untouched.
            try
            {
                UpdateSecurity.ValidatePackageDirectory(directory, version);
                var retiredRoot = Path.Combine(installation.UpdatesRoot, "retired");
                Directory.CreateDirectory(retiredRoot);
                var retired = Path.Combine(retiredRoot, $"{version}-{Guid.NewGuid():N}");
                Directory.Move(directory, retired);
                try
                {
                    Directory.Delete(retired, recursive: true);
                }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException)
                {
                    UpdateMaintenance.RecordIssue(installation, "retired-version-cleanup", error);
                }
            }
            catch (Exception error) when (error is IOException
                or UnauthorizedAccessException
                or InvalidDataException
                or System.Security.Cryptography.CryptographicException)
            {
                // Windows may still hold a file mapping for an older process.
                // Corrupt or incomplete obsolete packages are likewise not
                // deletion authority. A later successful promotion can retry
                // without blocking the healthy active version's startup.
            }
        }
    }

    private static HashSet<string> ReadRunningLatticeExecutables(out bool complete)
    {
        var paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        complete = true;
        foreach (var process in Process.GetProcessesByName("Lattice"))
        {
            using (process)
            {
                try
                {
                    var path = process.MainModule?.FileName;
                    if (!string.IsNullOrWhiteSpace(path)) paths.Add(Path.GetFullPath(path));
                }
                catch (Exception error) when (error is InvalidOperationException
                    or System.ComponentModel.Win32Exception
                    or NotSupportedException)
                {
                    // An inaccessible process is not a deletion authorization;
                    // abort this pruning pass rather than guessing its path.
                    complete = false;
                }
            }
        }
        var current = Environment.ProcessPath;
        if (!string.IsNullOrWhiteSpace(current)) paths.Add(Path.GetFullPath(current));
        return paths;
    }

    internal static bool IsVersionRunning(string versionDirectory)
    {
        var running = ReadRunningLatticeExecutables(out var complete);
        if (!complete) return true;
        var executable = Path.GetFullPath(Path.Combine(versionDirectory, "Lattice.exe"));
        return running.Contains(executable);
    }
}
