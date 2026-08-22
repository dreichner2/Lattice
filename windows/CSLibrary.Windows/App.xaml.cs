using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace CSLibrary.Windows;

public partial class App : Application
{
    private const int DwmwaWindowCornerPreference = 33;
    private const int DwmwaBorderColor = 34;
    private const int DwmwaCaptionColor = 35;
    private const int DwmwaTextColor = 36;
    private const int DwmWindowCornerRound = 2;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        var smokeRequested = e.Args.Contains("--smoke-test", StringComparer.Ordinal);
        try
        {
            if (UpdateStartupRedirect.TryRedirectToActiveVersion(e.Args))
            {
                Shutdown(0);
                return;
            }
        }
        catch (Exception error) when (error is IOException
                                      or UnauthorizedAccessException
                                      or InvalidDataException
                                      or InvalidOperationException
                                      or NotSupportedException
                                      or System.Text.Json.JsonException
                                      or System.ComponentModel.Win32Exception
                                      or System.Security.Cryptography.CryptographicException)
        {
            ReportStartupIssue(
                "Lattice could not safely open the active updated version. "
                + error.Message,
                smokeRequested);
            Shutdown(3);
            return;
        }

        LaunchOptions options;
        try
        {
            options = LaunchOptions.Parse(e.Args);
        }
        catch (ArgumentException error)
        {
            ReportStartupIssue(error.Message, smokeRequested, MessageBoxImage.Error);
            Shutdown(2);
            return;
        }

        var window = new MainWindow(options);
        window.SourceInitialized += (_, _) => ApplyNativeChrome(window);
        MainWindow = window;
        window.Show();
    }

    private static void ReportStartupIssue(
        string message,
        bool smokeRequested,
        MessageBoxImage icon = MessageBoxImage.Warning)
    {
        if (smokeRequested)
        {
            Console.Error.WriteLine(message);
            return;
        }
        MessageBox.Show(message, "Lattice", MessageBoxButton.OK, icon);
    }

    private static void ApplyNativeChrome(Window window)
    {
        // Windows 11 exposes native caption colors and rounded-corner preference
        // through DWM. Older supported Windows versions safely keep their normal
        // system title bar when these attributes are unavailable.
        if (SystemParameters.HighContrast
            || !OperatingSystem.IsWindowsVersionAtLeast(10, 0, 22000)) return;

        var handle = new WindowInteropHelper(window).Handle;
        var corner = DwmWindowCornerRound;
        var border = ColorRef(red: 215, green: 213, blue: 207);
        var caption = ColorRef(red: 248, green: 247, blue: 244);
        var text = ColorRef(red: 23, green: 25, blue: 31);
        _ = DwmSetWindowAttribute(handle, DwmwaWindowCornerPreference, ref corner, sizeof(int));
        _ = DwmSetWindowAttribute(handle, DwmwaBorderColor, ref border, sizeof(int));
        _ = DwmSetWindowAttribute(handle, DwmwaCaptionColor, ref caption, sizeof(int));
        _ = DwmSetWindowAttribute(handle, DwmwaTextColor, ref text, sizeof(int));
    }

    private static int ColorRef(byte red, byte green, byte blue) =>
        red | (green << 8) | (blue << 16);

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(
        nint window,
        int attribute,
        ref int value,
        int valueSize);
}

internal sealed record LaunchOptions(string? LibraryRoot, SmokeTestOptions? SmokeTest)
{
    internal static LaunchOptions Empty { get; } = new(null, null);

    internal static LaunchOptions Parse(IReadOnlyList<string> arguments)
    {
        var smokeTest = false;
        string? libraryRoot = null;
        string? smokeOutput = null;
        var positional = new List<string>();
        var unknownOptions = new List<string>();

        for (var index = 0; index < arguments.Count; index++)
        {
            switch (arguments[index])
            {
                case "--smoke-test":
                    smokeTest = true;
                    break;
                case "--library-root":
                    libraryRoot = ReadValue(arguments, ref index, "--library-root");
                    break;
                case "--smoke-output":
                    smokeOutput = ReadValue(arguments, ref index, "--smoke-output");
                    break;
                case "--update-candidate":
                case "--update-token":
                    _ = ReadValue(arguments, ref index, arguments[index]);
                    break;
                default:
                    if (!arguments[index].StartsWith("--", StringComparison.Ordinal))
                        positional.Add(arguments[index]);
                    else
                        unknownOptions.Add(arguments[index]);
                    break;
            }
        }

        libraryRoot ??= positional.FirstOrDefault();
        if (!smokeTest) return new LaunchOptions(libraryRoot, null);
        if (unknownOptions.Count > 0)
            throw new ArgumentException($"Unknown smoke-test option: {unknownOptions[0]}");
        if (string.IsNullOrWhiteSpace(libraryRoot) || string.IsNullOrWhiteSpace(smokeOutput))
        {
            throw new ArgumentException(
                "Smoke mode requires --library-root <clone> and --smoke-output <directory>.");
        }

        var root = Path.GetFullPath(libraryRoot);
        var output = Path.GetFullPath(smokeOutput);
        return new LaunchOptions(root, new SmokeTestOptions(
            Root: root,
            ReportPath: Path.Combine(output, "lattice-smoke.json"),
            ScreenshotPath: Path.Combine(output, "lattice-webview.png")));
    }

    private static string ReadValue(IReadOnlyList<string> arguments, ref int index, string option)
    {
        if (index + 1 >= arguments.Count
            || string.IsNullOrWhiteSpace(arguments[index + 1])
            || arguments[index + 1].StartsWith("--", StringComparison.Ordinal))
            throw new ArgumentException($"{option} requires a value.");
        index += 1;
        return arguments[index];
    }
}

internal sealed record SmokeTestOptions(string Root, string ReportPath, string ScreenshotPath);
