using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace CSLibrary.Windows;

internal static class UpdateSecurity
{
    internal const string Repository = "dreichner2/Lattice";
    internal const string Platform = "windows-x64";
    internal const long MaximumManifestSize = 64 * 1024;
    internal const long MaximumArchiveSize = 1_073_741_824;
    internal const long MaximumExtractedSize = 2_147_483_648;
    internal const int MaximumArchiveEntries = 20_000;
    // 2.1.1 is the last published package without Move Library. Keep it valid
    // as a rollback target while requiring the helper from the next release on.
    private static readonly StableSemanticVersion StorageHelperIntroducedVersion = new(2, 1, 2);

    // The corresponding private key is kept locally outside the repository and
    // release workflow. Only manifests signed by that off-repository key can
    // authorize code.
    internal const string ProductionPublicKeyPem = """
        -----BEGIN PUBLIC KEY-----
        MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEA1MwHuaIA2eztxZaUBox3
        OeJE32teqcIXLJI1yX0ZRyIqUokgRexJbPegNloVkRtiTBswTrqWGXq/0DuSfckM
        SqpSULxvn59QVYuPvJy6PKYrAHQXqymSiSklWt01dzqz9oWDXhR9jGHX2fWWOiEG
        xxJ5U/rm0p8yiVItdFyzeUtLX6myejl0R4JEGpDk4U0nT6Vww8FxBK9HmRJPzecp
        yPLtEOWTpKwCa8WqEtU8nyma8EiHCtr6630IoeOUfayqus5evKFgCz4zuZUtxnju
        4znz9OJYqgN1uykqkWE2s0sDskLkUaPbUC4A1cxI7z7hEadTVF6s2V7eQLeEk2X5
        VVo4kHm3pNEK282BSuYTEbweszCPSY2o4SycnK9Cd9bZLNtv6LZqoKRPMZ5pkOrW
        /MzK3LgME1iWeD9BPHbPoAst7BMi3apDrTd/diGANmhlrMeT5kQMvw0VVGITiPVJ
        dYItgfI84m4cdXx9MRoZuGZqPJNSZEMaxdJpLueKYwdRAgMBAAE=
        -----END PUBLIC KEY-----
        """;

    private static readonly JsonSerializerOptions StrictJson = new()
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = System.Text.Json.Serialization.JsonUnmappedMemberHandling.Disallow,
        MaxDepth = 16,
    };

    internal static ValidatedDesktopRelease VerifyAndValidateManifest(
        ReadOnlySpan<byte> manifestBytes,
        ReadOnlySpan<byte> signatureBytes,
        StableSemanticVersion installedVersion,
        string publicKeyPem = ProductionPublicKeyPem)
    {
        if (manifestBytes.IsEmpty || manifestBytes.Length > MaximumManifestSize)
            throw new InvalidDataException("The update manifest has an unsafe size.");

        using var rsa = RSA.Create();
        try
        {
            rsa.ImportFromPem(publicKeyPem);
        }
        catch (Exception error) when (error is ArgumentException or CryptographicException)
        {
            throw new CryptographicException("The embedded update verification key is invalid.", error);
        }
        if (rsa.KeySize != 3072 || signatureBytes.Length != rsa.KeySize / 8)
            throw new CryptographicException("The update signature is not an RSA-3072 signature.");
        if (!rsa.VerifyData(
                manifestBytes,
                signatureBytes,
                HashAlgorithmName.SHA256,
                RSASignaturePadding.Pkcs1))
            throw new CryptographicException("The update manifest signature is invalid.");

        // Nothing from the manifest is parsed or trusted until its exact bytes
        // pass the public-key check above.
        DesktopUpdateManifest manifest;
        try
        {
            var trustedManifestBytes = manifestBytes.ToArray();
            using var document = JsonDocument.Parse(trustedManifestBytes, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 16,
            });
            RejectDuplicateProperties(document.RootElement);
            manifest = JsonSerializer.Deserialize<DesktopUpdateManifest>(trustedManifestBytes, StrictJson)
                ?? throw new InvalidDataException("The signed update manifest is empty.");
        }
        catch (JsonException error)
        {
            throw new InvalidDataException("The signed update manifest is malformed.", error);
        }

        if (manifest.SchemaVersion != 2
            || !string.Equals(manifest.Repository, Repository, StringComparison.Ordinal))
            throw new InvalidDataException("The signed update manifest belongs to an unsupported source.");

        var releaseVersion = StableSemanticVersion.Parse(manifest.ReleaseVersion, "release version");
        var expectedTag = $"v{releaseVersion}";
        if (!string.Equals(manifest.ReleaseTag, expectedTag, StringComparison.Ordinal))
            throw new InvalidDataException("The signed release tag does not match its semantic version.");
        if (!DateTimeOffset.TryParse(manifest.PublishedAt, out var publishedAt)
            || publishedAt.Offset != TimeSpan.Zero)
            throw new InvalidDataException("The signed release timestamp must be a UTC ISO-8601 value.");

        var versionOrder = releaseVersion.CompareTo(installedVersion);
        if (versionOrder == 0)
            throw new UpdateVersionRejectedException(
                UpdateVersionRejection.SameVersion,
                $"Lattice {installedVersion} is already installed.");
        if (versionOrder < 0)
            throw new UpdateVersionRejectedException(
                UpdateVersionRejection.Downgrade,
                $"Refusing to downgrade Lattice {installedVersion} to {releaseVersion}.");

        if (manifest.Assets.Count == 0
            || !manifest.Assets.TryGetValue(Platform, out var asset))
            throw new InvalidDataException("The signed release does not include Windows x64.");
        ValidateAssetForVersion(releaseVersion, asset);
        return new ValidatedDesktopRelease(releaseVersion, asset);
    }

    internal static void ValidateAssetForVersion(
        StableSemanticVersion releaseVersion,
        DesktopUpdateAsset asset)
    {
        if (asset.Size <= 0 || asset.Size > MaximumArchiveSize || !IsLowerHexSha256(asset.Sha256))
            throw new InvalidDataException("The signed Windows asset metadata is invalid.");

        var expectedTag = $"v{releaseVersion}";
        var expectedUrl = $"https://github.com/{Repository}/releases/download/{expectedTag}/Lattice-Windows-win-x64.zip";
        if (!string.Equals(asset.Url, expectedUrl, StringComparison.Ordinal)
            || !Uri.TryCreate(asset.Url, UriKind.Absolute, out var assetUri)
            || assetUri.Scheme != Uri.UriSchemeHttps
            || !string.Equals(assetUri.Host, "github.com", StringComparison.OrdinalIgnoreCase)
            || !string.IsNullOrEmpty(assetUri.Query)
            || !string.IsNullOrEmpty(assetUri.Fragment)
            || !string.IsNullOrEmpty(assetUri.UserInfo))
            throw new InvalidDataException("The signed Windows asset URL is not the exact versioned GitHub release URL.");
    }

    internal static UpdatePackageMetadata ValidatePackageDirectory(
        string root,
        StableSemanticVersion expectedVersion)
    {
        root = Path.GetFullPath(root);
        var metadataPath = Path.Combine(root, "update-package.json");
        UpdatePackageMetadata metadata;
        try
        {
            using var stream = new FileStream(metadataPath, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (stream.Length <= 0 || stream.Length > 16 * 1024)
                throw new InvalidDataException("The package metadata has an unsafe size.");
            using var document = JsonDocument.Parse(stream, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 8,
            });
            RejectDuplicateProperties(document.RootElement);
            metadata = document.RootElement.Deserialize<UpdatePackageMetadata>(StrictJson)
                ?? throw new InvalidDataException("The package metadata is empty.");
        }
        catch (JsonException error)
        {
            throw new InvalidDataException("The package metadata is malformed.", error);
        }

        var metadataVersion = StableSemanticVersion.Parse(metadata.Version, "package version");
        if (metadata.SchemaVersion != 1
            || !string.Equals(metadata.Repository, Repository, StringComparison.Ordinal)
            || !string.Equals(metadata.Platform, Platform, StringComparison.Ordinal)
            || metadataVersion != expectedVersion)
            throw new InvalidDataException("The extracted package does not match the signed release.");

        foreach (var relative in new[]
        {
            "Lattice.exe",
            "Lattice.ico",
            "Server/LatticeServer.exe",
            "ui/index.html",
            "ui/app.js",
            "update-package.json",
            "update-files.json",
        })
        {
            var path = ResolveContainedPath(root, relative);
            if (!File.Exists(path))
                throw new InvalidDataException($"The extracted update is missing {relative}.");
        }
        if (RequiresStorageHelper(expectedVersion)
            && !File.Exists(ResolveContainedPath(root, "Tools/LatticeStorage.exe")))
            throw new InvalidDataException("The extracted update is missing Tools/LatticeStorage.exe.");
        ValidatePackageFiles(root, expectedVersion);
        return metadata;
    }

    private static void ValidatePackageFiles(string root, StableSemanticVersion packageVersion)
    {
        var manifestPath = Path.Combine(root, "update-files.json");
        UpdatePackageFileManifest manifest;
        try
        {
            using var stream = new FileStream(manifestPath, FileMode.Open, FileAccess.Read, FileShare.Read);
            if (stream.Length <= 0 || stream.Length > 4 * 1024 * 1024)
                throw new InvalidDataException("The package file manifest has an unsafe size.");
            using var document = JsonDocument.Parse(stream, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 16,
            });
            RejectDuplicateProperties(document.RootElement);
            manifest = document.RootElement.Deserialize<UpdatePackageFileManifest>(StrictJson)
                ?? throw new InvalidDataException("The package file manifest is empty.");
        }
        catch (JsonException error)
        {
            throw new InvalidDataException("The package file manifest is malformed.", error);
        }
        if (manifest.SchemaVersion != 1
            || manifest.Files.Count == 0
            || manifest.Files.Count > MaximumArchiveEntries)
            throw new InvalidDataException("The package file manifest has an unsupported shape.");

        var expected = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        long totalSize = 0;
        foreach (var file in manifest.Files)
        {
            if (!expected.Add(file.Path)
                || string.Equals(file.Path, "update-files.json", StringComparison.OrdinalIgnoreCase)
                || file.Size < 0
                || file.Size > MaximumExtractedSize - totalSize
                || !IsLowerHexSha256(file.Sha256))
                throw new InvalidDataException($"Invalid package file entry: {file.Path}");
            totalSize += file.Size;
            var path = ResolveContainedPath(root, file.Path);
            var information = new FileInfo(path);
            if (!information.Exists
                || information.Length != file.Size
                || (information.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException($"The package file does not match its manifest: {file.Path}");
            using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
            var actualDigest = SHA256.HashData(stream);
            var expectedDigest = Convert.FromHexString(file.Sha256);
            if (!CryptographicOperations.FixedTimeEquals(actualDigest, expectedDigest))
                throw new CryptographicException($"The package file failed verification: {file.Path}");
        }

        foreach (var required in new[]
        {
            "Lattice.exe",
            "Lattice.ico",
            "Server/LatticeServer.exe",
            "ui/index.html",
            "ui/app.js",
            "update-package.json",
        })
        {
            if (!expected.Contains(required))
                throw new InvalidDataException($"The package file manifest omits {required}.");
        }
        if (RequiresStorageHelper(packageVersion) && !expected.Contains("Tools/LatticeStorage.exe"))
            throw new InvalidDataException("The package file manifest omits Tools/LatticeStorage.exe.");

        var actual = EnumerateRegularPackageFiles(root);
        actual.Remove("update-files.json");
        if (!actual.SetEquals(expected))
            throw new InvalidDataException("The package contains unverified or missing files.");
    }

    private static bool RequiresStorageHelper(StableSemanticVersion version) =>
        version.CompareTo(StorageHelperIntroducedVersion) >= 0;

    private static HashSet<string> EnumerateRegularPackageFiles(string root)
    {
        var files = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var pending = new Stack<string>();
        pending.Push(root);
        while (pending.Count > 0)
        {
            var directory = pending.Pop();
            foreach (var child in Directory.EnumerateFileSystemEntries(directory))
            {
                var attributes = File.GetAttributes(child);
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidDataException("Reparse points are not permitted in a Lattice version directory.");
                if ((attributes & FileAttributes.Directory) != 0)
                {
                    pending.Push(child);
                    continue;
                }
                var relative = Path.GetRelativePath(root, child)
                    .Replace(Path.DirectorySeparatorChar, '/');
                if (!files.Add(relative))
                    throw new InvalidDataException($"Duplicate package file path: {relative}");
                if (files.Count > MaximumArchiveEntries)
                    throw new InvalidDataException("The package contains too many files.");
            }
        }
        return files;
    }

    internal static void ExtractArchiveSafely(string archivePath, string destinationRoot)
    {
        destinationRoot = Path.GetFullPath(destinationRoot);
        if (Directory.Exists(destinationRoot) && Directory.EnumerateFileSystemEntries(destinationRoot).Any())
            throw new InvalidDataException("The update staging directory is not empty.");
        Directory.CreateDirectory(destinationRoot);

        using var archive = ZipFile.OpenRead(archivePath);
        if (archive.Entries.Count == 0 || archive.Entries.Count > MaximumArchiveEntries)
            throw new InvalidDataException("The update archive contains an unsafe number of entries.");

        long extractedSize = 0;
        var entries = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in archive.Entries)
        {
            var relative = entry.FullName;
            if (string.IsNullOrEmpty(relative)) continue;
            if (relative.Contains('\\'))
                throw new InvalidDataException("Backslash paths are not permitted in update archives.");
            var isDirectory = relative.EndsWith("/", StringComparison.Ordinal);
            var normalized = relative.TrimEnd('/');
            if (normalized.Length == 0) continue;
            if (!entries.Add(normalized))
                throw new InvalidDataException($"Duplicate path in update archive: {normalized}");
            RejectLinkEntry(entry, normalized);
            var destination = ResolveContainedPath(destinationRoot, normalized);
            if (isDirectory)
            {
                Directory.CreateDirectory(destination);
                continue;
            }
            if (entry.Length < 0 || entry.Length > MaximumExtractedSize - extractedSize)
                throw new InvalidDataException("The update expands beyond its safe size limit.");
            extractedSize += entry.Length;
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            entry.ExtractToFile(destination, overwrite: false);
            if ((File.GetAttributes(destination) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException($"A reparse point was extracted from {normalized}.");
        }
    }

    internal static string ResolveContainedPath(string root, string relative)
    {
        var parts = relative.Split('/');
        if (string.IsNullOrWhiteSpace(relative)
            || relative.Length > 512
            || Path.IsPathRooted(relative)
            || relative.Contains('\\')
            || parts.Any(IsUnsafeWindowsPathSegment))
            throw new InvalidDataException($"Unsafe update path: {relative}");
        var prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        var full = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
        if (!full.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException($"Update path escapes its version directory: {relative}");
        return full;
    }

    private static bool IsUnsafeWindowsPathSegment(string part)
    {
        if (part is "" or "." or ".."
            || part.EndsWith(' ')
            || part.EndsWith('.')
            || part.Any(character => character < 32 || "<>:\"|?*".Contains(character))) return true;
        var stem = part.Split('.')[0];
        return stem.Equals("CON", StringComparison.OrdinalIgnoreCase)
            || stem.Equals("PRN", StringComparison.OrdinalIgnoreCase)
            || stem.Equals("AUX", StringComparison.OrdinalIgnoreCase)
            || stem.Equals("NUL", StringComparison.OrdinalIgnoreCase)
            || (stem.Length == 4
                && (stem.StartsWith("COM", StringComparison.OrdinalIgnoreCase)
                    || stem.StartsWith("LPT", StringComparison.OrdinalIgnoreCase))
                && stem[3] is >= '1' and <= '9');
    }

    internal static bool IsLowerHexSha256(string value) =>
        value.Length == 64 && value.All(character => character is >= '0' and <= '9' or >= 'a' and <= 'f');

    internal static void RejectDuplicateProperties(JsonElement element)
    {
        switch (element.ValueKind)
        {
            case JsonValueKind.Object:
                var names = new HashSet<string>(StringComparer.Ordinal);
                foreach (var property in element.EnumerateObject())
                {
                    if (!names.Add(property.Name))
                        throw new InvalidDataException($"Duplicate JSON property: {property.Name}");
                    RejectDuplicateProperties(property.Value);
                }
                break;
            case JsonValueKind.Array:
                foreach (var item in element.EnumerateArray()) RejectDuplicateProperties(item);
                break;
        }
    }

    private static void RejectLinkEntry(ZipArchiveEntry entry, string relative)
    {
        // Unix file type bits are preserved by many ZIP producers. A symlink
        // could redirect later writes outside staging, so no link-like entry is
        // accepted even though .NET normally materializes it as a plain file.
        var unixType = (entry.ExternalAttributes >> 16) & 0xF000;
        if (unixType == 0xA000)
            throw new InvalidDataException($"Symbolic links are not permitted in updates: {relative}");
        if ((entry.ExternalAttributes & (int)FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException($"Reparse points are not permitted in updates: {relative}");
    }
}
