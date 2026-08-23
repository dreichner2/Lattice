using System.IO;
using System.Text.Json;

namespace CSLibrary.Windows;

internal sealed record ExternalLibraryVolumeState(
    int SchemaVersion,
    string OriginalLibraryRoot,
    string VolumeName,
    string RelativeLibraryPath,
    string DeviceInstanceId,
    bool SyncthingManaged);

internal static class ExternalLibraryVolumeRecord
{
    private const int MaximumRecordBytes = 16 * 1024;
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };

    internal static void Save(
        string recordPath,
        NativeEjectTarget target,
        bool syncthingManaged)
    {
        var path = Path.GetFullPath(recordPath);
        var parent = Path.GetDirectoryName(path)
            ?? throw new InvalidOperationException("The reconnect record has no local folder.");
        Directory.CreateDirectory(parent);
        RejectReparsePoint(path);
        var state = new ExternalLibraryVolumeState(
            1,
            target.LibraryRoot,
            target.VolumeName,
            target.RelativeLibraryPath,
            target.DeviceInstanceId,
            syncthingManaged);
        Validate(state);

        var payload = JsonSerializer.SerializeToUtf8Bytes(state, JsonOptions);
        if (payload.Length > MaximumRecordBytes)
            throw new InvalidDataException("The reconnect record is unexpectedly large.");
        var temporary = Path.Combine(parent, $".{Path.GetFileName(path)}.{Guid.NewGuid():N}.tmp");
        try
        {
            using (var output = new FileStream(
                       temporary,
                       FileMode.CreateNew,
                       FileAccess.Write,
                       FileShare.None,
                       4096,
                       FileOptions.WriteThrough))
            {
                output.Write(payload);
                output.WriteByte((byte)'\n');
                output.Flush(flushToDisk: true);
            }
            File.Move(temporary, path, overwrite: true);
        }
        finally
        {
            try
            {
                File.Delete(temporary);
            }
            catch (IOException)
            {
                // The atomic move already consumed the temporary file.
            }
        }
    }

    internal static ExternalLibraryVolumeState? Read(string recordPath)
    {
        var path = Path.GetFullPath(recordPath);
        if (!File.Exists(path)) return null;
        RejectReparsePoint(path);
        var details = new FileInfo(path);
        if (details.Length <= 0 || details.Length > MaximumRecordBytes)
            throw new InvalidDataException("The external-library reconnect record has an unsafe size.");
        var state = JsonSerializer.Deserialize<ExternalLibraryVolumeState>(
            File.ReadAllBytes(path),
            JsonOptions)
            ?? throw new InvalidDataException("The external-library reconnect record is empty.");
        Validate(state);
        return state;
    }

    internal static bool TryResolveLibraryRoot(
        ExternalLibraryVolumeState state,
        out string libraryRoot)
    {
        Validate(state);
        foreach (var driveRoot in Directory.GetLogicalDrives())
        {
            string volumeName;
            try
            {
                volumeName = NativeDriveEjector.GetVolumeName(driveRoot);
            }
            catch (Exception error) when (error is IOException
                                          or UnauthorizedAccessException
                                          or System.ComponentModel.Win32Exception)
            {
                continue;
            }
            if (!string.Equals(volumeName, state.VolumeName, StringComparison.OrdinalIgnoreCase))
                continue;
            var candidate = state.RelativeLibraryPath == "."
                ? driveRoot
                : Path.Combine(driveRoot, state.RelativeLibraryPath);
            libraryRoot = Path.GetFullPath(candidate);
            return true;
        }
        libraryRoot = string.Empty;
        return false;
    }

    internal static bool IsSafeRelativePath(string value)
    {
        if (string.IsNullOrWhiteSpace(value) || Path.IsPathRooted(value)) return false;
        if (value == ".") return true;
        return value
            .Split(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            .All(component => component.Length > 0 && component is not "." and not "..");
    }

    internal static void Delete(string recordPath)
    {
        var path = Path.GetFullPath(recordPath);
        RejectReparsePoint(path);
        File.Delete(path);
    }

    private static void Validate(ExternalLibraryVolumeState state)
    {
        if (state.SchemaVersion != 1
            || string.IsNullOrWhiteSpace(state.OriginalLibraryRoot)
            || state.OriginalLibraryRoot.Length > 4096
            || string.IsNullOrWhiteSpace(state.VolumeName)
            || state.VolumeName.Length > 512
            || !state.VolumeName.StartsWith(@"\\?\Volume{", StringComparison.OrdinalIgnoreCase)
            || !state.VolumeName.EndsWith(@"}\", StringComparison.Ordinal)
            || !IsSafeRelativePath(state.RelativeLibraryPath)
            || string.IsNullOrWhiteSpace(state.DeviceInstanceId)
            || state.DeviceInstanceId.Length > 4096
            || !state.DeviceInstanceId.StartsWith("USB\\", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("The external-library reconnect record is invalid.");
        }
    }

    private static void RejectReparsePoint(string path)
    {
        if (!File.Exists(path)) return;
        if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidDataException("The external-library reconnect record is unsafe.");
    }
}
