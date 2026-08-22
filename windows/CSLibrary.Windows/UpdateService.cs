using System.Diagnostics;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text.Json;

namespace CSLibrary.Windows;

internal sealed record UpdateInstallation(
    string InstallRoot,
    string VersionsRoot,
    string VersionDirectory,
    StableSemanticVersion Version)
{
    private static readonly Lazy<UpdateInstallation?> CurrentProcessInstallation = new(
        () => Detect(AppContext.BaseDirectory, null),
        LazyThreadSafetyMode.ExecutionAndPublication);

    internal string UpdatesRoot => Path.Combine(InstallRoot, ".updates");

    internal void AssertSafeRoots()
    {
        foreach (var path in new[] { InstallRoot, VersionsRoot })
        {
            if (Directory.Exists(path)
                && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("The versioned Lattice installation cannot use reparse-point roots.");
        }
    }

    internal static UpdateInstallation? TryDetect(
        string? applicationDirectory = null,
        string? localApplicationData = null)
    {
        if (applicationDirectory is null && localApplicationData is null)
            return CurrentProcessInstallation.Value;
        return Detect(applicationDirectory ?? AppContext.BaseDirectory, localApplicationData);
    }

    private static UpdateInstallation? Detect(
        string applicationDirectory,
        string? localApplicationData)
    {
        applicationDirectory = Path.TrimEndingDirectorySeparator(Path.GetFullPath(
            applicationDirectory));
        localApplicationData ??= Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (string.IsNullOrWhiteSpace(localApplicationData)) return null;

        var installRoot = Path.GetFullPath(Path.Combine(localApplicationData, "Programs", "Lattice"));
        var versionsRoot = Path.Combine(installRoot, "versions");
        try
        {
            if ((Directory.Exists(installRoot)
                    && (File.GetAttributes(installRoot) & FileAttributes.ReparsePoint) != 0)
                || (Directory.Exists(versionsRoot)
                    && (File.GetAttributes(versionsRoot) & FileAttributes.ReparsePoint) != 0)) return null;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            return null;
        }
        var parent = Directory.GetParent(applicationDirectory);
        if (parent is null
            || !string.Equals(
                Path.TrimEndingDirectorySeparator(parent.FullName),
                Path.TrimEndingDirectorySeparator(versionsRoot),
                StringComparison.OrdinalIgnoreCase)) return null;

        StableSemanticVersion version;
        try
        {
            version = StableSemanticVersion.Parse(Path.GetFileName(applicationDirectory), "installed version");
            if ((File.GetAttributes(applicationDirectory) & FileAttributes.ReparsePoint) != 0) return null;
            UpdateSecurity.ValidatePackageDirectory(applicationDirectory, version);
        }
        catch (Exception error) when (error is IOException
            or UnauthorizedAccessException
            or InvalidDataException
            or CryptographicException)
        {
            return null;
        }
        return new UpdateInstallation(installRoot, versionsRoot, applicationDirectory, version);
    }
}

internal sealed class UpdateService
{
    internal static readonly Uri ManifestUrl = new(
        "https://github.com/dreichner2/cs-library/releases/latest/download/update-manifest.json");
    internal static readonly Uri SignatureUrl = new(
        "https://github.com/dreichner2/cs-library/releases/latest/download/update-manifest.json.sig");

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = System.Text.Json.Serialization.JsonUnmappedMemberHandling.Disallow,
        MaxDepth = 16,
    };
    private static readonly HttpClient Client = CreateClient();
    private readonly UpdateInstallation? _installation;

    internal UpdateService() : this(UpdateInstallation.TryDetect())
    {
    }

    internal UpdateService(UpdateInstallation? installation)
    {
        _installation = installation;
    }

    internal bool IsAutomaticUpdateSupported => _installation is not null;
    internal string? InstalledVersion => _installation?.Version.ToString();

    internal async Task<DesktopUpdateCheck> CheckAsync(CancellationToken cancellationToken = default)
    {
        if (_installation is null)
        {
            return new DesktopUpdateCheck(
                DesktopUpdateState.NotInstalled,
                null,
                null,
                Message: "Automatic updates are available only after Lattice is installed for this Windows account.");
        }

        var manifestTask = DownloadBoundedBytesAsync(
            ManifestUrl,
            UpdateSecurity.MaximumManifestSize,
            cancellationToken);
        var signatureTask = DownloadBoundedBytesAsync(SignatureUrl, 4096, cancellationToken);
        await Task.WhenAll(manifestTask, signatureTask);
        var manifestBytes = await manifestTask;
        var signatureBytes = await signatureTask;

        ValidatedDesktopRelease release;
        try
        {
            release = UpdateSecurity.VerifyAndValidateManifest(
                manifestBytes,
                signatureBytes,
                _installation.Version);
        }
        catch (UpdateVersionRejectedException error)
            when (error.Reason == UpdateVersionRejection.SameVersion)
        {
            return new DesktopUpdateCheck(
                DesktopUpdateState.Current,
                _installation.Version.ToString(),
                _installation.Version.ToString(),
                Message: error.Message);
        }

        return new DesktopUpdateCheck(
            DesktopUpdateState.Available,
            _installation.Version.ToString(),
            release.Version.ToString(),
            release.Asset);
    }

    internal async Task<StagedDesktopUpdate> DownloadAndStageAsync(
        DesktopUpdateCheck update,
        IProgress<int>? progress = null,
        CancellationToken cancellationToken = default)
    {
        if (_installation is null)
            throw new InvalidOperationException("Portable and development copies cannot install automatic updates.");
        _installation.AssertSafeRoots();
        if (update.State != DesktopUpdateState.Available
            || update.Asset is null
            || string.IsNullOrWhiteSpace(update.LatestVersion))
            throw new InvalidOperationException("No verified Windows update is available to stage.");

        var version = StableSemanticVersion.Parse(update.LatestVersion, "release version");
        if (version.CompareTo(_installation.Version) <= 0)
            throw new InvalidDataException("The staged release must be newer than the installed version.");
        UpdateSecurity.ValidateAssetForVersion(version, update.Asset);

        Directory.CreateDirectory(_installation.UpdatesRoot);
        Directory.CreateDirectory(_installation.VersionsRoot);
        var finalDirectory = Path.Combine(_installation.VersionsRoot, version.ToString());
        if (Directory.Exists(finalDirectory))
            RemoveRecognizedStaleCandidateForRedownload(version);

        var operationId = Guid.NewGuid().ToString("N");
        var archivePath = Path.Combine(_installation.UpdatesRoot, $"download-{version}-{operationId}.zip.partial");
        var stagingDirectory = Path.Combine(_installation.VersionsRoot, $".staging-{version}-{operationId}");
        var finalCreated = false;
        try
        {
            using var response = await Client.GetAsync(
                new Uri(update.Asset.Url),
                HttpCompletionOption.ResponseHeadersRead,
                cancellationToken);
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength is long publishedLength
                && publishedLength != update.Asset.Size)
                throw new InvalidDataException("The update download size differs from its signed manifest.");

            await using (var source = await response.Content.ReadAsStreamAsync(cancellationToken))
            await using (var destination = new FileStream(
                archivePath,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None,
                1024 * 1024,
                FileOptions.Asynchronous | FileOptions.SequentialScan))
            using (var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256))
            {
                var buffer = new byte[1024 * 1024];
                long received = 0;
                while (true)
                {
                    var count = await source.ReadAsync(buffer, cancellationToken);
                    if (count == 0) break;
                    received += count;
                    if (received > update.Asset.Size || received > UpdateSecurity.MaximumArchiveSize)
                        throw new InvalidDataException("The update download exceeds its signed size.");
                    await destination.WriteAsync(buffer.AsMemory(0, count), cancellationToken);
                    digest.AppendData(buffer, 0, count);
                    progress?.Report((int)Math.Clamp(received * 100 / update.Asset.Size, 0, 100));
                }
                if (received != update.Asset.Size)
                    throw new InvalidDataException("The update download is incomplete.");
                var expected = Convert.FromHexString(update.Asset.Sha256);
                if (!CryptographicOperations.FixedTimeEquals(digest.GetHashAndReset(), expected))
                    throw new CryptographicException("The update ZIP failed its signed SHA-256 check.");
            }

            UpdateSecurity.ExtractArchiveSafely(archivePath, stagingDirectory);
            UpdateSecurity.ValidatePackageDirectory(stagingDirectory, version);
            Directory.Move(stagingDirectory, finalDirectory);
            finalCreated = true;
            UpdateSecurity.ValidatePackageDirectory(finalDirectory, version);
            return new StagedDesktopUpdate(version.ToString(), finalDirectory);
        }
        catch
        {
            if (Directory.Exists(stagingDirectory)) Directory.Delete(stagingDirectory, recursive: true);
            if (finalCreated && Directory.Exists(finalDirectory)) Directory.Delete(finalDirectory, recursive: true);
            throw;
        }
        finally
        {
            if (File.Exists(archivePath)) File.Delete(archivePath);
        }
    }

    internal Process LaunchCandidate(StagedDesktopUpdate staged, string? libraryRoot = null)
    {
        if (_installation is null)
            throw new InvalidOperationException("Portable and development copies cannot launch automatic updates.");
        _installation.AssertSafeRoots();

        var candidateVersion = StableSemanticVersion.Parse(staged.Version, "candidate version");
        if (candidateVersion.CompareTo(_installation.Version) <= 0)
            throw new InvalidDataException("The update candidate is not newer than this installation.");
        var expectedDirectory = Path.Combine(_installation.VersionsRoot, candidateVersion.ToString());
        if (!string.Equals(
                Path.TrimEndingDirectorySeparator(Path.GetFullPath(staged.VersionDirectory)),
                Path.TrimEndingDirectorySeparator(Path.GetFullPath(expectedDirectory)),
                StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("The update candidate is outside the installed version layout.");
        UpdateSecurity.ValidatePackageDirectory(expectedDirectory, candidateVersion);

        RemoveExpiredPendingActivations(candidateVersion);
        if (HasLivePendingActivation(candidateVersion))
            throw new InvalidOperationException(
                $"Lattice {candidateVersion} is already awaiting its startup health check. Try again after it finishes.");

        var activationId = Guid.NewGuid().ToString("N");
        var tokenBytes = RandomNumberGenerator.GetBytes(32);
        var token = Convert.ToHexString(tokenBytes).ToLowerInvariant();
        var pending = new PendingUpdateActivation
        {
            SchemaVersion = 1,
            ActivationId = activationId,
            TokenSha256 = Convert.ToHexString(SHA256.HashData(tokenBytes)).ToLowerInvariant(),
            CreatedAt = DateTimeOffset.UtcNow.ToString("O"),
            PreviousVersion = _installation.Version.ToString(),
            CandidateVersion = candidateVersion.ToString(),
            CandidateDirectory = expectedDirectory,
        };
        var pendingRoot = Path.Combine(_installation.UpdatesRoot, "pending");
        Directory.CreateDirectory(pendingRoot);
        var pendingPath = Path.Combine(pendingRoot, $"{activationId}.json");
        WriteNewJson(pendingPath, pending);

        var executable = Path.Combine(expectedDirectory, "Lattice.exe");
        var start = new ProcessStartInfo(executable)
        {
            UseShellExecute = true,
            WorkingDirectory = expectedDirectory,
        };
        start.ArgumentList.Add("--update-candidate");
        start.ArgumentList.Add(activationId);
        start.ArgumentList.Add("--update-token");
        start.ArgumentList.Add(token);
        if (!string.IsNullOrWhiteSpace(libraryRoot))
        {
            start.ArgumentList.Add("--library-root");
            start.ArgumentList.Add(Path.GetFullPath(libraryRoot));
        }
        try
        {
            return Process.Start(start)
                ?? throw new InvalidOperationException("The verified update candidate did not start.");
        }
        catch
        {
            File.Delete(pendingPath);
            throw;
        }
    }

    internal static T ReadBoundedJson<T>(string path, long maximumBytes)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length <= 0 || stream.Length > maximumBytes)
            throw new InvalidDataException($"{Path.GetFileName(path)} has an unsafe size.");
        using var document = JsonDocument.Parse(stream, new JsonDocumentOptions
        {
            AllowTrailingCommas = false,
            CommentHandling = JsonCommentHandling.Disallow,
            MaxDepth = 16,
        });
        UpdateSecurity.RejectDuplicateProperties(document.RootElement);
        return document.RootElement.Deserialize<T>(JsonOptions)
            ?? throw new InvalidDataException($"{Path.GetFileName(path)} is empty.");
    }

    internal static void WriteNewJson<T>(string path, T value)
    {
        var bytes = JsonSerializer.SerializeToUtf8Bytes(value, JsonOptions);
        using var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        stream.Write(bytes);
        stream.Flush(flushToDisk: true);
    }

    internal int RemoveExpiredPendingActivations(
        StableSemanticVersion candidateVersion,
        DateTimeOffset? clock = null)
    {
        if (_installation is null) return 0;
        var pendingRoot = Path.Combine(_installation.UpdatesRoot, "pending");
        if (!Directory.Exists(pendingRoot)) return 0;
        var now = clock ?? DateTimeOffset.UtcNow;
        var removed = 0;
        foreach (var path in Directory.EnumerateFiles(pendingRoot, "*.json", SearchOption.TopDirectoryOnly))
        {
            try
            {
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) continue;
                var id = Path.GetFileNameWithoutExtension(path);
                if (!Guid.TryParseExact(id, "N", out _)
                    || !string.Equals(id, id.ToLowerInvariant(), StringComparison.Ordinal)) continue;
                var pending = ReadBoundedJson<PendingUpdateActivation>(path, 16 * 1024);
                if (pending.SchemaVersion != 1
                    || !string.Equals(pending.ActivationId, id, StringComparison.Ordinal)
                    || !UpdateSecurity.IsLowerHexSha256(pending.TokenSha256)
                    || !DateTimeOffset.TryParse(pending.CreatedAt, out var createdAt)
                    || createdAt.Offset != TimeSpan.Zero
                    || createdAt >= now.AddMinutes(-15)) continue;
                var recordedVersion = StableSemanticVersion.Parse(
                    pending.CandidateVersion,
                    "pending candidate version");
                var expectedDirectory = Path.Combine(_installation.VersionsRoot, candidateVersion.ToString());
                if (recordedVersion != candidateVersion
                    || !string.Equals(
                        Path.GetFullPath(pending.CandidateDirectory),
                        Path.GetFullPath(expectedDirectory),
                        StringComparison.OrdinalIgnoreCase)) continue;
                File.Delete(path);
                removed += 1;
            }
            catch (Exception error) when (error is IOException
                or UnauthorizedAccessException
                or InvalidDataException
                or JsonException)
            {
                // Unknown files are never updater-owned deletion targets.
            }
        }
        return removed;
    }

    internal void RemoveRecognizedStaleCandidateForRedownload(StableSemanticVersion candidateVersion)
    {
        if (_installation is null)
            throw new InvalidOperationException("There is no versioned Lattice installation.");
        _installation.AssertSafeRoots();
        var candidateDirectory = Path.Combine(_installation.VersionsRoot, candidateVersion.ToString());
        if (!Directory.Exists(candidateDirectory)) return;
        RemoveExpiredPendingActivations(candidateVersion);
        if (HasLivePendingActivation(candidateVersion))
            throw new InvalidOperationException(
                $"Lattice {candidateVersion} is still within its startup health window; it will not be replaced.");
        if (UpdateVersionRetention.IsVersionRunning(candidateDirectory))
            throw new InvalidOperationException(
                $"Lattice {candidateVersion} is running and will not be replaced.");

        // Validation is deletion authorization only, never execution trust.
        // The directory is removed and the signed ZIP is always downloaded and
        // hashed again; a local lookalike can therefore never bypass the signed
        // asset digest by pre-creating versions/<version>.
        UpdateSecurity.ValidatePackageDirectory(candidateDirectory, candidateVersion);
        var discardedRoot = Path.Combine(_installation.UpdatesRoot, "discarded");
        Directory.CreateDirectory(discardedRoot);
        var discarded = Path.Combine(
            discardedRoot,
            $"{candidateVersion}-{Guid.NewGuid():N}");
        Directory.Move(candidateDirectory, discarded);
        try
        {
            Directory.Delete(discarded, recursive: true);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // The atomic move already cleared the executable version path. Old
            // quarantined bytes are inert and can be cleaned on a later run.
            UpdateMaintenance.RecordIssue(_installation, "discarded-candidate-cleanup", error);
        }
    }

    private bool HasLivePendingActivation(StableSemanticVersion candidateVersion)
    {
        if (_installation is null) return false;
        var pendingRoot = Path.Combine(_installation.UpdatesRoot, "pending");
        if (!Directory.Exists(pendingRoot)) return false;
        var now = DateTimeOffset.UtcNow;
        foreach (var path in Directory.EnumerateFiles(pendingRoot, "*.json", SearchOption.TopDirectoryOnly))
        {
            try
            {
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0) continue;
                var pending = ReadBoundedJson<PendingUpdateActivation>(path, 16 * 1024);
                if (!DateTimeOffset.TryParse(pending.CreatedAt, out var createdAt)
                    || createdAt < now.AddMinutes(-15)
                    || createdAt > now.AddMinutes(1)) continue;
                if (StableSemanticVersion.Parse(pending.CandidateVersion) == candidateVersion)
                    return true;
            }
            catch (Exception error) when (error is IOException
                or UnauthorizedAccessException
                or InvalidDataException
                or JsonException)
            {
                // Malformed files are not evidence of a live activation.
            }
        }
        return false;
    }

    private static async Task<byte[]> DownloadBoundedBytesAsync(
        Uri url,
        long maximumBytes,
        CancellationToken cancellationToken)
    {
        using var response = await Client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength is long length && (length <= 0 || length > maximumBytes))
            throw new InvalidDataException($"{url.Segments.Last()} has an unsafe size.");
        await using var source = await response.Content.ReadAsStreamAsync(cancellationToken);
        using var destination = new MemoryStream();
        var buffer = new byte[16 * 1024];
        while (true)
        {
            var count = await source.ReadAsync(buffer, cancellationToken);
            if (count == 0) break;
            if (destination.Length + count > maximumBytes)
                throw new InvalidDataException($"{url.Segments.Last()} exceeds its safe size limit.");
            destination.Write(buffer, 0, count);
        }
        if (destination.Length == 0)
            throw new InvalidDataException($"{url.Segments.Last()} is empty.");
        return destination.ToArray();
    }

    private static HttpClient CreateClient()
    {
        var client = new HttpClient(new HttpClientHandler
        {
            AutomaticDecompression = System.Net.DecompressionMethods.All,
        })
        {
            Timeout = TimeSpan.FromMinutes(5),
        };
        client.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("Lattice-Updater", "2.0"));
        return client;
    }
}
