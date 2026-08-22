using System.Text.Json.Serialization;

namespace CSLibrary.Windows;

internal sealed class GitHubBranchCommit
{
    [JsonPropertyName("sha")]
    public string Sha { get; init; } = "";
}

internal sealed class DesktopUpdateAsset
{
    [JsonPropertyName("url")]
    public Uri? Url { get; init; }

    [JsonPropertyName("sha256")]
    public string Sha256 { get; init; } = "";

    [JsonPropertyName("size")]
    public long Size { get; init; }
}

internal sealed class DesktopUpdateManifest
{
    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; }

    [JsonPropertyName("repository")]
    public string Repository { get; init; } = "";

    [JsonPropertyName("channel")]
    public string Channel { get; init; } = "";

    [JsonPropertyName("commit")]
    public string Commit { get; init; } = "";

    [JsonPropertyName("publishedAt")]
    public string PublishedAt { get; init; } = "";

    [JsonPropertyName("assets")]
    public Dictionary<string, DesktopUpdateAsset> Assets { get; init; } = [];
}

internal sealed class PackageBuildInfo
{
    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; }

    [JsonPropertyName("repository")]
    public string Repository { get; init; } = "";

    [JsonPropertyName("channel")]
    public string Channel { get; init; } = "";

    [JsonPropertyName("commit")]
    public string Commit { get; init; } = "";
}

internal sealed class PackageFileManifest
{
    [JsonPropertyName("schemaVersion")]
    public int SchemaVersion { get; init; }

    [JsonPropertyName("files")]
    public List<string> Files { get; init; } = [];
}

internal enum DesktopUpdateState
{
    Current,
    Available,
    Preparing,
}

internal sealed record DesktopUpdateCheck(
    DesktopUpdateState State,
    string InstalledCommit,
    string LatestCommit,
    DesktopUpdateAsset? Asset = null);

internal sealed class PendingUpdateCleanup
{
    [JsonPropertyName("commit")]
    public string Commit { get; init; } = "";

    [JsonPropertyName("backupPath")]
    public string BackupPath { get; init; } = "";

    [JsonPropertyName("stagingPath")]
    public string StagingPath { get; init; } = "";
}
