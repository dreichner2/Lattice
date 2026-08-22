using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;

namespace CSLibrary.Windows;

internal sealed class UpdateService
{
    internal const string Repository = "dreichner2/cs-library";
    internal const string Channel = "main";
    internal const string Platform = "windows-x64";
    private const long MaximumArchiveSize = 1_073_741_824;
    private const long MaximumExtractedSize = 2_147_483_648;
    private static readonly Uri LatestCommitUrl = new(
        "https://api.github.com/repos/dreichner2/cs-library/commits/main");
    private static readonly Uri ManifestUrl = new(
        "https://github.com/dreichner2/cs-library/releases/download/latest-main/update-manifest.json");
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = false,
    };
    private static readonly HttpClient Client = CreateClient();

    internal static readonly string SettingsRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "CS Library");
    internal static readonly string UpdatesRoot = Path.Combine(SettingsRoot, "Updates");
    internal static readonly string PendingCleanupPath = Path.Combine(UpdatesRoot, "pending-update.json");
    internal static readonly string InstallerErrorPath = Path.Combine(UpdatesRoot, "installer-error.txt");

    public string CurrentCommit { get; } = ReadCurrentCommit();

    public async Task<DesktopUpdateCheck> CheckAsync(CancellationToken cancellationToken)
    {
        var latest = await GetJsonAsync<GitHubBranchCommit>(LatestCommitUrl, cancellationToken);
        if (!IsFullCommit(latest.Sha))
            throw new InvalidDataException("GitHub did not return a full main-branch commit.");
        if (string.Equals(CurrentCommit, latest.Sha, StringComparison.Ordinal))
            return new DesktopUpdateCheck(DesktopUpdateState.Current, CurrentCommit, latest.Sha);

        DesktopUpdateManifest manifest;
        try
        {
            manifest = await GetJsonAsync<DesktopUpdateManifest>(ManifestUrl, cancellationToken);
        }
        catch (HttpRequestException error) when (error.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            return new DesktopUpdateCheck(DesktopUpdateState.Preparing, CurrentCommit, latest.Sha);
        }
        var asset = ValidateReleaseManifest(manifest);
        if (!string.Equals(manifest.Commit, latest.Sha, StringComparison.Ordinal))
            return new DesktopUpdateCheck(DesktopUpdateState.Preparing, CurrentCommit, latest.Sha);
        return new DesktopUpdateCheck(DesktopUpdateState.Available, CurrentCommit, latest.Sha, asset);
    }

    public async Task<string> DownloadAndStageAsync(
        DesktopUpdateCheck update,
        IProgress<int>? progress,
        CancellationToken cancellationToken)
    {
        if (update.State != DesktopUpdateState.Available || update.Asset?.Url is null)
            throw new InvalidOperationException("There is no verified Windows update to install.");

        Directory.CreateDirectory(UpdatesRoot);
        var archivePath = Path.Combine(UpdatesRoot, $"Lattice-Windows-{update.LatestCommit}.zip");
        if (File.Exists(archivePath)) File.Delete(archivePath);

        using var response = await Client.GetAsync(
            update.Asset.Url,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken);
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength is long publishedLength
            && publishedLength != update.Asset.Size)
            throw new InvalidDataException("The downloaded update size does not match its release metadata.");

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
                if (received > update.Asset.Size || received > MaximumArchiveSize)
                    throw new InvalidDataException("The downloaded update is larger than its release metadata.");
                await destination.WriteAsync(buffer.AsMemory(0, count), cancellationToken);
                digest.AppendData(buffer, 0, count);
                progress?.Report((int)Math.Clamp(received * 100 / update.Asset.Size, 0, 100));
            }
            if (received != update.Asset.Size)
                throw new InvalidDataException("The downloaded update is incomplete.");
            var expectedDigest = Convert.FromHexString(update.Asset.Sha256);
            if (!CryptographicOperations.FixedTimeEquals(digest.GetHashAndReset(), expectedDigest))
                throw new InvalidDataException("The downloaded update failed SHA-256 verification.");
        }

        var stagingPath = Path.Combine(UpdatesRoot, $"staged-{update.LatestCommit}");
        if (Directory.Exists(stagingPath)) Directory.Delete(stagingPath, recursive: true);
        Directory.CreateDirectory(stagingPath);
        ExtractArchiveSafely(archivePath, stagingPath);
        ValidateStagedPackage(stagingPath, update.LatestCommit);
        return stagingPath;
    }

    public void LaunchInstaller(string stagingPath, string expectedCommit)
    {
        ValidateStagedPackage(stagingPath, expectedCommit);
        var currentExecutable = Environment.ProcessPath;
        if (string.IsNullOrWhiteSpace(currentExecutable)
            || !File.Exists(currentExecutable)
            || !string.Equals(Path.GetFileName(currentExecutable), "Lattice.exe", StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Self-update is available only from the packaged Lattice.exe.");

        var targetRoot = Path.GetFullPath(AppContext.BaseDirectory).TrimEnd(Path.DirectorySeparatorChar);
        EnsureWritableDirectory(targetRoot);
        Directory.CreateDirectory(UpdatesRoot);
        var helperPath = Path.Combine(UpdatesRoot, $"LatticeUpdateInstaller-{expectedCommit}.exe");
        File.Copy(currentExecutable, helperPath, overwrite: true);

        var start = new ProcessStartInfo(helperPath)
        {
            UseShellExecute = false,
            WorkingDirectory = UpdatesRoot,
        };
        start.ArgumentList.Add("--apply-update");
        start.ArgumentList.Add("--parent-pid");
        start.ArgumentList.Add(Environment.ProcessId.ToString());
        start.ArgumentList.Add("--staging");
        start.ArgumentList.Add(Path.GetFullPath(stagingPath));
        start.ArgumentList.Add("--target");
        start.ArgumentList.Add(targetRoot);
        start.ArgumentList.Add("--expected-commit");
        start.ArgumentList.Add(expectedCommit);
        if (Process.Start(start) is null)
            throw new InvalidOperationException("The external update installer did not start.");
    }

    internal static DesktopUpdateAsset ValidateReleaseManifest(DesktopUpdateManifest manifest)
    {
        if (manifest.SchemaVersion != 1)
            throw new InvalidDataException($"Unsupported update schema {manifest.SchemaVersion}.");
        if (!string.Equals(manifest.Repository, Repository, StringComparison.Ordinal)
            || !string.Equals(manifest.Channel, Channel, StringComparison.Ordinal))
            throw new InvalidDataException("The update metadata belongs to a different channel.");
        if (!IsFullCommit(manifest.Commit)
            || !DateTimeOffset.TryParse(manifest.PublishedAt, out _))
            throw new InvalidDataException("The update metadata is incomplete.");
        if (!manifest.Assets.TryGetValue(Platform, out var asset) || asset.Url is null)
            throw new InvalidDataException("The release does not include a Windows x64 application.");
        if (asset.Size <= 0 || asset.Size > MaximumArchiveSize || !IsSha256(asset.Sha256))
            throw new InvalidDataException("The Windows update asset metadata is invalid.");
        var expectedPrefix = $"/{Repository}/releases/download/latest-main/";
        if (!asset.Url.IsAbsoluteUri
            || asset.Url.Scheme != Uri.UriSchemeHttps
            || !string.Equals(asset.Url.Host, "github.com", StringComparison.OrdinalIgnoreCase)
            || !asset.Url.AbsolutePath.StartsWith(expectedPrefix, StringComparison.Ordinal)
            || !string.IsNullOrEmpty(asset.Url.Query)
            || !string.IsNullOrEmpty(asset.Url.Fragment)
            || !string.IsNullOrEmpty(asset.Url.UserInfo))
            throw new InvalidDataException("The update asset is not at the expected GitHub release location.");
        return asset;
    }

    internal static PackageFileManifest ValidateStagedPackage(string root, string expectedCommit)
    {
        root = Path.GetFullPath(root);
        var buildInfo = ReadJsonFile<PackageBuildInfo>(Path.Combine(root, "update-build.json"));
        if (buildInfo.SchemaVersion != 1
            || !string.Equals(buildInfo.Repository, Repository, StringComparison.Ordinal)
            || !string.Equals(buildInfo.Channel, Channel, StringComparison.Ordinal)
            || !string.Equals(buildInfo.Commit, expectedCommit, StringComparison.Ordinal))
            throw new InvalidDataException("The staged package does not match the expected main commit.");

        var manifest = ReadJsonFile<PackageFileManifest>(Path.Combine(root, "update-files.json"));
        ValidateOwnedFiles(root, manifest);
        foreach (var required in new[]
        {
            "Lattice.exe",
            "Server/LatticeServer.exe",
            "update-build.json",
            "update-files.json",
        })
        {
            if (!manifest.Files.Contains(required, StringComparer.OrdinalIgnoreCase))
                throw new InvalidDataException($"The staged package does not own required file {required}.");
        }
        return manifest;
    }

    internal static PackageFileManifest? TryReadOwnedFiles(string root)
    {
        try
        {
            var manifest = ReadJsonFile<PackageFileManifest>(Path.Combine(root, "update-files.json"));
            ValidateOwnedFiles(root, manifest, requireFiles: false);
            return manifest;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidDataException or JsonException)
        {
            return null;
        }
    }

    internal static string ResolveOwnedPath(string root, string relative)
    {
        if (string.IsNullOrWhiteSpace(relative)
            || Path.IsPathRooted(relative)
            || relative.Contains('\\')
            || relative.Split('/').Any(part => part is "" or "." or ".." || part.Contains(':')))
            throw new InvalidDataException($"Unsafe updater-owned path: {relative}");
        var first = relative.Split('/')[0];
        if (new[] { "books", "papers", "lectures" }.Contains(first, StringComparer.OrdinalIgnoreCase))
            throw new InvalidDataException($"Private library content cannot be updater-owned: {relative}");
        var full = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
        var prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"Updater-owned path escapes its package: {relative}");
        return full;
    }

    internal static bool IsFullCommit(string value) =>
        value.Length == 40 && value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    internal static void FinalizeSuccessfulUpdate()
    {
        try
        {
            if (!File.Exists(PendingCleanupPath)) return;
            var pending = ReadJsonFile<PendingUpdateCleanup>(PendingCleanupPath);
            if (!IsFullCommit(pending.Commit)
                || !string.Equals(pending.Commit, ReadCurrentCommit(), StringComparison.Ordinal)) return;
            RemoveKnownUpdateDirectory(pending.BackupPath, $"backup-{pending.Commit}");
            RemoveKnownUpdateDirectory(pending.StagingPath, $"staged-{pending.Commit}");
            RemoveKnownUpdateFile($"Lattice-Windows-{pending.Commit}.zip");
            RemoveKnownUpdateFile($"LatticeUpdateInstaller-{pending.Commit}.exe");
            File.Delete(PendingCleanupPath);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or InvalidDataException or JsonException)
        {
            // A later launch can retry cleanup. Never block the reader over old rollback files.
        }
    }

    internal static string? TakeInstallerError()
    {
        try
        {
            if (!File.Exists(InstallerErrorPath)) return null;
            var message = File.ReadAllText(InstallerErrorPath);
            File.Delete(InstallerErrorPath);
            return message.Length <= 4000 ? message : message[..4000];
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static HttpClient CreateClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromMinutes(5) };
        client.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("Lattice-Updater", "1.0"));
        client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/vnd.github+json"));
        return client;
    }

    private static async Task<T> GetJsonAsync<T>(Uri url, CancellationToken cancellationToken)
    {
        using var response = await Client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        response.EnsureSuccessStatusCode();
        if (response.Content.Headers.ContentLength is > 1_048_576)
            throw new InvalidDataException("GitHub returned unexpectedly large update metadata.");
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using var memory = new MemoryStream();
        var buffer = new byte[64 * 1024];
        while (true)
        {
            var count = await stream.ReadAsync(buffer, cancellationToken);
            if (count == 0) break;
            if (memory.Length + count > 1_048_576)
                throw new InvalidDataException("GitHub returned unexpectedly large update metadata.");
            memory.Write(buffer, 0, count);
        }
        memory.Position = 0;
        return await JsonSerializer.DeserializeAsync<T>(memory, JsonOptions, cancellationToken)
            ?? throw new InvalidDataException("GitHub returned empty update metadata.");
    }

    private static void ExtractArchiveSafely(string archivePath, string stagingPath)
    {
        using var archive = ZipFile.OpenRead(archivePath);
        long extractedSize = 0;
        foreach (var entry in archive.Entries)
        {
            var relative = entry.FullName.Replace('\\', '/');
            if (string.IsNullOrEmpty(relative)) continue;
            var destination = ResolveArchivePath(stagingPath, relative);
            if (relative.EndsWith('/'))
            {
                Directory.CreateDirectory(destination);
                continue;
            }
            extractedSize += entry.Length;
            if (extractedSize > MaximumExtractedSize)
                throw new InvalidDataException("The update expands beyond its safe size limit.");
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            entry.ExtractToFile(destination, overwrite: false);
        }
    }

    private static string ResolveArchivePath(string root, string relative)
    {
        if (Path.IsPathRooted(relative)
            || relative.Split('/').Any(part => part is ".." || part.Contains(':')))
            throw new InvalidDataException($"Unsafe path in update archive: {relative}");
        var full = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
        var prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"Update archive path escapes staging: {relative}");
        return full;
    }

    private static void ValidateOwnedFiles(string root, PackageFileManifest manifest, bool requireFiles = true)
    {
        if (manifest.SchemaVersion != 1 || manifest.Files.Count == 0)
            throw new InvalidDataException("The package file manifest is invalid.");
        var unique = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var relative in manifest.Files)
        {
            if (!unique.Add(relative))
                throw new InvalidDataException($"Duplicate updater-owned path: {relative}");
            var path = ResolveOwnedPath(root, relative);
            if (requireFiles && !File.Exists(path))
                throw new InvalidDataException($"The package is missing updater-owned file {relative}.");
        }
    }

    private static T ReadJsonFile<T>(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        if (stream.Length > 4 * 1024 * 1024)
            throw new InvalidDataException($"Update metadata is unexpectedly large: {Path.GetFileName(path)}");
        return JsonSerializer.Deserialize<T>(stream, JsonOptions)
            ?? throw new InvalidDataException($"Update metadata is empty: {Path.GetFileName(path)}");
    }

    private static string ReadCurrentCommit()
    {
        var value = Assembly.GetExecutingAssembly()
            .GetCustomAttributes<AssemblyMetadataAttribute>()
            .FirstOrDefault(attribute => attribute.Key == "LatticeCommit")
            ?.Value;
        return value is not null && IsFullCommit(value) ? value : "development";
    }

    private static bool IsSha256(string value) =>
        value.Length == 64 && value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    private static void EnsureWritableDirectory(string root)
    {
        var probe = Path.Combine(root, $".cs-library-update-write-{Guid.NewGuid():N}");
        try
        {
            using (File.Create(probe)) { }
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            throw new UnauthorizedAccessException(
                "Lattice cannot update this installation without write access. Reinstall it under your user account.",
                error);
        }
        finally
        {
            if (File.Exists(probe)) File.Delete(probe);
        }
    }

    private static void RemoveKnownUpdateDirectory(string path, string expectedName)
    {
        if (string.IsNullOrWhiteSpace(path) || !Directory.Exists(path)) return;
        var full = Path.GetFullPath(path);
        var updatesPrefix = Path.GetFullPath(UpdatesRoot).TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        if (!full.StartsWith(updatesPrefix, StringComparison.OrdinalIgnoreCase)
            || !string.Equals(Path.GetFileName(full), expectedName, StringComparison.Ordinal))
            throw new InvalidDataException("Refusing to remove an unexpected updater directory.");
        Directory.Delete(full, recursive: true);
    }

    private static void RemoveKnownUpdateFile(string expectedName)
    {
        var path = Path.Combine(UpdatesRoot, expectedName);
        if (File.Exists(path)) File.Delete(path);
    }
}
