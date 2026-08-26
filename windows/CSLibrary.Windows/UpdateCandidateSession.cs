using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text.Json;

namespace CSLibrary.Windows;

/// <summary>
/// Health gate used only by an isolated, newly staged version. The existing
/// Start-menu shortcut remains pointed at the previous version until both the
/// candidate's local server and complete shared WebView interface have succeeded.
/// </summary>
internal sealed class UpdateCandidateSession
{
    private static readonly HttpClient HealthClient = new()
    {
        Timeout = TimeSpan.FromSeconds(8),
    };

    private readonly UpdateInstallation _installation;
    private readonly PendingUpdateActivation _pending;
    private readonly string _pendingPath;
    private Uri? _healthyServerOrigin;
    private bool _webViewHealthy;
    private bool _promoted;

    private UpdateCandidateSession(
        UpdateInstallation installation,
        PendingUpdateActivation pending,
        string pendingPath)
    {
        _installation = installation;
        _pending = pending;
        _pendingPath = pendingPath;
    }

    internal string PreviousVersion => _pending.PreviousVersion;
    internal string CandidateVersion => _pending.CandidateVersion;
    internal bool IsReadyToPromote => _healthyServerOrigin is not null && _webViewHealthy;

    internal static UpdateCandidateSession? TryOpenFromCurrentProcess(
        IReadOnlyList<string>? arguments = null)
    {
        arguments ??= Environment.GetCommandLineArgs().Skip(1).ToArray();
        var activationId = ReadOption(arguments, "--update-candidate");
        var token = ReadOption(arguments, "--update-token");
        if (activationId is null && token is null) return null;
        if (activationId is null || token is null)
            throw new InvalidDataException("The update-candidate launch proof is incomplete.");
        if (!Guid.TryParseExact(activationId, "N", out _)
            || !string.Equals(activationId, activationId.ToLowerInvariant(), StringComparison.Ordinal)
            || !UpdateSecurity.IsLowerHexSha256(token))
            throw new InvalidDataException("The update-candidate launch proof is malformed.");

        var installation = UpdateInstallation.TryDetect()
            ?? throw new InvalidDataException("An update candidate must run from the versioned Lattice installation.");
        var pendingPath = Path.Combine(installation.UpdatesRoot, "pending", $"{activationId}.json");
        if ((File.GetAttributes(pendingPath) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("The update-candidate record cannot be a reparse point.");
        var pending = UpdateService.ReadBoundedJson<PendingUpdateActivation>(pendingPath, 16 * 1024);
        ValidatePending(installation, pending, activationId, token);
        return new UpdateCandidateSession(installation, pending, pendingPath);
    }

    internal async Task ReportServerHealthyAsync(
        Uri serverBaseUri,
        string expectedLibraryRoot,
        Process ownedServerProcess,
        CancellationToken cancellationToken = default)
    {
        var expectedServerExecutable = Path.Combine(
            _installation.VersionDirectory,
            "Server",
            "LatticeServer.exe");
        if (ownedServerProcess.HasExited
            || !string.Equals(
                Path.GetFullPath(ownedServerProcess.StartInfo.FileName),
                Path.GetFullPath(expectedServerExecutable),
                StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("The update candidate does not own the expected bundled local server.");
        expectedLibraryRoot = Path.GetFullPath(expectedLibraryRoot);
        var origin = ValidateLoopbackOrigin(serverBaseUri);
        var healthUri = new Uri(origin, "api/health");
        using var response = await HealthClient.GetAsync(
            healthUri,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken);
        if (response.StatusCode != HttpStatusCode.OK)
            throw new InvalidDataException("The update candidate's local server did not return HTTP 200.");
        if (response.Content.Headers.ContentLength is > 64 * 1024)
            throw new InvalidDataException("The update candidate's health response is too large.");
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using var bounded = new MemoryStream();
        var buffer = new byte[8192];
        while (true)
        {
            var count = await stream.ReadAsync(buffer, cancellationToken);
            if (count == 0) break;
            if (bounded.Length + count > 64 * 1024)
                throw new InvalidDataException("The update candidate's health response is too large.");
            bounded.Write(buffer, 0, count);
        }
        if (bounded.Length == 0)
            throw new InvalidDataException("The update candidate's health response is empty.");
        try
        {
            using var document = JsonDocument.Parse(bounded.ToArray(), new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 8,
            });
            UpdateSecurity.RejectDuplicateProperties(document.RootElement);
            if (document.RootElement.ValueKind != JsonValueKind.Object
                || !document.RootElement.TryGetProperty("app", out var app)
                || app.ValueKind != JsonValueKind.String
                || !string.Equals(app.GetString(), "cs-library", StringComparison.Ordinal)
                || !document.RootElement.TryGetProperty("protocolVersion", out var protocol)
                || protocol.ValueKind != JsonValueKind.Number
                || !protocol.TryGetInt32(out var protocolVersion)
                || protocolVersion != 4
                || !document.RootElement.TryGetProperty("status", out var status)
                || status.ValueKind != JsonValueKind.String
                || !string.Equals(status.GetString(), "ok", StringComparison.Ordinal)
                || !document.RootElement.TryGetProperty("root", out var root)
                || root.ValueKind != JsonValueKind.String
                || string.IsNullOrWhiteSpace(root.GetString())
                || !string.Equals(
                    Path.GetFullPath(root.GetString()!),
                    expectedLibraryRoot,
                    StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("The update candidate's local server is not healthy.");
        }
        catch (JsonException error)
        {
            throw new InvalidDataException("The update candidate returned malformed health data.", error);
        }

        if (ownedServerProcess.HasExited)
            throw new InvalidDataException("The update candidate's owned local server exited during its health proof.");
        _healthyServerOrigin = origin;
        PromoteIfReady();
    }

    internal void ReportWebViewNavigationHealthy(Uri navigatedUri, bool navigationSucceeded)
    {
        if (!navigationSucceeded)
            throw new InvalidDataException("The update candidate's WebView navigation failed.");
        if (_healthyServerOrigin is null)
            throw new InvalidOperationException("The local server must pass its health probe before WebView promotion.");
        var navigationOrigin = ValidateLoopbackOrigin(navigatedUri);
        if (!string.Equals(
                navigationOrigin.AbsoluteUri,
                _healthyServerOrigin.AbsoluteUri,
                StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("The update candidate's WebView did not navigate to its own healthy server.");
        _webViewHealthy = true;
        PromoteIfReady();
    }

    internal void PromoteIfReady()
    {
        if (_promoted || !IsReadyToPromote) return;
        _installation.AssertSafeRoots();
        ValidateCurrentCandidateExecutable(_installation, _pending);
        // The active-version record is the authority used by stale binaries.
        // Publish it first: if the process stops before the shortcut swap, the
        // old shortcut launches an old binary that immediately redirects here.
        var previousVersion = ActiveVersionAuthority.Promote(
            _installation,
            StableSemanticVersion.Parse(_pending.CandidateVersion, "candidate version"),
            StableSemanticVersion.Parse(_pending.PreviousVersion, "previous version"),
            _pending.ActivationId);
        _promoted = true;
        try
        {
            UpdateShortcutMaintenance.EnsureActiveShortcut(
                _installation,
                previousVersion.ToString(),
                _pending.ActivationId);
        }
        catch (Exception error)
        {
            UpdateMaintenance.RecordIssue(_installation, "shortcut", error);
        }
        try
        {
            ArchiveActivationRecord();
        }
        catch (Exception error)
        {
            UpdateMaintenance.RecordIssue(_installation, "activation-archive", error);
        }
        try
        {
            UpdateVersionRetention.PruneToActiveAndPrevious(
                _installation,
                _installation.Version,
                previousVersion);
        }
        catch (Exception error)
        {
            UpdateMaintenance.RecordIssue(_installation, "version-retention", error);
        }
        try
        {
            LaunchPortableLauncherReplacement();
        }
        catch (Exception error) when (error is IOException
            or UnauthorizedAccessException
            or InvalidOperationException
            or NotSupportedException
            or System.ComponentModel.Win32Exception
            or System.Security.Cryptography.CryptographicException)
        {
            UpdateMaintenance.RecordIssue(_installation, "portable-launcher", error);
        }
        try
        {
            RequestSupersededLauncherShutdown();
        }
        catch (Exception error) when (error is InvalidOperationException
            or System.ComponentModel.Win32Exception
            or NotSupportedException)
        {
            // Promotion is already durable. Failure to dismiss an older window
            // is a recoverable maintenance issue, never a reason to roll back a
            // healthy candidate.
            UpdateMaintenance.RecordIssue(_installation, "superseded-window", error);
        }
    }

    private void LaunchPortableLauncherReplacement()
    {
        if (!_promoted || _pending.LauncherProcessId is not int launcherProcessId)
            return;

        var previousVersion = StableSemanticVersion.Parse(
            _pending.PreviousVersion,
            "previous version");
        var previousExecutable = Path.GetFullPath(Path.Combine(
            _installation.VersionsRoot,
            previousVersion.ToString(),
            "Lattice.exe"));
        var mirror = _pending.LauncherMirrorPath;
        var mirrorSha256 = _pending.LauncherMirrorSha256;
        if (string.IsNullOrWhiteSpace(mirror) || string.IsNullOrWhiteSpace(mirrorSha256))
        {
            mirror = PortableLauncherMaintenance.FindLegacyDesktopMirror(
                _installation,
                previousExecutable);
            if (mirror is null) return;
            mirrorSha256 = PortableLauncherMaintenance.ComputeSha256(mirror);
        }

        var parentStartTimeUtcTicks = _pending.LauncherProcessStartTimeUtcTicks;
        try
        {
            using var launcher = Process.GetProcessById(launcherProcessId);
            if (!launcher.HasExited)
            {
                var executable = launcher.MainModule?.FileName;
                if (string.IsNullOrWhiteSpace(executable)
                    || !string.Equals(
                        Path.GetFullPath(executable),
                        previousExecutable,
                        StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException(
                        "The superseded Lattice launcher path changed before replacement.");
                var actualStartTime = launcher.StartTime.ToUniversalTime().Ticks;
                if (parentStartTimeUtcTicks is long expectedStartTime
                    && expectedStartTime != actualStartTime)
                    throw new InvalidDataException(
                        "The superseded Lattice launcher identity changed before replacement.");
                parentStartTimeUtcTicks = actualStartTime;
            }
        }
        catch (ArgumentException)
        {
            // The old launcher already exited. The helper can replace its mirror immediately.
        }
        if (parentStartTimeUtcTicks is not > 0)
            parentStartTimeUtcTicks = 1;

        var options = new PortableUpdateHelperOptions(
            launcherProcessId,
            parentStartTimeUtcTicks.Value,
            previousExecutable,
            Path.GetFullPath(mirror),
            mirrorSha256,
            _pending.CandidateVersion);
        var executablePath = Environment.ProcessPath
            ?? throw new InvalidOperationException("The portable replacement helper executable is unavailable.");
        Directory.CreateDirectory(PortableLauncherMaintenance.LocalSettingsRoot);
        var start = new ProcessStartInfo(executablePath)
        {
            UseShellExecute = false,
            WorkingDirectory = PortableLauncherMaintenance.LocalSettingsRoot,
        };
        options.AddArguments(start);
        using var helper = Process.Start(start)
            ?? throw new InvalidOperationException("Windows did not start the portable replacement helper.");
    }

    private void RequestSupersededLauncherShutdown()
    {
        if (!_promoted)
            throw new InvalidOperationException(
                "The previous Lattice window can close only after candidate promotion.");

        var previousVersion = StableSemanticVersion.Parse(
            _pending.PreviousVersion,
            "previous version");
        var expectedExecutable = Path.GetFullPath(Path.Combine(
            _installation.VersionsRoot,
            previousVersion.ToString(),
            "Lattice.exe"));

        if (_pending.LauncherProcessId is int launcherProcessId)
        {
            // Current launchers bind the handoff to one process. Validate the
            // executable path as well so PID reuse can never close an unrelated
            // application.
            if (launcherProcessId == Environment.ProcessId) return;
            try
            {
                using var launcher = Process.GetProcessById(launcherProcessId);
                RequestShutdownIfExpected(launcher, expectedExecutable);
            }
            catch (ArgumentException)
            {
                // The launcher already exited.
            }
            return;
        }

        // Lattice 2.0.1 activation records predate launcherProcessId. The first
        // fixed candidate therefore closes only same-user Lattice processes
        // whose executable is the exact, canonical previous-version binary.
        foreach (var process in Process.GetProcessesByName("Lattice"))
        {
            using (process)
            {
                if (process.Id == Environment.ProcessId) continue;
                RequestShutdownIfExpected(process, expectedExecutable);
            }
        }
    }

    private static void RequestShutdownIfExpected(Process process, string expectedExecutable)
    {
        if (process.HasExited) return;
        var executable = process.MainModule?.FileName;
        if (string.IsNullOrWhiteSpace(executable)
            || !string.Equals(
                Path.GetFullPath(executable),
                expectedExecutable,
                StringComparison.OrdinalIgnoreCase)) return;
        _ = process.CloseMainWindow();
    }

    private void ArchiveActivationRecord()
    {
        var promotedRoot = Path.Combine(_installation.UpdatesRoot, "promoted");
        Directory.CreateDirectory(promotedRoot);
        var promotedPath = Path.Combine(promotedRoot, $"{_pending.ActivationId}.json");
        if (File.Exists(promotedPath))
            throw new InvalidDataException("The update activation was already archived.");
        File.Move(_pendingPath, promotedPath);
    }

    private static void ValidatePending(
        UpdateInstallation installation,
        PendingUpdateActivation pending,
        string activationId,
        string token)
    {
        var now = DateTimeOffset.UtcNow;
        if (pending.SchemaVersion != 1
            || !string.Equals(pending.ActivationId, activationId, StringComparison.Ordinal)
            || !UpdateSecurity.IsLowerHexSha256(pending.TokenSha256)
            || pending.LauncherProcessId is <= 0
            || !DateTimeOffset.TryParse(pending.CreatedAt, out var createdAt)
            || createdAt.Offset != TimeSpan.Zero
            || createdAt > now.AddMinutes(1)
            || createdAt < now.AddMinutes(-15))
            throw new InvalidDataException("The update activation record is invalid or expired.");

        var suppliedTokenBytes = Convert.FromHexString(token);
        var suppliedHash = SHA256.HashData(suppliedTokenBytes);
        var expectedHash = Convert.FromHexString(pending.TokenSha256);
        if (!CryptographicOperations.FixedTimeEquals(suppliedHash, expectedHash))
            throw new CryptographicException("The update activation token is invalid.");

        var previous = StableSemanticVersion.Parse(pending.PreviousVersion, "previous version");
        var candidate = StableSemanticVersion.Parse(pending.CandidateVersion, "candidate version");
        if (candidate != installation.Version || candidate.CompareTo(previous) <= 0)
            throw new InvalidDataException("The update activation versions are inconsistent.");
        var expectedDirectory = Path.Combine(installation.VersionsRoot, candidate.ToString());
        if (!string.Equals(
                Path.TrimEndingDirectorySeparator(Path.GetFullPath(pending.CandidateDirectory)),
                Path.TrimEndingDirectorySeparator(Path.GetFullPath(expectedDirectory)),
                StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("The update activation points outside the versioned installation.");
        var expectedLauncher = Path.GetFullPath(Path.Combine(
            installation.VersionsRoot,
            previous.ToString(),
            "Lattice.exe"));
        var hasLauncherStartTime = pending.LauncherProcessStartTimeUtcTicks is not null;
        var hasLauncherPath = !string.IsNullOrWhiteSpace(pending.LauncherExecutablePath);
        if (hasLauncherStartTime != hasLauncherPath
            || pending.LauncherProcessStartTimeUtcTicks is <= 0
            || (hasLauncherPath
                && !string.Equals(
                    Path.GetFullPath(pending.LauncherExecutablePath!),
                    expectedLauncher,
                    StringComparison.OrdinalIgnoreCase)))
            throw new InvalidDataException("The update launcher identity is invalid.");
        var hasMirrorPath = !string.IsNullOrWhiteSpace(pending.LauncherMirrorPath);
        var hasMirrorDigest = !string.IsNullOrWhiteSpace(pending.LauncherMirrorSha256);
        if (hasMirrorPath != hasMirrorDigest
            || (hasMirrorPath
                && (!string.Equals(
                        Path.GetExtension(Path.GetFullPath(pending.LauncherMirrorPath!)),
                        ".exe",
                        StringComparison.OrdinalIgnoreCase)
                    || !PortableLauncherMaintenance.IsOutsideInstallRoot(
                        pending.LauncherMirrorPath!,
                        installation.InstallRoot)
                    || !UpdateSecurity.IsLowerHexSha256(pending.LauncherMirrorSha256!))))
            throw new InvalidDataException("The portable launcher replacement record is invalid.");
        UpdateSecurity.ValidatePackageDirectory(installation.VersionDirectory, candidate);
        ValidateCurrentCandidateExecutable(installation, pending);
    }

    private static void ValidateCurrentCandidateExecutable(
        UpdateInstallation installation,
        PendingUpdateActivation pending)
    {
        var processPath = Environment.ProcessPath;
        var expectedExecutable = Path.Combine(installation.VersionDirectory, "Lattice.exe");
        if (string.IsNullOrWhiteSpace(processPath)
            || !string.Equals(
                Path.GetFullPath(processPath),
                Path.GetFullPath(expectedExecutable),
                StringComparison.OrdinalIgnoreCase)
            || !string.Equals(
                Path.GetFullPath(pending.CandidateDirectory),
                Path.GetFullPath(installation.VersionDirectory),
                StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Only the running versioned candidate may promote itself.");
    }

    private static Uri ValidateLoopbackOrigin(Uri uri)
    {
        if (!uri.IsAbsoluteUri
            || uri.Scheme != Uri.UriSchemeHttp
            || !uri.IsLoopback
            || uri.IsDefaultPort
            || !string.IsNullOrEmpty(uri.UserInfo))
            throw new InvalidDataException("The update candidate health origin must be an explicit loopback HTTP port.");
        return new UriBuilder(Uri.UriSchemeHttp, uri.Host, uri.Port, "/").Uri;
    }

    private static string? ReadOption(IReadOnlyList<string> arguments, string name)
    {
        string? value = null;
        for (var index = 0; index < arguments.Count; index++)
        {
            if (!string.Equals(arguments[index], name, StringComparison.Ordinal)) continue;
            if (value is not null || index + 1 >= arguments.Count || arguments[index + 1].StartsWith("--"))
                throw new InvalidDataException($"{name} must occur once with a value.");
            value = arguments[++index];
        }
        return value;
    }

}

/// <summary>
/// Serializes active-version commits across candidate processes and enforces a
/// monotonic version authority at the instant of promotion.
/// </summary>
internal static class ActiveVersionAuthority
{
    private static readonly TimeSpan LockTimeout = TimeSpan.FromSeconds(5);

    internal static StableSemanticVersion Promote(
        UpdateInstallation installation,
        StableSemanticVersion candidateVersion,
        StableSemanticVersion launchedFromVersion,
        string operationId,
        DateTimeOffset? clock = null)
    {
        if (candidateVersion != installation.Version
            || candidateVersion.CompareTo(launchedFromVersion) <= 0)
            throw new InvalidDataException("The promoted candidate versions are inconsistent.");
        if (!Guid.TryParseExact(operationId, "N", out _)
            || !string.Equals(operationId, operationId.ToLowerInvariant(), StringComparison.Ordinal))
            throw new InvalidDataException("The promotion operation identifier is invalid.");

        installation.AssertSafeRoots();
        var activePath = Path.Combine(installation.InstallRoot, "active-version.json");
        var lockPath = Path.Combine(installation.InstallRoot, ".active-version.lock");
        using var authorityLock = AcquireAuthorityLock(lockPath);

        StableSemanticVersion? existingVersion = null;
        StableSemanticVersion? existingPreviousVersion = null;
        if (File.Exists(activePath))
        {
            if ((File.GetAttributes(activePath) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("The active-version record cannot be a reparse point.");
            var active = UpdateService.ReadBoundedJson<ActiveVersionRecord>(activePath, 16 * 1024);
            if (active.SchemaVersion != 1
                || !DateTimeOffset.TryParse(active.PromotedAt, out var promotedAt)
                || promotedAt.Offset != TimeSpan.Zero)
                throw new InvalidDataException("The active-version record is invalid.");

            existingVersion = StableSemanticVersion.Parse(active.Version, "active version");
            if (active.PreviousVersion is not null)
            {
                existingPreviousVersion = StableSemanticVersion.Parse(
                    active.PreviousVersion,
                    "active previous version");
                if (existingPreviousVersion.Value.CompareTo(existingVersion.Value) >= 0)
                    throw new InvalidDataException("The active-version rollback record is invalid.");
            }

            var order = candidateVersion.CompareTo(existingVersion.Value);
            if (order < 0)
                throw new UpdateVersionRejectedException(
                    UpdateVersionRejection.Downgrade,
                    $"Refusing to replace active Lattice {existingVersion} with older candidate {candidateVersion}.");
            if (order == 0)
                return existingPreviousVersion ?? launchedFromVersion;
        }

        var previousVersion = launchedFromVersion;
        if (existingVersion is StableSemanticVersion activeVersion
            && activeVersion.CompareTo(previousVersion) > 0)
            previousVersion = activeVersion;

        WriteActiveVersion(
            installation,
            candidateVersion,
            previousVersion,
            operationId,
            clock ?? DateTimeOffset.UtcNow,
            activePath);
        return previousVersion;
    }

    private static FileStream AcquireAuthorityLock(string path)
    {
        var stopwatch = Stopwatch.StartNew();
        IOException? lastError = null;
        while (stopwatch.Elapsed < LockTimeout)
        {
            try
            {
                if (File.Exists(path)
                    && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("The active-version lock cannot be a reparse point.");
                return new FileStream(
                    path,
                    FileMode.OpenOrCreate,
                    FileAccess.ReadWrite,
                    FileShare.None,
                    bufferSize: 1,
                    FileOptions.WriteThrough);
            }
            catch (IOException error)
            {
                lastError = error;
                Thread.Sleep(25);
            }
        }
        throw new IOException(
            "Timed out waiting to commit the active Lattice version.",
            lastError);
    }

    private static void WriteActiveVersion(
        UpdateInstallation installation,
        StableSemanticVersion candidateVersion,
        StableSemanticVersion previousVersion,
        string operationId,
        DateTimeOffset promotedAt,
        string activePath)
    {
        var temporaryPath = Path.Combine(
            installation.InstallRoot,
            $".active-version-{operationId}.json");
        var backupRoot = Path.Combine(installation.InstallRoot, "rollback");
        Directory.CreateDirectory(backupRoot);
        var backupPath = Path.Combine(
            backupRoot,
            $"active-version-{previousVersion}-{operationId}.json");
        UpdateService.WriteNewJson(temporaryPath, new ActiveVersionRecord
        {
            SchemaVersion = 1,
            Version = candidateVersion.ToString(),
            PreviousVersion = previousVersion.ToString(),
            PromotedAt = promotedAt.ToString("O"),
        });
        try
        {
            if (File.Exists(activePath))
                File.Replace(temporaryPath, activePath, backupPath, ignoreMetadataErrors: true);
            else
                File.Move(temporaryPath, activePath);
        }
        finally
        {
            if (File.Exists(temporaryPath)) File.Delete(temporaryPath);
        }
    }
}
