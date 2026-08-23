using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;

namespace CSLibrary.Windows;

internal static class PortableLauncherMaintenance
{
    internal const string LauncherMirrorOption = "--launcher-mirror";
    internal static string LocalSettingsRoot { get; } = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "CS Library");

    internal static string? ResolveMirrorForUpdate(
        UpdateInstallation installation,
        string? requestedMirror,
        string currentExecutable)
    {
        currentExecutable = Path.GetFullPath(currentExecutable);
        if (TryValidateExactMirror(
                requestedMirror,
                currentExecutable,
                installation.InstallRoot,
                out var requested)) return requested;

        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (string.IsNullOrWhiteSpace(desktop)) return null;
        var defaultMirror = Path.Combine(desktop, "Lattice.exe");
        return TryValidateExactMirror(
            defaultMirror,
            currentExecutable,
            installation.InstallRoot,
            out var detected)
                ? detected
                : null;
    }

    internal static string? FindLegacyDesktopMirror(
        UpdateInstallation installation,
        string previousExecutable)
    {
        var desktop = Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (string.IsNullOrWhiteSpace(desktop)) return null;
        var mirror = Path.Combine(desktop, "Lattice.exe");
        return TryValidateExactMirror(
            mirror,
            previousExecutable,
            installation.InstallRoot,
            out var detected)
                ? detected
                : null;
    }

    internal static string ComputeSha256(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    internal static bool IsOutsideInstallRoot(string path, string installRoot)
    {
        path = Path.GetFullPath(path);
        installRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(installRoot));
        var prefix = installRoot + Path.DirectorySeparatorChar;
        return !string.Equals(path, installRoot, StringComparison.OrdinalIgnoreCase)
            && !path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }

    private static bool TryValidateExactMirror(
        string? candidate,
        string currentExecutable,
        string installRoot,
        out string mirror)
    {
        mirror = string.Empty;
        if (string.IsNullOrWhiteSpace(candidate)) return false;
        try
        {
            var fullPath = Path.GetFullPath(candidate);
            if (!string.Equals(Path.GetExtension(fullPath), ".exe", StringComparison.OrdinalIgnoreCase)
                || string.Equals(fullPath, currentExecutable, StringComparison.OrdinalIgnoreCase)
                || !IsOutsideInstallRoot(fullPath, installRoot)
                || !File.Exists(fullPath)
                || (File.GetAttributes(fullPath) & FileAttributes.ReparsePoint) != 0
                || !string.Equals(
                    ComputeSha256(fullPath),
                    ComputeSha256(currentExecutable),
                    StringComparison.Ordinal)) return false;
            mirror = fullPath;
            return true;
        }
        catch (Exception error) when (error is IOException
                                      or UnauthorizedAccessException
                                      or ArgumentException
                                      or NotSupportedException
                                      or CryptographicException)
        {
            return false;
        }
    }
}

internal sealed record PortableUpdateHelperOptions(
    int ParentProcessId,
    long ParentStartTimeUtcTicks,
    string ParentExecutablePath,
    string TargetExecutablePath,
    string ExpectedTargetSha256,
    string CandidateVersion)
{
    private const string HelperSwitch = "--portable-update-helper";

    internal static bool IsRequested(IReadOnlyList<string> arguments) =>
        arguments.Contains(HelperSwitch, StringComparer.Ordinal);

    internal static PortableUpdateHelperOptions Parse(IReadOnlyList<string> arguments)
    {
        if (!IsRequested(arguments))
            throw new ArgumentException("The portable update helper switch is missing.");
        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var index = 0; index < arguments.Count; index++)
        {
            var argument = arguments[index];
            if (string.Equals(argument, HelperSwitch, StringComparison.Ordinal)) continue;
            if (argument is not ("--parent-pid"
                or "--parent-start-time-utc-ticks"
                or "--parent-executable"
                or "--target-executable"
                or "--expected-target-sha256"
                or "--candidate-version"))
            {
                throw new ArgumentException($"Unknown portable update helper option: {argument}");
            }
            if (values.ContainsKey(argument))
                throw new ArgumentException($"Duplicate portable update helper option: {argument}");
            if (index + 1 >= arguments.Count || arguments[index + 1].StartsWith("--", StringComparison.Ordinal))
                throw new ArgumentException($"{argument} requires a value.");
            values[argument] = arguments[++index];
        }

        var parentProcessId = ParsePositiveInt(values, "--parent-pid");
        var parentStartTimeUtcTicks = ParsePositiveLong(values, "--parent-start-time-utc-ticks");
        var parentExecutable = Path.GetFullPath(Required(values, "--parent-executable"));
        var targetExecutable = Path.GetFullPath(Required(values, "--target-executable"));
        if (!string.Equals(Path.GetExtension(targetExecutable), ".exe", StringComparison.OrdinalIgnoreCase))
            throw new ArgumentException("The portable update target must be an executable file.");
        var expectedTargetSha256 = Required(values, "--expected-target-sha256");
        if (!UpdateSecurity.IsLowerHexSha256(expectedTargetSha256))
            throw new ArgumentException("The portable update target digest is invalid.");
        var candidateVersion = StableSemanticVersion.Parse(
            Required(values, "--candidate-version"),
            "portable update candidate version").ToString();
        return new PortableUpdateHelperOptions(
            parentProcessId,
            parentStartTimeUtcTicks,
            parentExecutable,
            targetExecutable,
            expectedTargetSha256,
            candidateVersion);
    }

    internal void AddArguments(ProcessStartInfo start)
    {
        start.ArgumentList.Add(HelperSwitch);
        AddValue(start, "--parent-pid", ParentProcessId.ToString(CultureInfo.InvariantCulture));
        AddValue(
            start,
            "--parent-start-time-utc-ticks",
            ParentStartTimeUtcTicks.ToString(CultureInfo.InvariantCulture));
        AddValue(start, "--parent-executable", ParentExecutablePath);
        AddValue(start, "--target-executable", TargetExecutablePath);
        AddValue(start, "--expected-target-sha256", ExpectedTargetSha256);
        AddValue(start, "--candidate-version", CandidateVersion);
    }

    private static void AddValue(ProcessStartInfo start, string option, string value)
    {
        start.ArgumentList.Add(option);
        start.ArgumentList.Add(value);
    }

    private static string Required(IReadOnlyDictionary<string, string> values, string option) =>
        values.TryGetValue(option, out var value) && !string.IsNullOrWhiteSpace(value)
            ? value
            : throw new ArgumentException($"{option} requires a value.");

    private static int ParsePositiveInt(IReadOnlyDictionary<string, string> values, string option) =>
        int.TryParse(Required(values, option), NumberStyles.None, CultureInfo.InvariantCulture, out var value)
        && value > 0
            ? value
            : throw new ArgumentException($"{option} must be a positive integer.");

    private static long ParsePositiveLong(IReadOnlyDictionary<string, string> values, string option) =>
        long.TryParse(Required(values, option), NumberStyles.None, CultureInfo.InvariantCulture, out var value)
        && value > 0
            ? value
            : throw new ArgumentException($"{option} must be a positive integer.");
}

internal static class PortableUpdateReplacement
{
    private static readonly TimeSpan ParentExitTimeout = TimeSpan.FromSeconds(30);

    internal static async Task ReplaceAsync(PortableUpdateHelperOptions options)
    {
        await WaitForExactParentExitAsync(options);

        var installation = UpdateInstallation.TryDetect()
            ?? throw new InvalidOperationException(
                "The portable replacement helper is not running from a verified Lattice installation.");
        var candidateVersion = StableSemanticVersion.Parse(
            options.CandidateVersion,
            "portable update candidate version");
        if (installation.Version != candidateVersion)
            throw new InvalidDataException("The portable replacement helper version changed.");
        UpdateSecurity.ValidatePackageDirectory(installation.VersionDirectory, candidateVersion);

        var source = Environment.ProcessPath;
        var expectedSource = Path.Combine(installation.VersionDirectory, "Lattice.exe");
        if (string.IsNullOrWhiteSpace(source)
            || !string.Equals(
                Path.GetFullPath(source),
                Path.GetFullPath(expectedSource),
                StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException(
                "Only the running verified candidate may replace a portable launcher.");
        }

        ReplaceVerifiedExecutable(
            source,
            options.TargetExecutablePath,
            options.ExpectedTargetSha256,
            installation.InstallRoot);
    }

    internal static void ReplaceVerifiedExecutable(
        string source,
        string target,
        string expectedTargetSha256,
        string installRoot)
    {
        source = Path.GetFullPath(source);
        target = Path.GetFullPath(target);
        if (!File.Exists(source)
            || (File.GetAttributes(source) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("The verified portable launcher source is unavailable.");
        if (!PortableLauncherMaintenance.IsOutsideInstallRoot(target, installRoot)
            || !File.Exists(target)
            || (File.GetAttributes(target) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException(
                "The saved portable Lattice launcher is missing or no longer a regular file.");
        if (!UpdateSecurity.IsLowerHexSha256(expectedTargetSha256)
            || !string.Equals(
                PortableLauncherMaintenance.ComputeSha256(target),
                expectedTargetSha256,
                StringComparison.Ordinal))
            throw new InvalidDataException(
                "The portable Lattice launcher changed after the update began, so it was not overwritten.");

        var sourceSha256 = PortableLauncherMaintenance.ComputeSha256(source);
        var parent = Path.GetDirectoryName(target)
            ?? throw new InvalidDataException("The portable Lattice launcher has no parent directory.");
        var operationId = Guid.NewGuid().ToString("N");
        var temporary = Path.Combine(parent, $".Lattice-update-{operationId}.exe.tmp");
        var backup = Path.Combine(parent, $".Lattice-update-{operationId}.exe.bak");
        var replaced = false;
        try
        {
            using (var input = new FileStream(source, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var output = new FileStream(
                temporary,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                1024 * 1024,
                FileOptions.WriteThrough))
            {
                input.CopyTo(output);
                output.Flush(flushToDisk: true);
            }
            if (!string.Equals(
                    PortableLauncherMaintenance.ComputeSha256(temporary),
                    sourceSha256,
                    StringComparison.Ordinal))
                throw new CryptographicException("The portable launcher replacement copy failed verification.");

            File.Replace(temporary, target, backup, ignoreMetadataErrors: true);
            replaced = true;
            if (!string.Equals(
                    PortableLauncherMaintenance.ComputeSha256(target),
                    sourceSha256,
                    StringComparison.Ordinal))
                throw new CryptographicException("The replaced portable launcher failed verification.");
            File.Delete(backup);
        }
        catch
        {
            if (replaced && File.Exists(backup))
            {
                var failed = Path.Combine(parent, $".Lattice-update-{operationId}.exe.failed");
                try
                {
                    File.Replace(backup, target, failed, ignoreMetadataErrors: true);
                    if (File.Exists(failed)) File.Delete(failed);
                }
                catch (Exception rollbackError) when (rollbackError is IOException
                                                      or UnauthorizedAccessException
                                                      or NotSupportedException)
                {
                    // Preserve the backup if rollback cannot be completed.
                }
            }
            throw;
        }
        finally
        {
            if (File.Exists(temporary)) File.Delete(temporary);
        }
    }

    private static async Task WaitForExactParentExitAsync(PortableUpdateHelperOptions options)
    {
        Process parent;
        try
        {
            parent = Process.GetProcessById(options.ParentProcessId);
        }
        catch (ArgumentException)
        {
            return;
        }
        using (parent)
        {
            try
            {
                var startTime = parent.StartTime.ToUniversalTime().Ticks;
                var executable = parent.MainModule?.FileName;
                if (startTime != options.ParentStartTimeUtcTicks
                    || string.IsNullOrWhiteSpace(executable)
                    || !string.Equals(
                        Path.GetFullPath(executable),
                        Path.GetFullPath(options.ParentExecutablePath),
                        StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidDataException(
                        "The superseded Lattice process identity changed before portable replacement.");
                }
                using var timeout = new CancellationTokenSource(ParentExitTimeout);
                await parent.WaitForExitAsync(timeout.Token);
            }
            catch (InvalidOperationException)
            {
                return;
            }
            catch (OperationCanceledException error)
            {
                throw new TaskCanceledException(
                    "The superseded Lattice process did not close within 30 seconds. The portable launcher was not replaced.",
                    error);
            }
        }
    }
}
