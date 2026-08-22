using System.Diagnostics;
using System.Text.Json;

namespace CSLibrary.Windows;

internal static class UpdateInstaller
{
    public static bool IsInstallerInvocation(IReadOnlyList<string> arguments) =>
        arguments.Count > 0 && arguments[0] == "--apply-update";

    public static int Run(IReadOnlyList<string> arguments)
    {
        Directory.CreateDirectory(UpdateService.UpdatesRoot);
        InstallerOptions? options = null;
        try
        {
            if (File.Exists(UpdateService.InstallerErrorPath))
                File.Delete(UpdateService.InstallerErrorPath);
            options = InstallerOptions.Parse(arguments);
            Log($"Waiting for Lattice process {options.ParentProcessId} to exit");
            WaitForParent(options.ParentProcessId);
            Install(options);
            Log("Update installed and the new app was launched");
            return 0;
        }
        catch (Exception error)
        {
            var message = $"The automatic update was rolled back.\n\n{error.Message}";
            try { File.WriteAllText(UpdateService.InstallerErrorPath, message); } catch (IOException) { }
            Log($"Update failed: {error}");
            if (options is not null) TryLaunchPrevious(options.TargetPath);
            return 1;
        }
    }

    private static void Install(InstallerOptions options)
    {
        var staging = Path.GetFullPath(options.StagingPath).TrimEnd(Path.DirectorySeparatorChar);
        var target = Path.GetFullPath(options.TargetPath).TrimEnd(Path.DirectorySeparatorChar);
        ValidateInstallerPaths(staging, target, options.ExpectedCommit);

        var newManifest = UpdateService.ValidateStagedPackage(staging, options.ExpectedCommit);
        var oldManifest = UpdateService.TryReadOwnedFiles(target);
        var newFiles = new HashSet<string>(newManifest.Files, StringComparer.OrdinalIgnoreCase);
        var oldFiles = new HashSet<string>(oldManifest?.Files ?? [], StringComparer.OrdinalIgnoreCase);
        var affectedFiles = new HashSet<string>(newFiles, StringComparer.OrdinalIgnoreCase);
        affectedFiles.UnionWith(oldFiles);

        var backupRoot = Path.Combine(UpdateService.UpdatesRoot, $"backup-{options.ExpectedCommit}");
        if (Directory.Exists(backupRoot)) Directory.Delete(backupRoot, recursive: true);
        Directory.CreateDirectory(backupRoot);
        var createdFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        foreach (var relative in affectedFiles)
        {
            var current = UpdateService.ResolveOwnedPath(target, relative);
            if (!File.Exists(current))
            {
                createdFiles.Add(relative);
                continue;
            }
            var backup = UpdateService.ResolveOwnedPath(backupRoot, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(backup)!);
            CopyWithRetry(current, backup, overwrite: false);
        }

        try
        {
            Log($"Installing {newFiles.Count} application files");
            foreach (var relative in newFiles)
            {
                var source = UpdateService.ResolveOwnedPath(staging, relative);
                var destination = UpdateService.ResolveOwnedPath(target, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                CopyWithRetry(source, destination, overwrite: true);
            }
            foreach (var relative in oldFiles.Except(newFiles, StringComparer.OrdinalIgnoreCase))
            {
                var obsolete = UpdateService.ResolveOwnedPath(target, relative);
                DeleteWithRetry(obsolete);
            }
            UpdateService.ValidateStagedPackage(target, options.ExpectedCommit);

            var cleanup = new PendingUpdateCleanup
            {
                Commit = options.ExpectedCommit,
                BackupPath = backupRoot,
                StagingPath = staging,
            };
            File.WriteAllText(
                UpdateService.PendingCleanupPath,
                JsonSerializer.Serialize(cleanup, new JsonSerializerOptions { WriteIndented = true }));
            Launch(Path.Combine(target, "Lattice.exe"));
        }
        catch
        {
            Log("Installation failed; restoring all previous application files");
            Restore(target, backupRoot, affectedFiles, createdFiles);
            throw;
        }
    }

    private static void Restore(
        string target,
        string backupRoot,
        IEnumerable<string> affectedFiles,
        IReadOnlySet<string> createdFiles)
    {
        foreach (var relative in affectedFiles)
        {
            var destination = UpdateService.ResolveOwnedPath(target, relative);
            var backup = UpdateService.ResolveOwnedPath(backupRoot, relative);
            if (File.Exists(backup))
            {
                Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                CopyWithRetry(backup, destination, overwrite: true);
            }
            else if (createdFiles.Contains(relative))
            {
                DeleteWithRetry(destination);
            }
        }
    }

    private static void ValidateInstallerPaths(string staging, string target, string commit)
    {
        var updatesPrefix = Path.GetFullPath(UpdateService.UpdatesRoot).TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        if (!staging.StartsWith(updatesPrefix, StringComparison.OrdinalIgnoreCase)
            || !string.Equals(Path.GetFileName(staging), $"staged-{commit}", StringComparison.Ordinal)
            || string.Equals(staging, target, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("The update staging path is unsafe.");

        var targetRoot = Path.GetPathRoot(target);
        if (string.IsNullOrWhiteSpace(targetRoot)
            || string.Equals(target, targetRoot.TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase)
            || !File.Exists(Path.Combine(target, "Lattice.exe")))
            throw new InvalidDataException("The installed application path is unsafe.");
    }

    private static void WaitForParent(int processId)
    {
        try
        {
            using var process = Process.GetProcessById(processId);
            if (!process.WaitForExit(60_000))
                throw new TimeoutException("Lattice did not close within 60 seconds.");
        }
        catch (ArgumentException)
        {
            // It exited before the helper opened the process handle.
        }
    }

    private static void CopyWithRetry(string source, string destination, bool overwrite)
    {
        Exception? lastError = null;
        for (var attempt = 0; attempt < 80; attempt++)
        {
            try
            {
                File.Copy(source, destination, overwrite);
                return;
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            {
                lastError = error;
                Thread.Sleep(250);
            }
        }
        throw new IOException($"Could not replace {Path.GetFileName(destination)}.", lastError);
    }

    private static void DeleteWithRetry(string path)
    {
        if (!File.Exists(path)) return;
        Exception? lastError = null;
        for (var attempt = 0; attempt < 80; attempt++)
        {
            try
            {
                File.Delete(path);
                return;
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException)
            {
                lastError = error;
                Thread.Sleep(250);
            }
        }
        throw new IOException($"Could not remove obsolete file {Path.GetFileName(path)}.", lastError);
    }

    private static void Launch(string executable)
    {
        var start = new ProcessStartInfo(executable)
        {
            UseShellExecute = true,
            WorkingDirectory = Path.GetDirectoryName(executable)!,
        };
        if (Process.Start(start) is null)
            throw new InvalidOperationException("The updated Lattice app did not relaunch.");
    }

    private static void TryLaunchPrevious(string target)
    {
        try
        {
            var executable = Path.Combine(target, "Lattice.exe");
            if (File.Exists(executable)) Launch(executable);
        }
        catch (Exception error)
        {
            Log($"The restored app could not relaunch: {error.Message}");
        }
    }

    private static void Log(string message)
    {
        try
        {
            var line = $"[{DateTimeOffset.UtcNow:O}] {message}{Environment.NewLine}";
            File.AppendAllText(Path.Combine(UpdateService.UpdatesRoot, "installer.log"), line);
        }
        catch (IOException)
        {
            // Logging is best-effort and must not affect rollback.
        }
    }

    private sealed record InstallerOptions(
        int ParentProcessId,
        string StagingPath,
        string TargetPath,
        string ExpectedCommit)
    {
        public static InstallerOptions Parse(IReadOnlyList<string> arguments)
        {
            if (!IsInstallerInvocation(arguments))
                throw new InvalidDataException("The update installer command is invalid.");
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            for (var index = 1; index < arguments.Count; index += 2)
            {
                if (index + 1 >= arguments.Count
                    || !arguments[index].StartsWith("--", StringComparison.Ordinal)
                    || !values.TryAdd(arguments[index], arguments[index + 1]))
                    throw new InvalidDataException("The update installer arguments are invalid.");
            }
            if (!values.TryGetValue("--parent-pid", out var rawPid)
                || !int.TryParse(rawPid, out var pid) || pid <= 1
                || !values.TryGetValue("--staging", out var staging)
                || !values.TryGetValue("--target", out var target)
                || !values.TryGetValue("--expected-commit", out var commit)
                || !UpdateService.IsFullCommit(commit)
                || values.Count != 4)
                throw new InvalidDataException("The update installer arguments are incomplete.");
            return new InstallerOptions(pid, staging, target, commit);
        }
    }
}
