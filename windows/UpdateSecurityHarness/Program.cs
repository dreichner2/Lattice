using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using CSLibrary.Windows;

var tests = new (string Name, Action Body)[]
{
    ("accepts authentic newer stable manifest", AcceptsAuthenticManifest),
    ("rejects changed manifest bytes", RejectsChangedManifest),
    ("rejects same version and downgrade", RejectsNonUpgrade),
    ("rejects signed wrong repository URL", RejectsWrongAssetUrl),
    ("rejects oversized manifest before parsing", RejectsOversizedManifest),
    ("extracts a bounded valid package", ExtractsValidPackage),
    ("rejects ZIP traversal", RejectsZipTraversal),
    ("rejects duplicate case-folded ZIP paths", RejectsDuplicateZipPaths),
    ("rejects ZIP symlinks", RejectsZipSymlink),
    ("rejects Windows device-name ZIP entries", RejectsWindowsDevicePath),
    ("accepts the pre-storage-helper rollback package", AcceptsLegacyPackageWithoutStorageHelper),
    ("requires the storage helper in new packages", RejectsNewPackageWithoutStorageHelper),
    ("requires Study Lab assets in 2.3.3 packages", RejectsNewPackageWithoutStudyLab),
    ("requires reader workspace assets in 2.4.0 packages", RejectsNewPackageWithoutReaderWorkspace),
    ("removes a complete stale candidate before redownload", RemovesStaleCandidateForRedownload),
    ("removes only recognized expired activation records", RemovesExpiredActivation),
    ("keeps active authority monotonic when an older candidate finishes last", RejectsLateOlderPromotion),
    ("prunes a valid obsolete version", PrunesValidObsoleteVersion),
    ("leaves a corrupt obsolete version without blocking startup", IgnoresCorruptObsoleteVersion),
    ("accepts only an exact out-of-install launcher mirror", AcceptsOnlyExactPortableMirror),
    ("atomically replaces a digest-bound portable launcher", ReplacesVerifiedPortableLauncher),
};

var failures = 0;
foreach (var test in tests)
{
    try
    {
        test.Body();
        Console.WriteLine($"PASS {test.Name}");
    }
    catch (Exception error)
    {
        failures += 1;
        Console.Error.WriteLine($"FAIL {test.Name}: {error}");
    }
}
return failures == 0 ? 0 : 1;

static void AcceptsAuthenticManifest()
{
    using var key = RSA.Create(3072);
    var bytes = BuildManifest("2.1.0");
    var release = UpdateSecurity.VerifyAndValidateManifest(
        bytes,
        Sign(key, bytes),
        StableSemanticVersion.Parse("2.0.0"),
        key.ExportSubjectPublicKeyInfoPem());
    Equal("2.1.0", release.Version.ToString());
    Equal(
        "https://github.com/dreichner2/Lattice/releases/download/v2.1.0/Lattice-Windows-win-x64.zip",
        release.Asset.Url);
}

static void RejectsChangedManifest()
{
    using var key = RSA.Create(3072);
    var bytes = BuildManifest("2.1.0");
    var signature = Sign(key, bytes);
    bytes[^2] ^= 1;
    Throws<CryptographicException>(() => UpdateSecurity.VerifyAndValidateManifest(
        bytes,
        signature,
        StableSemanticVersion.Parse("2.0.0"),
        key.ExportSubjectPublicKeyInfoPem()));
}

static void RejectsNonUpgrade()
{
    using var key = RSA.Create(3072);
    foreach (var (release, reason) in new[]
    {
        ("2.0.0", UpdateVersionRejection.SameVersion),
        ("1.9.9", UpdateVersionRejection.Downgrade),
    })
    {
        var bytes = BuildManifest(release);
        var error = Throws<UpdateVersionRejectedException>(() => UpdateSecurity.VerifyAndValidateManifest(
            bytes,
            Sign(key, bytes),
            StableSemanticVersion.Parse("2.0.0"),
            key.ExportSubjectPublicKeyInfoPem()));
        Equal(reason, error.Reason);
    }
}

static void RejectsWrongAssetUrl()
{
    using var key = RSA.Create(3072);
    var bytes = BuildManifest(
        "2.1.0",
        "https://github.com/attacker/repo/releases/download/v2.1.0/Lattice-Windows-win-x64.zip");
    Throws<InvalidDataException>(() => UpdateSecurity.VerifyAndValidateManifest(
        bytes,
        Sign(key, bytes),
        StableSemanticVersion.Parse("2.0.0"),
        key.ExportSubjectPublicKeyInfoPem()));
}

static void RejectsOversizedManifest()
{
    using var key = RSA.Create(3072);
    var bytes = new byte[UpdateSecurity.MaximumManifestSize + 1];
    Throws<InvalidDataException>(() => UpdateSecurity.VerifyAndValidateManifest(
        bytes,
        new byte[384],
        StableSemanticVersion.Parse("2.0.0"),
        key.ExportSubjectPublicKeyInfoPem()));
}

static void ExtractsValidPackage()
{
    WithTemporaryRoot(root =>
    {
        var archivePath = Path.Combine(root, "valid.zip");
        var package = Path.Combine(root, "package");
        BuildPackageDirectory(package, "2.1.0");
        ZipFile.CreateFromDirectory(package, archivePath);
        var destination = Path.Combine(root, "out");
        UpdateSecurity.ExtractArchiveSafely(archivePath, destination);
        var metadata = UpdateSecurity.ValidatePackageDirectory(
            destination,
            StableSemanticVersion.Parse("2.1.0"));
        Equal("2.1.0", metadata.Version);
    });
}

static void RejectsZipTraversal()
{
    WithTemporaryRoot(root =>
    {
        var archivePath = Path.Combine(root, "traversal.zip");
        using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
            AddEntry(archive, "../escaped.txt", "owned");
        var destination = Path.Combine(root, "out");
        Throws<InvalidDataException>(() => UpdateSecurity.ExtractArchiveSafely(archivePath, destination));
        if (File.Exists(Path.Combine(root, "escaped.txt"))) throw new Exception("Traversal created an outside file.");
    });
}

static void RejectsDuplicateZipPaths()
{
    WithTemporaryRoot(root =>
    {
        var archivePath = Path.Combine(root, "duplicates.zip");
        using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
        {
            AddEntry(archive, "ui/app.js", "one");
            AddEntry(archive, "UI/APP.JS", "two");
        }
        Throws<InvalidDataException>(() => UpdateSecurity.ExtractArchiveSafely(
            archivePath,
            Path.Combine(root, "out")));
    });
}

static void RejectsZipSymlink()
{
    WithTemporaryRoot(root =>
    {
        var archivePath = Path.Combine(root, "symlink.zip");
        using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
        {
            var entry = archive.CreateEntry("link");
            entry.ExternalAttributes = unchecked((int)0xA0000000);
            using var writer = new StreamWriter(entry.Open());
            writer.Write("target");
        }
        Throws<InvalidDataException>(() => UpdateSecurity.ExtractArchiveSafely(
            archivePath,
            Path.Combine(root, "out")));
    });
}

static void RejectsWindowsDevicePath()
{
    WithTemporaryRoot(root =>
    {
        var archivePath = Path.Combine(root, "device.zip");
        using (var archive = ZipFile.Open(archivePath, ZipArchiveMode.Create))
            AddEntry(archive, "ui/CON.txt", "unsafe");
        Throws<InvalidDataException>(() => UpdateSecurity.ExtractArchiveSafely(
            archivePath,
            Path.Combine(root, "out")));
    });
}

static void AcceptsLegacyPackageWithoutStorageHelper()
{
    WithTemporaryRoot(root =>
    {
        BuildPackageDirectory(root, "2.1.1", includeStorageHelper: false);
        var metadata = UpdateSecurity.ValidatePackageDirectory(
            root,
            StableSemanticVersion.Parse("2.1.1"));
        Equal("2.1.1", metadata.Version);
    });
}

static void RejectsNewPackageWithoutStorageHelper()
{
    WithTemporaryRoot(root =>
    {
        BuildPackageDirectory(root, "2.1.2", includeStorageHelper: false);
        Throws<InvalidDataException>(() => UpdateSecurity.ValidatePackageDirectory(
            root,
            StableSemanticVersion.Parse("2.1.2")));
    });
}

static void RejectsNewPackageWithoutStudyLab()
{
    WithTemporaryRoot(root =>
    {
        BuildPackageDirectory(root, "2.3.3");
        File.Delete(Path.Combine(root, "ui", "study-lab.js"));
        Throws<InvalidDataException>(() => UpdateSecurity.ValidatePackageDirectory(
            root,
            StableSemanticVersion.Parse("2.3.3")));
    });
}

static void RejectsNewPackageWithoutReaderWorkspace()
{
    WithTemporaryRoot(root =>
    {
        BuildPackageDirectory(root, "2.4.0");
        File.Delete(Path.Combine(root, "ui", "reader-desk.js"));
        Throws<InvalidDataException>(() => UpdateSecurity.ValidatePackageDirectory(
            root,
            StableSemanticVersion.Parse("2.4.0")));
    });
}

static void RemovesStaleCandidateForRedownload()
{
    WithTemporaryRoot(root =>
    {
        var installRoot = Path.Combine(root, "Lattice");
        var versionsRoot = Path.Combine(installRoot, "versions");
        var currentDirectory = Path.Combine(versionsRoot, "2.0.0");
        var candidateDirectory = Path.Combine(versionsRoot, "2.1.0");
        BuildPackageDirectory(currentDirectory, "2.0.0");
        BuildPackageDirectory(candidateDirectory, "2.1.0");
        var service = new UpdateService(new UpdateInstallation(
            installRoot,
            versionsRoot,
            currentDirectory,
            StableSemanticVersion.Parse("2.0.0")));
        service.RemoveRecognizedStaleCandidateForRedownload(StableSemanticVersion.Parse("2.1.0"));
        if (Directory.Exists(candidateDirectory))
            throw new Exception("Recognized stale candidate was not removed before redownload.");
    });
}

static void RemovesExpiredActivation()
{
    WithTemporaryRoot(root =>
    {
        var installRoot = Path.Combine(root, "Lattice");
        var versionsRoot = Path.Combine(installRoot, "versions");
        var currentDirectory = Path.Combine(versionsRoot, "2.0.0");
        var candidateDirectory = Path.Combine(versionsRoot, "2.1.0");
        BuildPackageDirectory(currentDirectory, "2.0.0");
        BuildPackageDirectory(candidateDirectory, "2.1.0");
        var service = new UpdateService(new UpdateInstallation(
            installRoot,
            versionsRoot,
            currentDirectory,
            StableSemanticVersion.Parse("2.0.0")));
        var pendingRoot = Path.Combine(installRoot, ".updates", "pending");
        Directory.CreateDirectory(pendingRoot);
        var now = DateTimeOffset.Parse("2026-08-21T12:00:00Z");
        var expiredId = Guid.NewGuid().ToString("N");
        var freshId = Guid.NewGuid().ToString("N");
        WritePending(expiredId, now.AddMinutes(-16));
        WritePending(freshId, now.AddMinutes(-14));

        Equal(1, service.RemoveExpiredPendingActivations(
            StableSemanticVersion.Parse("2.1.0"),
            now));
        if (File.Exists(Path.Combine(pendingRoot, $"{expiredId}.json")))
            throw new Exception("Expired activation was not removed.");
        if (!File.Exists(Path.Combine(pendingRoot, $"{freshId}.json")))
            throw new Exception("Fresh activation was removed.");

        void WritePending(string id, DateTimeOffset createdAt)
        {
            UpdateService.WriteNewJson(Path.Combine(pendingRoot, $"{id}.json"), new PendingUpdateActivation
            {
                SchemaVersion = 1,
                ActivationId = id,
                TokenSha256 = new string('a', 64),
                CreatedAt = createdAt.ToString("O"),
                PreviousVersion = "2.0.0",
                CandidateVersion = "2.1.0",
                CandidateDirectory = candidateDirectory,
            });
        }
    });
}

static void RejectsLateOlderPromotion()
{
    WithTemporaryRoot(root =>
    {
        var installRoot = Path.Combine(root, "Lattice");
        var versionsRoot = Path.Combine(installRoot, "versions");
        var version20 = Path.Combine(versionsRoot, "2.0.0");
        var version21 = Path.Combine(versionsRoot, "2.1.0");
        var version22 = Path.Combine(versionsRoot, "2.2.0");
        BuildPackageDirectory(version20, "2.0.0");
        BuildPackageDirectory(version21, "2.1.0");
        BuildPackageDirectory(version22, "2.2.0");
        var activePath = Path.Combine(installRoot, "active-version.json");
        UpdateService.WriteNewJson(activePath, new ActiveVersionRecord
        {
            SchemaVersion = 1,
            Version = "2.0.0",
            PreviousVersion = null,
            PromotedAt = "2026-08-21T12:00:00.0000000+00:00",
        });

        var candidate22 = new UpdateInstallation(
            installRoot,
            versionsRoot,
            version22,
            StableSemanticVersion.Parse("2.2.0"));
        Equal(
            StableSemanticVersion.Parse("2.0.0"),
            ActiveVersionAuthority.Promote(
                candidate22,
                StableSemanticVersion.Parse("2.2.0"),
                StableSemanticVersion.Parse("2.0.0"),
                Guid.NewGuid().ToString("N"),
                DateTimeOffset.Parse("2026-08-21T12:02:00Z")));

        var candidate21 = new UpdateInstallation(
            installRoot,
            versionsRoot,
            version21,
            StableSemanticVersion.Parse("2.1.0"));
        var rejection = Throws<UpdateVersionRejectedException>(() =>
            ActiveVersionAuthority.Promote(
                candidate21,
                StableSemanticVersion.Parse("2.1.0"),
                StableSemanticVersion.Parse("2.0.0"),
                Guid.NewGuid().ToString("N"),
                DateTimeOffset.Parse("2026-08-21T12:03:00Z")));
        Equal(UpdateVersionRejection.Downgrade, rejection.Reason);

        var active = UpdateService.ReadBoundedJson<ActiveVersionRecord>(activePath, 16 * 1024);
        Equal("2.2.0", active.Version);
        Equal("2.0.0", active.PreviousVersion);
    });
}

static void PrunesValidObsoleteVersion()
{
    WithTemporaryRoot(root =>
    {
        var installRoot = Path.Combine(root, "Lattice");
        var versionsRoot = Path.Combine(installRoot, "versions");
        var obsolete = Path.Combine(versionsRoot, "2.0.0");
        var previous = Path.Combine(versionsRoot, "2.1.0");
        var active = Path.Combine(versionsRoot, "2.2.0");
        var future = Path.Combine(versionsRoot, "2.3.0");
        BuildPackageDirectory(obsolete, "2.0.0");
        BuildPackageDirectory(previous, "2.1.0");
        BuildPackageDirectory(active, "2.2.0");
        BuildPackageDirectory(future, "2.3.0");
        var installation = new UpdateInstallation(
            installRoot,
            versionsRoot,
            active,
            StableSemanticVersion.Parse("2.2.0"));

        UpdateVersionRetention.PruneToActiveAndPrevious(
            installation,
            StableSemanticVersion.Parse("2.2.0"),
            StableSemanticVersion.Parse("2.1.0"));

        if (Directory.Exists(obsolete)) throw new Exception("Valid obsolete version was not pruned.");
        if (!Directory.Exists(previous) || !Directory.Exists(active) || !Directory.Exists(future))
            throw new Exception("Active, previous, or newer staged version was pruned.");
    });
}

static void IgnoresCorruptObsoleteVersion()
{
    WithTemporaryRoot(root =>
    {
        var installRoot = Path.Combine(root, "Lattice");
        var versionsRoot = Path.Combine(installRoot, "versions");
        var obsolete = Path.Combine(versionsRoot, "2.0.0");
        var previous = Path.Combine(versionsRoot, "2.1.0");
        var active = Path.Combine(versionsRoot, "2.2.0");
        BuildPackageDirectory(obsolete, "2.0.0");
        BuildPackageDirectory(previous, "2.1.0");
        BuildPackageDirectory(active, "2.2.0");
        var corruptExecutable = Path.Combine(obsolete, "Lattice.exe");
        var bytes = File.ReadAllBytes(corruptExecutable);
        bytes[0] ^= 1;
        File.WriteAllBytes(corruptExecutable, bytes);
        var installation = new UpdateInstallation(
            installRoot,
            versionsRoot,
            active,
            StableSemanticVersion.Parse("2.2.0"));

        UpdateVersionRetention.PruneToActiveAndPrevious(
            installation,
            StableSemanticVersion.Parse("2.2.0"),
            StableSemanticVersion.Parse("2.1.0"));

        if (!Directory.Exists(obsolete))
            throw new Exception("Corrupt obsolete content was treated as deletion authority.");
        if (!Directory.Exists(previous) || !Directory.Exists(active))
            throw new Exception("Corrupt obsolete content blocked healthy retention state.");
    });
}

static void AcceptsOnlyExactPortableMirror()
{
    WithTemporaryRoot(root =>
    {
        var installRoot = Path.Combine(root, "installed");
        var versionRoot = Path.Combine(installRoot, "versions", "2.3.3");
        Directory.CreateDirectory(versionRoot);
        var current = Path.Combine(versionRoot, "Lattice.exe");
        var mirror = Path.Combine(root, "Desktop", "Lattice.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(mirror)!);
        File.WriteAllBytes(current, Encoding.UTF8.GetBytes("verified-current"));
        File.WriteAllBytes(mirror, Encoding.UTF8.GetBytes("verified-current"));
        var installation = new UpdateInstallation(
            installRoot,
            Path.Combine(installRoot, "versions"),
            versionRoot,
            StableSemanticVersion.Parse("2.3.3"));

        Equal(
            Path.GetFullPath(mirror),
            PortableLauncherMaintenance.ResolveMirrorForUpdate(
                installation,
                mirror,
                current));
        File.WriteAllBytes(mirror, Encoding.UTF8.GetBytes("different-copy"));
        Equal<string?>(
            null,
            PortableLauncherMaintenance.ResolveMirrorForUpdate(
                installation,
                mirror,
                current));
    });
}

static void ReplacesVerifiedPortableLauncher()
{
    WithTemporaryRoot(root =>
    {
        var installRoot = Path.Combine(root, "installed");
        var versionRoot = Path.Combine(installRoot, "versions", "2.3.3");
        Directory.CreateDirectory(versionRoot);
        var source = Path.Combine(versionRoot, "Lattice.exe");
        var target = Path.Combine(root, "Desktop", "Lattice.exe");
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        File.WriteAllBytes(source, Encoding.UTF8.GetBytes("new-version"));
        File.WriteAllBytes(target, Encoding.UTF8.GetBytes("old-version"));
        var expected = PortableLauncherMaintenance.ComputeSha256(target);

        PortableUpdateReplacement.ReplaceVerifiedExecutable(
            source,
            target,
            expected,
            installRoot);
        Equal("new-version", File.ReadAllText(target));
        if (Directory.EnumerateFiles(Path.GetDirectoryName(target)!, ".Lattice-update-*").Any())
            throw new Exception("Portable replacement left an operation file after success.");

        File.WriteAllBytes(target, Encoding.UTF8.GetBytes("old-version"));
        expected = PortableLauncherMaintenance.ComputeSha256(target);
        File.WriteAllBytes(target, Encoding.UTF8.GetBytes("changed-after-start"));
        Throws<InvalidDataException>(() => PortableUpdateReplacement.ReplaceVerifiedExecutable(
            source,
            target,
            expected,
            installRoot));
        Equal("changed-after-start", File.ReadAllText(target));
    });
}

static byte[] BuildManifest(string version, string? assetUrl = null)
{
    assetUrl ??=
        $"https://github.com/dreichner2/Lattice/releases/download/v{version}/Lattice-Windows-win-x64.zip";
    return JsonSerializer.SerializeToUtf8Bytes(new
    {
        schemaVersion = 2,
        repository = UpdateSecurity.Repository,
        releaseVersion = version,
        releaseTag = $"v{version}",
        publishedAt = "2026-08-21T12:00:00Z",
        assets = new Dictionary<string, object>
        {
            [UpdateSecurity.Platform] = new
            {
                url = assetUrl,
                sha256 = new string('a', 64),
                size = 12345,
            },
        },
    });
}

static byte[] Sign(RSA key, byte[] bytes) => key.SignData(
    bytes,
    HashAlgorithmName.SHA256,
    RSASignaturePadding.Pkcs1);

static void AddEntry(ZipArchive archive, string path, string value)
{
    var entry = archive.CreateEntry(path);
    using var writer = new StreamWriter(entry.Open(), Encoding.UTF8);
    writer.Write(value);
}

static void BuildPackageDirectory(string root, string version, bool includeStorageHelper = true)
{
    var packageFiles = new List<string>
    {
        "Lattice.exe",
        "Lattice.ico",
        "Server/LatticeServer.exe",
        "ui/index.html",
        "ui/app.js",
        "ui/tutor.js",
        "ui/tutor-styles.css",
        "ui/reader-desk.css",
        "ui/reader-desk.js",
        "ui/audio-player.css",
        "ui/audio-player.js",
        "ui/study-lab.html",
        "ui/study-lab.css",
        "ui/study-lab.js",
        "ui/vendor/katex/LICENSE",
        "ui/vendor/katex/README-LATTICE.md",
        "ui/vendor/katex/katex.min.css",
        "ui/vendor/katex/katex.min.js",
        "ui/vendor/katex/fonts/KaTeX_Main-Regular.woff2",
    };
    if (includeStorageHelper) packageFiles.Add("Tools/LatticeStorage.exe");
    foreach (var relative in packageFiles)
    {
        var path = Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar));
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllText(path, relative);
    }
    File.WriteAllText(Path.Combine(root, "update-package.json"), JsonSerializer.Serialize(new
    {
        schemaVersion = 1,
        repository = UpdateSecurity.Repository,
        platform = UpdateSecurity.Platform,
        version,
    }));
    var files = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
        .Select(path => new
        {
            path = Path.GetRelativePath(root, path).Replace(Path.DirectorySeparatorChar, '/'),
            sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant(),
            size = new FileInfo(path).Length,
        })
        .OrderBy(file => file.path, StringComparer.Ordinal)
        .ToArray();
    File.WriteAllText(Path.Combine(root, "update-files.json"), JsonSerializer.Serialize(new
    {
        schemaVersion = 1,
        files,
    }));
}

static void WithTemporaryRoot(Action<string> action)
{
    var root = Path.Combine(Path.GetTempPath(), $"lattice-updater-{Guid.NewGuid():N}");
    Directory.CreateDirectory(root);
    try { action(root); }
    finally { Directory.Delete(root, recursive: true); }
}

static T Throws<T>(Action action) where T : Exception
{
    try { action(); }
    catch (T error) { return error; }
    throw new Exception($"Expected {typeof(T).Name}.");
}

static void Equal<T>(T expected, T actual)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
        throw new Exception($"Expected {expected}, got {actual}.");
}
