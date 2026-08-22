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

internal sealed record LibraryDisconnectOutcome(
    bool SyncthingManaged,
    bool SyncthingRunning,
    bool PausedByLattice,
    bool SyncthingStopped);

internal sealed record LibraryReconnectOutcome(
    bool SyncthingManaged,
    bool SyncthingRunning,
    bool SyncthingStarted,
    bool ResumedByLattice);

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
        var completed = await RunStorageHelperAsync(
            "move", source, destination, stateFile: null, startIfNeeded: false, progress: progress);
        var completedDestination = RequiredString(completed, "destination");
        if (!string.Equals(
                Path.TrimEndingDirectorySeparator(Path.GetFullPath(completedDestination)),
                Path.TrimEndingDirectorySeparator(destination),
                StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("The storage helper reported an unexpected destination.");
        return new LibraryMoveOutcome(
            Path.GetFullPath(completedDestination),
            RequiredBoolean(completed, "sourceRemoved"),
            RequiredBoolean(completed, "syncthingManaged"),
            completed.TryGetProperty("warning", out var warningValue)
                && warningValue.ValueKind == JsonValueKind.String
                    ? warningValue.GetString()
                    : null);
    }

    internal static async Task<LibraryDisconnectOutcome> DisconnectAsync(
        string source,
        string stateFile,
        IProgress<LibraryMoveProgress>? progress = null)
    {
        var completed = await RunStorageHelperAsync(
            "disconnect",
            Path.GetFullPath(source),
            destination: null,
            stateFile: Path.GetFullPath(stateFile),
            startIfNeeded: false,
            progress: progress);
        return new LibraryDisconnectOutcome(
            RequiredBoolean(completed, "syncthingManaged"),
            RequiredBoolean(completed, "syncthingRunning"),
            RequiredBoolean(completed, "pausedByLattice"),
            RequiredBoolean(completed, "syncthingStopped"));
    }

    internal static async Task<LibraryReconnectOutcome> ReconnectAsync(
        string source,
        string stateFile,
        bool startIfNeeded,
        IProgress<LibraryMoveProgress>? progress = null)
    {
        var completed = await RunStorageHelperAsync(
            "reconnect",
            Path.GetFullPath(source),
            destination: null,
            stateFile: Path.GetFullPath(stateFile),
            startIfNeeded: startIfNeeded,
            progress: progress);
        return new LibraryReconnectOutcome(
            RequiredBoolean(completed, "syncthingManaged"),
            RequiredBoolean(completed, "syncthingRunning"),
            RequiredBoolean(completed, "syncthingStarted"),
            RequiredBoolean(completed, "resumedByLattice"));
    }

    private static async Task<JsonElement> RunStorageHelperAsync(
        string operation,
        string source,
        string? destination,
        string? stateFile,
        bool startIfNeeded,
        IProgress<LibraryMoveProgress>? progress)
    {
        var start = CreateStartInfo(operation, source, destination, stateFile, startIfNeeded);
        using var process = new Process { StartInfo = start };
        if (!process.Start())
            throw new InvalidOperationException("The Lattice storage helper did not start.");

        var standardError = process.StandardError.ReadToEndAsync();
        JsonElement? completion = null;
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
                if (!root.TryGetProperty("operation", out var operationValue)
                    || operationValue.ValueKind != JsonValueKind.String
                    || !string.Equals(operationValue.GetString(), operation, StringComparison.Ordinal))
                    throw new InvalidDataException("The storage helper completed an unexpected operation.");
                completion = root.Clone();
            }
        }

        await process.WaitForExitAsync();
        var errorDetail = await standardError;
        if (process.ExitCode != 0 || completion is null)
        {
            var detail = !string.IsNullOrWhiteSpace(reportedError)
                ? reportedError
                : Truncate(errorDetail.Trim(), MaximumMessageLength);
            throw new InvalidOperationException(
                string.IsNullOrWhiteSpace(detail)
                    ? $"The library storage operation stopped with exit code {process.ExitCode}."
                    : detail);
        }
        return completion.Value;
    }

    private static ProcessStartInfo CreateStartInfo(
        string operation,
        string source,
        string? destination,
        string? stateFile,
        bool startIfNeeded)
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
        var workingPath = destination is not null
            ? Path.GetDirectoryName(destination)
            : Path.GetDirectoryName(stateFile!);
        if (string.IsNullOrWhiteSpace(workingPath))
            throw new InvalidOperationException("The storage operation has no safe working folder.");
        Directory.CreateDirectory(workingPath);
        start.WorkingDirectory = workingPath;
        start.ArgumentList.Add("--operation");
        start.ArgumentList.Add(operation);
        start.ArgumentList.Add("--source");
        start.ArgumentList.Add(source);
        if (destination is not null)
        {
            start.ArgumentList.Add("--destination");
            start.ArgumentList.Add(destination);
        }
        if (stateFile is not null)
        {
            start.ArgumentList.Add("--state-file");
            start.ArgumentList.Add(stateFile);
        }
        if (startIfNeeded) start.ArgumentList.Add("--start-if-needed");
        if (string.Equals(operation, "disconnect", StringComparison.Ordinal))
            start.ArgumentList.Add("--shutdown-syncthing");
        start.ArgumentList.Add("--folder-id");
        start.ArgumentList.Add(FolderId);
        start.ArgumentList.Add("--protected-path");
        start.ArgumentList.Add(AppContext.BaseDirectory);
        return start;
    }

    private static string RequiredString(JsonElement value, string name) =>
        value.TryGetProperty(name, out var property) && property.ValueKind == JsonValueKind.String
            ? property.GetString()!
            : throw new InvalidDataException($"The storage helper omitted {name}.");

    private static bool RequiredBoolean(JsonElement value, string name) =>
        value.TryGetProperty(name, out var property)
            && property.ValueKind is JsonValueKind.True or JsonValueKind.False
                ? property.GetBoolean()
                : throw new InvalidDataException($"The storage helper omitted {name}.");

    private static string Truncate(string value, int maximum) =>
        value.Length <= maximum ? value : value[..maximum];
}
