using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace CSLibrary.Windows;

internal sealed record EjectHelperOptions(
    int ParentProcessId,
    long ParentStartTimeUtcTicks,
    string DeviceInstanceId,
    string DriveRoot)
{
    private const string HelperSwitch = "--eject-helper";

    internal static bool IsRequested(IReadOnlyList<string> arguments) =>
        arguments.Contains(HelperSwitch, StringComparer.Ordinal);

    internal static EjectHelperOptions Parse(IReadOnlyList<string> arguments)
    {
        if (!IsRequested(arguments))
            throw new ArgumentException("The native eject helper switch is missing.");

        var values = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var index = 0; index < arguments.Count; index++)
        {
            var argument = arguments[index];
            if (string.Equals(argument, HelperSwitch, StringComparison.Ordinal)) continue;
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

        return new EjectHelperOptions(
            parentProcessId,
            parentStartTimeUtcTicks,
            deviceInstanceId,
            driveRoot);
    }

    internal static EjectHelperOptions ForCurrentProcess(NativeEjectTarget target)
    {
        using var parent = Process.GetCurrentProcess();
        return new EjectHelperOptions(
            Environment.ProcessId,
            parent.StartTime.ToUniversalTime().Ticks,
            target.DeviceInstanceId,
            target.DriveRoot);
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
    private const int MaximumEjectAttempts = 3;
    private static readonly TimeSpan ParentExitTimeout = TimeSpan.FromSeconds(30);
    private static readonly TimeSpan HandleDrainDelay = TimeSpan.FromMilliseconds(900);
    private static readonly TimeSpan RetryDelay = TimeSpan.FromMilliseconds(800);

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
        try
        {
            await WaitForParentExitAsync(_options);
            _detail.Text = "Lattice is closed. Waiting for its final Windows handles to clear…";
            await Task.Delay(HandleDrainDelay);

            NativeEjectResult? result = null;
            for (var attempt = 1; attempt <= MaximumEjectAttempts; attempt++)
            {
                _detail.Text = attempt == 1
                    ? $"Asking Windows to safely eject {_options.DriveRoot}…"
                    : $"Windows is still closing a handle. Retrying safe eject ({attempt}/{MaximumEjectAttempts})…";
                result = await Task.Run(() => NativeDriveEjector.RequestEject(
                    _options.DeviceInstanceId));
                if (result.Success) break;
                if (!NativeDriveEjector.IsTransientCloseVeto(result)
                    || attempt == MaximumEjectAttempts) break;
                await Task.Delay(RetryDelay);
            }

            if (result is null)
                throw new InvalidOperationException("Windows returned no result for the eject request.");
            if (!result.Success)
            {
                FinishWithFailure(
                    "Windows vetoed the native eject request. The library remains disconnected and the drive "
                    + "was not ejected.\n\n" + result.FailureDetail,
                    "Windows blocked eject");
                return;
            }

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
            FinishWithFailure(
                "The library remains disconnected and the drive was not ejected.\n\n" + error.Message,
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

    private static async Task WaitForParentExitAsync(EjectHelperOptions options)
    {
        if (options.ParentProcessId == Environment.ProcessId)
            throw new InvalidOperationException("The eject helper cannot wait on its own process.");

        Process parent;
        try
        {
            parent = Process.GetProcessById(options.ParentProcessId);
        }
        catch (ArgumentException)
        {
            return;
        }

        using (parent)
        {
            long actualStartTime;
            try
            {
                actualStartTime = parent.StartTime.ToUniversalTime().Ticks;
            }
            catch (InvalidOperationException)
            {
                return;
            }
            if (actualStartTime != options.ParentStartTimeUtcTicks) return;

            using var timeout = new CancellationTokenSource(ParentExitTimeout);
            try
            {
                await parent.WaitForExitAsync(timeout.Token);
            }
            catch (InvalidOperationException)
            {
                // The process exited between the identity check and the wait.
                return;
            }
            catch (OperationCanceledException error)
            {
                throw new TaskCanceledException(
                    "Lattice did not close within 30 seconds, so Windows was not asked to eject the drive.",
                    error);
            }
        }
    }

    private static Brush ResourceBrush(string key, Brush fallback) =>
        Application.Current.TryFindResource(key) as Brush ?? fallback;

    private static FontFamily ResourceFont(string key, FontFamily fallback) =>
        Application.Current.TryFindResource(key) as FontFamily ?? fallback;
}
