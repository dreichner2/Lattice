using System.Diagnostics;
using System.IO;
using System.Text.Json;

namespace CSLibrary.Windows;

internal sealed record LibraryMoveProgress(string Message, int? Percent);

internal sealed record LibraryMoveOutcome(
    string Destination,
    bool SourceRemoved,
    bool SyncthingManaged,
    string? Warning);

internal static class LibraryMoveClient
{
    private const string FolderId = "cs-library-3b8290f24f15";
    private const int MaximumMessageLength = 64 * 1024;

    internal static string DestinationForContainer(string container) =>
        Path.Combine(Path.GetFullPath(container), "Lattice");

    internal static async Task<LibraryMoveOutcome> MoveAsync(
        string source,
        string destination,
        IProgress<LibraryMoveProgress>? progress = null)
    {
        source = Path.GetFullPath(source);
        destination = Path.GetFullPath(destination);
        var start = CreateStartInfo(source, destination);
        using var process = new Process { StartInfo = start };
        if (!process.Start())
            throw new InvalidOperationException("The Lattice storage helper did not start.");

        var standardError = process.StandardError.ReadToEndAsync();
        LibraryMoveOutcome? outcome = null;
        string? reportedError = null;
        while (await process.StandardOutput.ReadLineAsync() is { } line)
        {
            if (line.Length == 0) continue;
            if (line.Length > MaximumMessageLength)
                throw new InvalidDataException("The Lattice storage helper returned an oversized message.");
            using var document = JsonDocument.Parse(line, new JsonDocumentOptions
            {
                AllowTrailingCommas = false,
                CommentHandling = JsonCommentHandling.Disallow,
                MaxDepth = 8,
            });
            var root = document.RootElement;
            if (!root.TryGetProperty("event", out var eventValue)
                || eventValue.ValueKind != JsonValueKind.String) continue;
            var eventName = eventValue.GetString();
            var message = root.TryGetProperty("message", out var messageValue)
                && messageValue.ValueKind == JsonValueKind.String
                    ? messageValue.GetString()
                    : null;
            int? percent = root.TryGetProperty("percent", out var percentValue)
                && percentValue.TryGetInt32(out var parsedPercent)
                    ? Math.Clamp(parsedPercent, 0, 100)
                    : null;
            if (!string.IsNullOrWhiteSpace(message))
                progress?.Report(new LibraryMoveProgress(message!, percent));

            if (string.Equals(eventName, "error", StringComparison.Ordinal))
            {
                reportedError = message;
            }
            else if (string.Equals(eventName, "complete", StringComparison.Ordinal))
            {
                var completedDestination = root.GetProperty("destination").GetString()
                    ?? throw new InvalidDataException("The completed move has no destination.");
                if (!string.Equals(
                        Path.TrimEndingDirectorySeparator(Path.GetFullPath(completedDestination)),
                        Path.TrimEndingDirectorySeparator(destination),
                        StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("The storage helper reported an unexpected destination.");
                outcome = new LibraryMoveOutcome(
                    Path.GetFullPath(completedDestination),
                    root.GetProperty("sourceRemoved").GetBoolean(),
                    root.GetProperty("syncthingManaged").GetBoolean(),
                    root.TryGetProperty("warning", out var warningValue)
                        && warningValue.ValueKind == JsonValueKind.String
                            ? warningValue.GetString()
                            : null);
            }
        }

        await process.WaitForExitAsync();
        var errorDetail = await standardError;
        if (process.ExitCode != 0 || outcome is null)
        {
            var detail = !string.IsNullOrWhiteSpace(reportedError)
                ? reportedError
                : Truncate(errorDetail.Trim(), MaximumMessageLength);
            throw new InvalidOperationException(
                string.IsNullOrWhiteSpace(detail)
                    ? $"The library move stopped with exit code {process.ExitCode}."
                    : detail);
        }
        return outcome;
    }

    private static ProcessStartInfo CreateStartInfo(string source, string destination)
    {
        var packagedHelper = Path.Combine(AppContext.BaseDirectory, "Tools", "LatticeStorage.exe");
        ProcessStartInfo start;
        if (File.Exists(packagedHelper))
        {
            start = new ProcessStartInfo(packagedHelper);
        }
        else
        {
            var developmentScript = Path.Combine(source, "scripts", "move_library.py");
            if (!File.Exists(developmentScript))
                throw new FileNotFoundException(
                    "The Lattice storage helper is missing. Reinstall the complete Windows package.",
                    packagedHelper);
            start = new ProcessStartInfo("python");
            start.ArgumentList.Add(developmentScript);
        }
        start.UseShellExecute = false;
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        start.CreateNoWindow = true;
        start.WorkingDirectory = Path.GetDirectoryName(destination)
            ?? throw new InvalidOperationException("The destination has no parent folder.");
        start.ArgumentList.Add("--source");
        start.ArgumentList.Add(source);
        start.ArgumentList.Add("--destination");
        start.ArgumentList.Add(destination);
        start.ArgumentList.Add("--folder-id");
        start.ArgumentList.Add(FolderId);
        start.ArgumentList.Add("--protected-path");
        start.ArgumentList.Add(AppContext.BaseDirectory);
        return start;
    }

    private static string Truncate(string value, int maximum) =>
        value.Length <= maximum ? value : value[..maximum];
}
