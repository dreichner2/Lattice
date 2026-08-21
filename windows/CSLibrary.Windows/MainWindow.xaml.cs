using Microsoft.Web.WebView2.Core;
using Microsoft.Win32;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows;

namespace CSLibrary.Windows;

public partial class MainWindow : Window
{
    private static readonly string SettingsRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "CS Library");
    private static readonly string SavedLibraryPath = Path.Combine(SettingsRoot, "library-root.txt");

    private readonly CancellationTokenSource _lifetime = new();
    private Process? _serverProcess;
    private string? _serverUrl;
    private string? _libraryRoot;
    private bool _webViewConfigured;

    public MainWindow()
    {
        InitializeComponent();
    }

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        var root = FindInitialLibrary() ?? ChooseLibrary();
        if (root is null)
        {
            Application.Current.Shutdown();
            return;
        }
        await OpenLibraryAsync(root);
    }

    private static bool IsLibrary(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return false;
        try
        {
            var root = Path.GetFullPath(path);
            return File.Exists(Path.Combine(root, "CATALOG.md"))
                && Directory.Exists(Path.Combine(root, "metadata"))
                && Directory.Exists(Path.Combine(root, "ui"));
        }
        catch (Exception) when (path is not null)
        {
            return false;
        }
    }

    private static string? FindInitialLibrary()
    {
        var argument = Environment.GetCommandLineArgs().Skip(1).FirstOrDefault(IsLibrary);
        if (argument is not null) return Path.GetFullPath(argument);

        try
        {
            if (File.Exists(SavedLibraryPath))
            {
                var saved = File.ReadAllText(SavedLibraryPath).Trim();
                if (IsLibrary(saved)) return Path.GetFullPath(saved);
            }
        }
        catch (IOException)
        {
            // The chooser below is the safe fallback for an unreadable setting.
        }

        var besideApp = AppContext.BaseDirectory;
        return IsLibrary(besideApp) ? Path.GetFullPath(besideApp) : null;
    }

    private string? ChooseLibrary()
    {
        var dialog = new OpenFolderDialog
        {
            Title = "Choose the CS Library folder",
            Multiselect = false,
        };
        if (IsLibrary(_libraryRoot)) dialog.InitialDirectory = _libraryRoot;
        if (dialog.ShowDialog(this) != true) return null;
        if (!IsLibrary(dialog.FolderName))
        {
            MessageBox.Show(
                this,
                "That folder is not a CS Library. Choose the folder containing CATALOG.md, metadata, and ui.",
                "CS Library",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            return ChooseLibrary();
        }
        return Path.GetFullPath(dialog.FolderName);
    }

    private async Task OpenLibraryAsync(string root)
    {
        SetLoading("Opening your library…", "Starting the private local reading service", false);
        StopOwnedServer();
        _libraryRoot = Path.GetFullPath(root);
        LibraryPathText.Text = _libraryRoot;
        Directory.CreateDirectory(SettingsRoot);
        File.WriteAllText(SavedLibraryPath, _libraryRoot + Environment.NewLine);

        try
        {
            _serverUrl = await StartServerAsync(_libraryRoot, _lifetime.Token);
            await ConfigureWebViewAsync(_libraryRoot);
            Browser.CoreWebView2.Navigate($"{_serverUrl}/?app=windows");
            StatusText.Text = "Private local library";
            LoadingOverlay.Visibility = Visibility.Collapsed;
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
            // The app is closing.
        }
        catch (Exception error)
        {
            SetLoading(
                "The library could not start",
                error.Message,
                true);
            StatusText.Text = "Needs attention";
        }
    }

    private async Task<string> StartServerAsync(string root, CancellationToken cancellationToken)
    {
        var server = Path.Combine(AppContext.BaseDirectory, "Server", "CSLibraryServer.exe");
        if (!File.Exists(server))
        {
            throw new FileNotFoundException(
                "CSLibraryServer.exe is missing. Extract the complete Windows package before running the app.",
                server);
        }

        var ready = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);
        var errors = new StringBuilder();
        var start = new ProcessStartInfo(server)
        {
            WorkingDirectory = root,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        start.ArgumentList.Add("--root");
        start.ArgumentList.Add(root);
        start.ArgumentList.Add("--port");
        start.ArgumentList.Add("8766");
        start.ArgumentList.Add("--parent-pid");
        start.ArgumentList.Add(Environment.ProcessId.ToString());
        start.ArgumentList.Add("--no-browser");
        start.Environment["PYTHONUNBUFFERED"] = "1";

        var process = new Process { StartInfo = start, EnableRaisingEvents = true };
        process.OutputDataReceived += (_, eventArgs) =>
        {
            var line = eventArgs.Data;
            if (line is null) return;
            const string started = "CS Library is ready: ";
            const string existing = "CS Library is already running at ";
            if (line.StartsWith(started, StringComparison.Ordinal))
                ready.TrySetResult(line[started.Length..].Trim());
            else if (line.StartsWith(existing, StringComparison.Ordinal))
                ready.TrySetResult(line[existing.Length..].Trim());
        };
        process.ErrorDataReceived += (_, eventArgs) =>
        {
            if (!string.IsNullOrWhiteSpace(eventArgs.Data))
            {
                lock (errors) errors.AppendLine(eventArgs.Data);
            }
        };
        process.Exited += (_, _) =>
        {
            if (ready.Task.IsCompleted) return;
            string detail;
            lock (errors) detail = errors.ToString().Trim();
            ready.TrySetException(new InvalidOperationException(
                string.IsNullOrEmpty(detail)
                    ? $"The local service exited with code {process.ExitCode}."
                    : detail));
        };

        if (!process.Start()) throw new InvalidOperationException("The local service did not start.");
        _serverProcess = process;
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(25));
        try
        {
            return await ready.Task.WaitAsync(timeout.Token);
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            string detail;
            lock (errors) detail = errors.ToString().Trim();
            throw new TimeoutException(
                string.IsNullOrEmpty(detail)
                    ? "The local reading service did not become ready within 25 seconds."
                    : detail);
        }
    }

    private async Task ConfigureWebViewAsync(string root)
    {
        if (!_webViewConfigured)
        {
            var userData = Path.Combine(SettingsRoot, "WebView2");
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: userData);
            await Browser.EnsureCoreWebView2Async(environment);
            Browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
            Browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
            Browser.CoreWebView2.Settings.IsStatusBarEnabled = false;
            Browser.CoreWebView2.NavigationStarting += NavigationStarting;
            Browser.CoreWebView2.NewWindowRequested += NewWindowRequested;
            Browser.CoreWebView2.DocumentTitleChanged += (_, _) =>
            {
                var title = Browser.CoreWebView2.DocumentTitle;
                Title = string.IsNullOrWhiteSpace(title) ? "CS Library" : $"{title} — CS Library";
            };
            _webViewConfigured = true;
        }

        var stateScript = new[]
        {
            Path.Combine(root, "native", "SharedReaderState.js"),
            Path.Combine(AppContext.BaseDirectory, "native", "SharedReaderState.js"),
        }.FirstOrDefault(File.Exists);
        if (stateScript is not null)
            await Browser.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(File.ReadAllText(stateScript));
    }

    private void NavigationStarting(object? sender, CoreWebView2NavigationStartingEventArgs e)
    {
        if (IsLocalUri(e.Uri)) return;
        if (!Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri)
            || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)) return;
        e.Cancel = true;
        Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
    }

    private void NewWindowRequested(object? sender, CoreWebView2NewWindowRequestedEventArgs e)
    {
        e.Handled = true;
        if (Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri)
            && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
            Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
    }

    private static bool IsLocalUri(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri)) return false;
        return uri.Scheme is "http" or "https"
            && uri.Host is "127.0.0.1" or "localhost" or "::1";
    }

    private void SetLoading(string title, string detail, bool chooseFolder)
    {
        LoadingTitle.Text = title;
        LoadingDetail.Text = detail;
        ChooseFolderButton.Visibility = chooseFolder ? Visibility.Visible : Visibility.Collapsed;
        LoadingOverlay.Visibility = Visibility.Visible;
    }

    private void StopOwnedServer()
    {
        var process = _serverProcess;
        _serverProcess = null;
        if (process is null) return;
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit(3_000);
            }
        }
        catch (InvalidOperationException)
        {
            // It exited between the checks.
        }
        finally
        {
            process.Dispose();
        }
    }

    private void Back_Click(object sender, RoutedEventArgs e)
    {
        if (Browser.CanGoBack) Browser.GoBack();
    }

    private void Home_Click(object sender, RoutedEventArgs e)
    {
        if (_serverUrl is not null) Browser.CoreWebView2?.Navigate($"{_serverUrl}/?app=windows");
    }

    private void Reload_Click(object sender, RoutedEventArgs e) => Browser.Reload();

    private void OpenFolder_Click(object sender, RoutedEventArgs e)
    {
        if (_libraryRoot is not null)
        {
            var start = new ProcessStartInfo("explorer.exe") { UseShellExecute = true };
            start.ArgumentList.Add(_libraryRoot);
            Process.Start(start);
        }
    }

    private async void ChangeLibrary_Click(object sender, RoutedEventArgs e)
    {
        var root = ChooseLibrary();
        if (root is not null) await OpenLibraryAsync(root);
    }

    private void Window_Closing(object? sender, CancelEventArgs e)
    {
        _lifetime.Cancel();
        StopOwnedServer();
        Browser.Dispose();
        _lifetime.Dispose();
    }
}
