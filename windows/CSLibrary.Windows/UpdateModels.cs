using System.IO;
using System.Text.Json.Serialization;

namespace CSLibrary.Windows;

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class DesktopUpdateAsset
{
    [JsonPropertyName("url")]
    public string Url { get; init; } = "";

    [JsonPropertyName("sha256")]
    public string Sha256 { get; init; } = "";

    [JsonPropertyName("size")]
    public long Size { get; init; }
}

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class DesktopUpdateManifest
{
    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; }

    [JsonPropertyName("repository")]
    public string Repository { get; init; } = "";

    [JsonPropertyName("releaseVersion")]
    public string ReleaseVersion { get; init; } = "";

    [JsonPropertyName("releaseTag")]
    public string ReleaseTag { get; init; } = "";

    [JsonPropertyName("publishedAt")]
    public string PublishedAt { get; init; } = "";

    [JsonPropertyName("assets")]
    public Dictionary<string, DesktopUpdateAsset> Assets { get; init; } = [];
}

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class UpdatePackageMetadata
{
    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; }

    [JsonPropertyName("repository")]
    public string Repository { get; init; } = "";

    [JsonPropertyName("platform")]
    public string Platform { get; init; } = "";

    [JsonPropertyName("version")]
    public string Version { get; init; } = "";
}

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class UpdatePackageFileManifest
{
    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; }

    [JsonPropertyName("files")]
    public List<UpdatePackageFile> Files { get; init; } = [];
}

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class UpdatePackageFile
{
    [JsonPropertyName("path")]
    public string Path { get; init; } = "";

    [JsonPropertyName("sha256")]
    public string Sha256 { get; init; } = "";

    [JsonPropertyName("size")]
    public long Size { get; init; }
}

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class PendingUpdateActivation
{
    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; }

    [JsonPropertyName("activationId")]
    public string ActivationId { get; init; } = "";

    [JsonPropertyName("tokenSha256")]
    public string TokenSha256 { get; init; } = "";

    [JsonPropertyName("createdAt")]
    public string CreatedAt { get; init; } = "";

    [JsonPropertyName("previousVersion")]
    public string PreviousVersion { get; init; } = "";

    [JsonPropertyName("candidateVersion")]
    public string CandidateVersion { get; init; } = "";

    [JsonPropertyName("candidateDirectory")]
    public string CandidateDirectory { get; init; } = "";

    [JsonPropertyName("launcherProcessId")]
    public int? LauncherProcessId { get; init; }

    [JsonPropertyName("launcherProcessStartTimeUtcTicks")]
    public long? LauncherProcessStartTimeUtcTicks { get; init; }

    [JsonPropertyName("launcherExecutablePath")]
    public string? LauncherExecutablePath { get; init; }

    [JsonPropertyName("launcherMirrorPath")]
    public string? LauncherMirrorPath { get; init; }

    [JsonPropertyName("launcherMirrorSha256")]
    public string? LauncherMirrorSha256 { get; init; }
}

[JsonUnmappedMemberHandling(JsonUnmappedMemberHandling.Disallow)]
internal sealed class ActiveVersionRecord
{
    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; }

    [JsonPropertyName("version")]
    public string Version { get; init; } = "";

    [JsonPropertyName("previousVersion")]
    public string? PreviousVersion { get; init; }

    [JsonPropertyName("promotedAt")]
    public string PromotedAt { get; init; } = "";
}

internal enum DesktopUpdateState
{
    NotInstalled,
    Current,
    Available,
}

internal sealed record DesktopUpdateCheck(
    DesktopUpdateState State,
    string? InstalledVersion,
    string? LatestVersion,
    DesktopUpdateAsset? Asset = null,
    string? Message = null);

internal sealed record StagedDesktopUpdate(
    string Version,
    string VersionDirectory);

internal sealed record ValidatedDesktopRelease(
    StableSemanticVersion Version,
    DesktopUpdateAsset Asset);

internal enum UpdateVersionRejection
{
    SameVersion,
    Downgrade,
}

internal sealed class UpdateVersionRejectedException(
    UpdateVersionRejection reason,
    string message) : IOException(message)
{
    public UpdateVersionRejection Reason { get; } = reason;
}

internal readonly record struct StableSemanticVersion(int Major, int Minor, int Patch)
    : IComparable<StableSemanticVersion>
{
    internal static StableSemanticVersion Parse(string value, string fieldName = "version")
    {
        if (string.IsNullOrWhiteSpace(value) || value.Length > 32)
            throw new InvalidDataException($"The {fieldName} is not a stable semantic version.");
        var pieces = value.Split('.');
        if (pieces.Length != 3)
            throw new InvalidDataException($"The {fieldName} must use major.minor.patch without a prerelease suffix.");

        static int ParsePart(string part, string field)
        {
            if (part.Length == 0
                || (part.Length > 1 && part[0] == '0')
                || !part.All(character => character is >= '0' and <= '9')
                || !int.TryParse(part, out var result))
                throw new InvalidDataException($"The {field} is not a stable semantic version.");
            return result;
        }

        return new StableSemanticVersion(
            ParsePart(pieces[0], fieldName),
            ParsePart(pieces[1], fieldName),
            ParsePart(pieces[2], fieldName));
    }

    public int CompareTo(StableSemanticVersion other)
    {
        var major = Major.CompareTo(other.Major);
        if (major != 0) return major;
        var minor = Minor.CompareTo(other.Minor);
        return minor != 0 ? minor : Patch.CompareTo(other.Patch);
    }

    public override string ToString() => $"{Major}.{Minor}.{Patch}";
}
