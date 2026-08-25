using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace CSLibrary.Windows;

internal sealed record EjectProcessIdentity(
    int ProcessId,
    long StartTimeUtcTicks)
{
    internal string Encode() =>
        $"{ProcessId.ToString(CultureInfo.InvariantCulture)}:{StartTimeUtcTicks.ToString(CultureInfo.InvariantCulture)}";

    internal static EjectProcessIdentity Parse(string value)
    {
        var separator = value.IndexOf(':');
        if (separator <= 0 || separator == value.Length - 1)
            throw new ArgumentException("A tracked eject process identity is invalid.");
        if (!int.TryParse(
                value.AsSpan(0, separator),
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out var processId)
            || processId <= 0
            || !long.TryParse(
                value.AsSpan(separator + 1),
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out var startTimeUtcTicks)
            || startTimeUtcTicks <= 0)
        {
            throw new ArgumentException("A tracked eject process identity is invalid.");
        }
        return new EjectProcessIdentity(processId, startTimeUtcTicks);
    }
}

internal sealed record EjectHelperOptions(
    int ParentProcessId,
    long ParentStartTimeUtcTicks,
    string DeviceInstanceId,
    string DriveRoot,
    IReadOnlyList<EjectProcessIdentity> WaitProcesses)
{
    private const string HelperSwitch = "--eject-helper";
    private const string WaitProcessOption = "--wait-process";
    private const int MaximumWaitProcesses = 64;

    internal static bool IsRequested(IReadOnlyList<string> arguments) =>
        arguments.Contains(HelperSwitch, StringComparer.Ordinal);

    internal static EjectHelperOptions Parse(IReadOnlyList<string> arguments)
    {
        if (!IsRequested(arguments))
            throw new ArgumentException("The native eject helper switch is missing.");

        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        var waitProcesses = new List<EjectProcessIdentity>();
        for (var index = 0; index < arguments.Count; index++)
        {
            var argument = arguments[index];
            if (string.Equals(argument, HelperSwitch, StringComparison.Ordinal)) continue;
            if (string.Equals(argument, WaitProcessOption, StringComparison.Ordinal))
            {
                if (index + 1 >= arguments.Count || arguments[index + 1].StartsWith("--", StringComparison.Ordinal))
                    throw new ArgumentException($"{WaitProcessOption} requires a value.");
                if (waitProcesses.Count >= MaximumWaitProcesses)
                    throw new ArgumentException("The native eject helper received too many tracked processes.");
                waitProcesses.Add(EjectProcessIdentity.Parse(arguments[++index]));
                continue;
            }
            if (argument is not ("--parent-pid"
                or "--parent-start-time-utc-ticks"
                or "--device-instance-id"
                or "--drive-root"))
            {
                throw new ArgumentException($"Unknown native eject helper option: {argument}");
            }
            if (values.ContainsKey(argument))
                throw new ArgumentException($"Duplicate native eject helper option: {argument}");
            if (index + 1 >= arguments.Count || arguments[index + 1].StartsWith("--", StringComparison.Ordinal))
                throw new ArgumentException($"{argument} requires a value.");
            values[argument] = arguments[++index];
        }

        var parentProcessId = ParsePositiveInt(values, "--parent-pid");
        var parentStartTimeUtcTicks = ParsePositiveLong(values, "--parent-start-time-utc-ticks");
        var deviceInstanceId = Required(values, "--device-instance-id");
        if (!deviceInstanceId.StartsWith("USB\\", StringComparison.OrdinalIgnoreCase)
            || deviceInstanceId.StartsWith("USB\\ROOT_HUB", StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException("The native eject helper target is not a removable USB device.");
        }

        var driveRoot = Path.GetFullPath(Required(values, "--drive-root"));
        if (driveRoot.Length != 3
            || !char.IsAsciiLetter(driveRoot[0])
            || driveRoot[1] != ':'
            || driveRoot[2] != Path.DirectorySeparatorChar)
        {
            throw new ArgumentException("The native eject helper requires a drive-letter root.");
        }
        if (waitProcesses.Any(process => process.ProcessId == parentProcessId)
            || waitProcesses.Select(process => process.ProcessId).Distinct().Count() != waitProcesses.Count)
        {
            throw new ArgumentException("The native eject helper received duplicate tracked processes.");
        }

        return new EjectHelperOptions(
            parentProcessId,
            parentStartTimeUtcTicks,
            deviceInstanceId,
            driveRoot,
            waitProcesses.ToArray());
    }

    internal static EjectHelperOptions ForCurrentProcess(
        NativeEjectTarget target,
        IReadOnlyList<EjectProcessIdentity> waitProcesses)
    {
        using var parent = Process.GetCurrentProcess();
        return new EjectHelperOptions(
            Environment.ProcessId,
            parent.StartTime.ToUniversalTime().Ticks,
            target.DeviceInstanceId,
            target.DriveRoot,
            waitProcesses);
    }

    internal void AddArguments(ProcessStartInfo start)
    {
        start.ArgumentList.Add(HelperSwitch);
        AddValue(start, "--parent-pid", ParentProcessId.ToString(CultureInfo.InvariantCulture));
        AddValue(
            start,
            "--parent-start-time-utc-ticks",
            ParentStartTimeUtcTicks.ToString(CultureInfo.InvariantCulture));
        AddValue(start, "--device-instance-id", DeviceInstanceId);
        AddValue(start, "--drive-root", DriveRoot);
        foreach (var process in WaitProcesses)
            AddValue(start, WaitProcessOption, process.Encode());
    }

    private static void AddValue(ProcessStartInfo start, string option, string value)
    {
        start.ArgumentList.Add(option);
        start.ArgumentList.Add(value);
    }

    private static string Required(IReadOnlyDictionary<string, string> values, string option) =>
        values.TryGetValue(option, out var value) && !string.IsNullOrWhiteSpace(value)
            ? value
            : throw new ArgumentException($"{option} requires a value.");

    private static int ParsePositiveInt(IReadOnlyDictionary<string, string> values, string option) =>
        int.TryParse(Required(values, option), NumberStyles.None, CultureInfo.InvariantCulture, out var value)
        && value > 0
            ? value
            : throw new ArgumentException($"{option} must be a positive integer.");

    private static long ParsePositiveLong(IReadOnlyDictionary<string, string> values, string option) =>
        long.TryParse(Required(values, option), NumberStyles.None, CultureInfo.InvariantCulture, out var value)
        && value > 0
            ? value
            : throw new ArgumentException($"{option} must be a positive integer.");

}

internal sealed class EjectHelperWindow : Window
{
    private const int MaximumEjectAttempts = 4;
    private static readonly TimeSpan TrackedProcessExitTimeout = TimeSpan.FromSeconds(45);
    private static readonly TimeSpan ExplorerWindowExitTimeout = TimeSpan.FromSeconds(45);
    private static readonly TimeSpan HandleDrainDelay = TimeSpan.FromSeconds(2);
    private static readonly TimeSpan RetryDelay = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan ProcessPollDelay = TimeSpan.FromMilliseconds(150);
    private static readonly TimeSpan ExplorerWindowPollDelay = TimeSpan.FromMilliseconds(500);
    private static readonly string DiagnosticPath = Path.Combine(
        MainWindow.LocalSettingsRoot,
        "last-eject-diagnostic.txt");

    private readonly EjectHelperOptions _options;
    private readonly TextBlock _heading;
    private readonly TextBlock _detail;
    private readonly ProgressBar _progress;
    private bool _finished;

    internal EjectHelperWindow(EjectHelperOptions options)
    {
        _options = options;
        Title = "Ejecting library drive";
        Width = 470;
        Height = 245;
        MinWidth = 470;
        MinHeight = 245;
        ResizeMode = ResizeMode.NoResize;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        Background = ResourceBrush("LatticeCanvasBrush", Brushes.WhiteSmoke);
        Icon = Application.Current.TryFindResource("LatticeIcon") as ImageSource;

        _heading = new TextBlock
        {
            Text = "Ejecting…",
            FontFamily = ResourceFont("LatticeDisplayFont", new FontFamily("Georgia")),
            FontSize = 28,
            FontWeight = FontWeights.SemiBold,
            Foreground = ResourceBrush("LatticeInkBrush", Brushes.Black),
        };
        _detail = new TextBlock
        {
            Text = "Closing Lattice completely before asking Windows to eject the drive.",
            Margin = new Thickness(0, 12, 0, 22),
            FontFamily = ResourceFont("LatticeSansFont", new FontFamily("Segoe UI")),
            FontSize = 13,
            Foreground = ResourceBrush("LatticeMutedBrush", Brushes.DimGray),
            TextWrapping = TextWrapping.Wrap,
        };
        _progress = new ProgressBar
        {
            Height = 5,
            IsIndeterminate = true,
            Foreground = ResourceBrush("LatticeAccentBrush", Brushes.RoyalBlue),
            Background = ResourceBrush("LatticeAccentSoftBrush", Brushes.Lavender),
        };

        Content = new Border
        {
            Margin = new Thickness(18),
            Padding = new Thickness(28),
            CornerRadius = new CornerRadius(18),
            Background = ResourceBrush("LatticePanelBrush", Brushes.White),
            BorderBrush = ResourceBrush("LatticeLineBrush", Brushes.LightGray),
            BorderThickness = new Thickness(1),
            Child = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center,
                Children = { _heading, _detail, _progress },
            },
        };

        Loaded += EjectHelperWindow_Loaded;
        Closing += (_, eventArgs) =>
        {
            if (!_finished) eventArgs.Cancel = true;
        };
    }

    private async void EjectHelperWindow_Loaded(object sender, RoutedEventArgs e)
    {
        var elapsed = Stopwatch.StartNew();
        var diagnostic = new List<string>
        {
            $"StartedUtc={DateTime.UtcNow:O}",
            $"DriveRoot={_options.DriveRoot}",
            $"DeviceInstanceId={_options.DeviceInstanceId}",
            $"ParentProcessId={_options.ParentProcessId}",
            $"TrackedWebViewProcessCount={_options.WaitProcesses.Count}",
            $"TrackedWebViewProcessIds={string.Join(',', _options.WaitProcesses.Select(process => process.ProcessId))}",
        };
        try
        {
            _detail.Text = "Waiting for Lattice and its WebView processes to close completely…";
            var trackedProcessCount = await WaitForTrackedProcessesExitAsync(_options);
            diagnostic.Add($"TrackedProcessTreeExitedMilliseconds={elapsed.Elapsed.TotalMilliseconds:F3}");
            diagnostic.Add($"TrackedProcessCount={trackedProcessCount}");
            await WaitForExplorerWindowsToReleaseAsync(_options.DriveRoot, diagnostic, elapsed);
            _detail.Text = "Every tracked Lattice process is closed. Waiting for final Windows handles to clear…";
            await Task.Delay(HandleDrainDelay);
            diagnostic.Add($"HandleDrainCompleteMilliseconds={elapsed.Elapsed.TotalMilliseconds:F3}");

            NativeEjectResult? result = null;
            var attemptsMade = 0;
            for (var attempt = 1; attempt <= MaximumEjectAttempts; attempt++)
            {
                attemptsMade = attempt;
                _detail.Text = attempt == 1
                    ? $"Asking Windows to safely eject {_options.DriveRoot}…"
                    : $"Windows is still closing a handle. Retrying safe eject ({attempt}/{MaximumEjectAttempts})…";
                result = await Task.Run(() => NativeDriveEjector.RequestEject(
                    _options.DeviceInstanceId));
                diagnostic.Add(
                    $"Attempt={attempt} ElapsedMilliseconds={elapsed.Elapsed.TotalMilliseconds:F3} "
                    + $"ConfigurationManagerResult=0x{result.ConfigurationManagerResult:X8} "
                    + $"VetoType={result.VetoType} VetoName={result.VetoName}");
                if (result.Success) break;
                if (!NativeDriveEjector.IsTransientCloseVeto(result)
                    || attempt == MaximumEjectAttempts) break;
                _detail.Text = $"Windows still has a closing volume handle. Waiting 30 seconds before "
                    + $"the next safe-eject request ({attempt + 1}/{MaximumEjectAttempts})…";
                diagnostic.Add(
                    $"Attempt={attempt} QuietRetryStartedMilliseconds={elapsed.Elapsed.TotalMilliseconds:F3}");
                await Task.Delay(RetryDelay);
            }

            if (result is null)
                throw new InvalidOperationException("Windows returned no result for the eject request.");
            if (!result.Success)
            {
                diagnostic.Add($"FinishedUtc={DateTime.UtcNow:O}");
                diagnostic.Add("Stage=Vetoed");
                var diagnosticLocation = TryWriteDiagnostic(diagnostic);
                FinishWithFailure(
                    "Windows vetoed the native eject request. The library remains disconnected and the drive "
                    + "was not ejected.\n\n" + result.FailureDetail
                    + $"\nAttempts: {attemptsMade} after every tracked Lattice process exited."
                    + DiagnosticMessage(diagnosticLocation),
                    "Windows blocked eject");
                return;
            }

            diagnostic.Add($"FinishedUtc={DateTime.UtcNow:O}");
            diagnostic.Add("Stage=Ejected");
            TryWriteDiagnostic(diagnostic);
            _heading.Text = "Safe to unplug";
            _detail.Text = "Windows accepted the native eject request and removed the USB storage device.";
            _progress.IsIndeterminate = false;
            _progress.Value = 100;
            MessageBox.Show(
                this,
                "Windows accepted the native eject request and removed the USB storage device.\n\nSafe to unplug.",
                "Safe to unplug",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
        catch (Exception error) when (error is ArgumentException
                                      or InvalidOperationException
                                      or System.ComponentModel.Win32Exception
                                      or TaskCanceledException)
        {
            diagnostic.Add($"FinishedUtc={DateTime.UtcNow:O}");
            diagnostic.Add($"Stage=Failed Error={error.Message}");
            var diagnosticLocation = TryWriteDiagnostic(diagnostic);
            FinishWithFailure(
                "The library remains disconnected and the drive was not ejected.\n\n" + error.Message
                + DiagnosticMessage(diagnosticLocation),
                "Windows eject failed");
            return;
        }

        Finish();
    }

    private void FinishWithFailure(string message, string title)
    {
        _heading.Text = "Drive not ejected";
        _detail.Text = "The library is disconnected. Review the Windows veto before trying again.";
        _progress.IsIndeterminate = false;
        _progress.Value = 0;
        MessageBox.Show(this, message, title, MessageBoxButton.OK, MessageBoxImage.Warning);
        Finish();
    }

    private void Finish()
    {
        _finished = true;
        Close();
    }

    private static async Task<int> WaitForTrackedProcessesExitAsync(EjectHelperOptions options)
    {
        var processes = new List<EjectProcessIdentity>
        {
            new(options.ParentProcessId, options.ParentStartTimeUtcTicks),
        };
        processes.AddRange(options.WaitProcesses);
        if (processes.Any(process => process.ProcessId == Environment.ProcessId))
            throw new InvalidOperationException("The eject helper cannot wait on its own process.");

        var elapsed = Stopwatch.StartNew();
        while (true)
        {
            var remaining = processes
                .Where(IsExactProcessRunning)
                .Select(process => process.ProcessId)
                .ToArray();
            if (remaining.Length == 0) return processes.Count;
            if (elapsed.Elapsed >= TrackedProcessExitTimeout)
            {
                throw new TaskCanceledException(
                    "Lattice or one of its WebView processes did not close within 45 seconds, so Windows "
                    + $"was not asked to eject the drive. Remaining process IDs: {string.Join(", ", remaining)}");
            }
            await Task.Delay(ProcessPollDelay);
        }
    }

    private static bool IsExactProcessRunning(EjectProcessIdentity identity)
    {
        Process process;
        try
        {
            process = Process.GetProcessById(identity.ProcessId);
        }
        catch (ArgumentException)
        {
            return false;
        }

        using (process)
        {
            try
            {
                return !process.HasExited
                    && process.StartTime.ToUniversalTime().Ticks == identity.StartTimeUtcTicks;
            }
            catch (InvalidOperationException)
            {
                return false;
            }
        }
    }

    private async Task WaitForExplorerWindowsToReleaseAsync(
        string driveRoot,
        ICollection<string> diagnostic,
        Stopwatch totalElapsed)
    {
        var locations = FindExplorerLocationsOnDrive(driveRoot);
        if (locations.Count == 0)
        {
            diagnostic.Add("ExplorerWindowCount=0");
            return;
        }

        diagnostic.Add($"ExplorerWindowCount={locations.Count}");
        diagnostic.Add($"ExplorerWindowLocations={string.Join('|', locations)}");
        var elapsed = Stopwatch.StartNew();
        while (locations.Count > 0)
        {
            _detail.Text = $"File Explorer is still using {driveRoot}. Close every Explorer window or tab "
                + "showing this drive; Lattice will continue automatically.";
            if (elapsed.Elapsed >= ExplorerWindowExitTimeout)
            {
                diagnostic.Add($"ExplorerWindowWaitTimedOutMilliseconds={totalElapsed.Elapsed.TotalMilliseconds:F3}");
                throw new TaskCanceledException(
                    $"File Explorer is still open on {driveRoot}. Close every File Explorer window or tab "
                    + "showing this drive, then choose Disconnect library drive again.");
            }
            await Task.Delay(ExplorerWindowPollDelay);
            locations = FindExplorerLocationsOnDrive(driveRoot);
        }
        diagnostic.Add($"ExplorerWindowsReleasedMilliseconds={totalElapsed.Elapsed.TotalMilliseconds:F3}");
    }

    private static IReadOnlyList<string> FindExplorerLocationsOnDrive(string driveRoot)
    {
        var locations = new List<string>();
        object? shell = null;
        object? windows = null;
        try
        {
            var shellType = Type.GetTypeFromProgID("Shell.Application");
            if (shellType is null) return locations;
            shell = Activator.CreateInstance(shellType);
            if (shell is null) return locations;
            windows = shellType.InvokeMember(
                "Windows",
                BindingFlags.InvokeMethod,
                binder: null,
                target: shell,
                args: null,
                culture: CultureInfo.InvariantCulture);
            if (windows is null) return locations;

            var windowsType = windows.GetType();
            var countValue = windowsType.InvokeMember(
                "Count",
                BindingFlags.GetProperty,
                binder: null,
                target: windows,
                args: null,
                culture: CultureInfo.InvariantCulture);
            var count = Convert.ToInt32(countValue, CultureInfo.InvariantCulture);
            for (var index = 0; index < count; index++)
            {
                object? window = null;
                try
                {
                    window = windowsType.InvokeMember(
                        "Item",
                        BindingFlags.InvokeMethod,
                        binder: null,
                        target: windows,
                        args: new object[] { index },
                        culture: CultureInfo.InvariantCulture);
                    if (window is null) continue;
                    var locationUrl = window.GetType().InvokeMember(
                        "LocationURL",
                        BindingFlags.GetProperty,
                        binder: null,
                        target: window,
                        args: null,
                        culture: CultureInfo.InvariantCulture) as string;
                    if (!Uri.TryCreate(locationUrl, UriKind.Absolute, out var uri) || !uri.IsFile) continue;
                    var location = Path.GetFullPath(uri.LocalPath);
                    if (!string.Equals(
                            Path.GetPathRoot(location),
                            driveRoot,
                            StringComparison.OrdinalIgnoreCase)) continue;
                    locations.Add(location);
                }
                catch (Exception error) when (error is COMException
                                              or TargetInvocationException
                                              or InvalidOperationException
                                              or ArgumentException
                                              or UnauthorizedAccessException)
                {
                    // A shell window can disappear while it is being enumerated.
                }
                finally
                {
                    ReleaseComObject(window);
                }
            }
        }
        catch (Exception error) when (error is COMException
                                      or TargetInvocationException
                                      or InvalidOperationException
                                      or ArgumentException
                                      or UnauthorizedAccessException)
        {
            // Explorer inspection is advisory. Native eject remains authoritative.
        }
        finally
        {
            ReleaseComObject(windows);
            ReleaseComObject(shell);
        }
        return locations
            .Distinct(StringComparer.OrdinalIgnoreCase)
            .OrderBy(location => location, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    private static void ReleaseComObject(object? value)
    {
        if (value is null || !Marshal.IsComObject(value)) return;
        try
        {
            Marshal.FinalReleaseComObject(value);
        }
        catch (InvalidComObjectException)
        {
            // Another released automation wrapper already disconnected this RCW.
        }
    }

    private static string? TryWriteDiagnostic(IReadOnlyList<string> lines)
    {
        try
        {
            Directory.CreateDirectory(MainWindow.LocalSettingsRoot);
            File.WriteAllLines(DiagnosticPath, lines);
            return DiagnosticPath;
        }
        catch (IOException)
        {
            return null;
        }
        catch (UnauthorizedAccessException)
        {
            return null;
        }
    }

    private static string DiagnosticMessage(string? path) =>
        string.IsNullOrWhiteSpace(path) ? string.Empty : $"\nDiagnostic: {path}";

    private static Brush ResourceBrush(string key, Brush fallback) =>
        Application.Current.TryFindResource(key) as Brush ?? fallback;

    private static FontFamily ResourceFont(string key, FontFamily fallback) =>
        Application.Current.TryFindResource(key) as FontFamily ?? fallback;
}
