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
    // Keep the legacy path so an in-place product rename does not strand the
    // selected library, WebView profile, or reader-state database.
    private static readonly string SettingsRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "CS Library");
    private static readonly string SavedLibraryPath = Path.Combine(SettingsRoot, "library-root.txt");

    private readonly CancellationTokenSource _lifetime = new();
    private readonly UpdateService _updateService = new();
    private Process? _serverProcess;
    private string? _serverUrl;
    private string? _libraryRoot;
    private bool _webViewConfigured;
    private bool _installingUpdate;
    private DesktopUpdateCheck? _updateCheck;

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
        await CheckForUpdatesAsync(presentResult: false);
    }

    private static bool IsLibrary(string? path)
    {
        if (string.IsNullOrWhiteSpace(path)) return false;
        try
        {
            var root = Path.GetFullPath(path);
            var appRoot = Path.TrimEndingDirectorySeparator(Path.GetFullPath(AppContext.BaseDirectory));
            if (string.Equals(
                Path.TrimEndingDirectorySeparator(root),
                appRoot,
                StringComparison.OrdinalIgnoreCase)) return false;
            return File.Exists(Path.Combine(root, "CATALOG.md"))
                && File.Exists(Path.Combine(root, "library-taxonomy.json"))
                && (Directory.Exists(Path.Combine(root, ".git"))
                    || File.Exists(Path.Combine(root, ".git")))
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

        // The installed package contains UI/catalog resources and an empty
        // scaffold, so it must never be inferred as the user's shared library.
        return null;
    }

    private string? ChooseLibrary()
    {
        while (true)
        {
            var dialog = new OpenFolderDialog
            {
                Title = "Choose the Lattice library folder",
                Multiselect = false,
            };
            if (IsLibrary(_libraryRoot)) dialog.InitialDirectory = _libraryRoot;
            if (dialog.ShowDialog(this) != true) return null;
            if (IsLibrary(dialog.FolderName)) return Path.GetFullPath(dialog.FolderName);

            MessageBox.Show(
                this,
                "That folder is not a Lattice library. Choose the synchronized clone containing CATALOG.md, library-taxonomy.json, metadata, and ui.",
                "Lattice",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
    }

    private async Task OpenLibraryAsync(string root)
    {
        SetLoading("Opening your library…", "Starting the private local reading service", false);
        SetBrowserControlsEnabled(false);
        StopOwnedServer();
        _libraryRoot = Path.GetFullPath(root);
        LibraryPathText.Text = _libraryRoot;

        try
        {
            Directory.CreateDirectory(SettingsRoot);
            File.WriteAllText(SavedLibraryPath, _libraryRoot + Environment.NewLine);
            _serverUrl = await StartServerAsync(_libraryRoot, _lifetime.Token);
            await ConfigureWebViewAsync(_libraryRoot);
            Browser.CoreWebView2.Navigate($"{_serverUrl}/?app=windows");
            StatusText.Text = "Loading your library";
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
            // The app is closing.
        }
        catch (Exception error)
        {
            SetLoading(
                "The library could not start",
                FriendlyStartupMessage(error),
                error is not WebView2RuntimeNotFoundException and not FileNotFoundException);
            StatusText.Text = "Needs attention";
        }
    }

    private static string FriendlyStartupMessage(Exception error)
    {
        if (error is WebView2RuntimeNotFoundException)
        {
            return "Microsoft Edge WebView2 Runtime is required. Install the Evergreen WebView2 Runtime from Microsoft, then reopen Lattice.";
        }
        if (error is FileNotFoundException)
        {
            return "The local service or bundled interface is missing. Extract the complete Lattice package, then run the app again.";
        }
        return error.Message;
    }

    private async Task<string> StartServerAsync(string root, CancellationToken cancellationToken)
    {
        var server = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "Server", "LatticeServer.exe"),
            Path.Combine(AppContext.BaseDirectory, "Server", "SharedLibraryServer.exe"),
            Path.Combine(AppContext.BaseDirectory, "Server", "CSLibraryServer.exe"),
        }.FirstOrDefault(File.Exists);
        if (server is null)
        {
            throw new FileNotFoundException(
                "The Lattice local service is missing. Extract the complete Windows package before running the app.");
        }
        var uiRoot = Path.Combine(AppContext.BaseDirectory, "ui");
        if (!File.Exists(Path.Combine(uiRoot, "index.html")))
            throw new FileNotFoundException("The bundled Lattice interface is missing.", uiRoot);

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
        start.ArgumentList.Add("--ui-root");
        start.ArgumentList.Add(uiRoot);
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
            var prefix = new[]
            {
                "Lattice is ready: ",
                "Lattice is already running at ",
                "Shared Library is ready: ",
                "Shared Library is already running at ",
                "CS Library is ready: ",
                "CS Library is already running at ",
            }.FirstOrDefault(candidate => line.StartsWith(candidate, StringComparison.Ordinal));
            if (prefix is not null) ready.TrySetResult(line[prefix.Length..].Trim());
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
            string detail;
            lock (errors) detail = errors.ToString().Trim();
            if (!ready.Task.IsCompleted)
            {
                ready.TrySetException(new InvalidOperationException(
                    string.IsNullOrEmpty(detail)
                        ? $"The local service exited with code {process.ExitCode}."
                        : detail));
                return;
            }
            if (process.ExitCode != 0 && !_lifetime.IsCancellationRequested)
            {
                Dispatcher.InvokeAsync(() =>
                {
                    if (!ReferenceEquals(_serverProcess, process)) return;
                    SetBrowserControlsEnabled(false);
                    SetLoading(
                        "The private local service stopped",
                        string.IsNullOrEmpty(detail) ? "Reopen Lattice to restart it." : detail,
                        false);
                    StatusText.Text = "Service stopped";
                });
            }
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
            Browser.CoreWebView2.NavigationCompleted += NavigationCompleted;
            Browser.CoreWebView2.HistoryChanged += (_, _) => UpdateNavigationControls();
            Browser.CoreWebView2.NewWindowRequested += NewWindowRequested;
            Browser.CoreWebView2.ProcessFailed += (_, eventArgs) =>
            {
                SetBrowserControlsEnabled(false);
                SetLoading(
                    "The reading window stopped",
                    $"WebView2 reported {eventArgs.ProcessFailedKind}. Reopen Lattice to recover.",
                    false);
                StatusText.Text = "Reader stopped";
            };
            Browser.CoreWebView2.DocumentTitleChanged += (_, _) =>
            {
                var title = Browser.CoreWebView2.DocumentTitle;
                Title = string.IsNullOrWhiteSpace(title) ? "Lattice" : $"{title} — Lattice";
            };

            var stateScript = new[]
            {
                Path.Combine(AppContext.BaseDirectory, "native", "SharedReaderState.js"),
                Path.Combine(root, "native", "SharedReaderState.js"),
            }.FirstOrDefault(File.Exists);
            if (stateScript is not null)
            {
                await Browser.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                    File.ReadAllText(stateScript));
            }
            _webViewConfigured = true;
        }
    }

    private void NavigationStarting(object? sender, CoreWebView2NavigationStartingEventArgs e)
    {
        if (IsLocalUri(e.Uri))
        {
            StatusText.Text = "Loading";
            return;
        }
        e.Cancel = true;
        if (Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri)
            && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
        {
            Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
        }
    }

    private void NavigationCompleted(object? sender, CoreWebView2NavigationCompletedEventArgs e)
    {
        if (!e.IsSuccess)
        {
            SetBrowserControlsEnabled(false);
            HomeButton.IsEnabled = _serverUrl is not null;
            ReloadButton.IsEnabled = Browser.CoreWebView2 is not null;
            SetLoading(
                "Lattice could not load",
                $"The local interface reported {e.WebErrorStatus}. Use Reload above or reopen the app.",
                false);
            StatusText.Text = "Load failed";
            return;
        }

        LoadingOverlay.Visibility = Visibility.Collapsed;
        SetBrowserControlsEnabled(true);
        StatusText.Text = "Private local library";
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

    private void SetBrowserControlsEnabled(bool enabled)
    {
        HomeButton.IsEnabled = enabled;
        ReloadButton.IsEnabled = enabled;
        AddMaterialsButton.IsEnabled = enabled;
        BackButton.IsEnabled = enabled && Browser.CanGoBack;
    }

    private void UpdateNavigationControls()
    {
        BackButton.IsEnabled = Browser.CoreWebView2 is not null && Browser.CanGoBack;
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

    private void Reload_Click(object sender, RoutedEventArgs e)
    {
        if (Browser.CoreWebView2 is not null) Browser.Reload();
    }

    private async void AddMaterials_Click(object sender, RoutedEventArgs e)
    {
        if (Browser.CoreWebView2 is null) return;
        const string script = """
            (() => {
              if (typeof window.sharedLibraryChooseFiles === "function") {
                window.sharedLibraryChooseFiles();
                return true;
              }
              const input = document.getElementById("addFilesInput");
              if (input instanceof HTMLInputElement) {
                input.click();
                return true;
              }
              return false;
            })()
            """;
        try
        {
            var result = await Browser.CoreWebView2.ExecuteScriptAsync(script);
            if (!string.Equals(result, "true", StringComparison.OrdinalIgnoreCase))
            {
                MessageBox.Show(
                    this,
                    "The Add materials control is unavailable in this interface. Reinstall the current Lattice package.",
                    "Lattice",
                    MessageBoxButton.OK,
                    MessageBoxImage.Information);
            }
        }
        catch (Exception error)
        {
            MessageBox.Show(
                this,
                $"The file chooser could not open. {error.Message}",
                "Lattice",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
    }

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

    private async void UpdateButton_Click(object sender, RoutedEventArgs e)
    {
        if (_installingUpdate) return;
        if (_updateCheck?.State == DesktopUpdateState.Available)
            await ConfirmAndInstallUpdateAsync(_updateCheck);
        else
            await CheckForUpdatesAsync(presentResult: true);
    }

    private async Task CheckForUpdatesAsync(bool presentResult)
    {
        if (_installingUpdate) return;
        UpdateButton.Content = "Checking for updates…";
        UpdateButton.IsEnabled = false;
        try
        {
            _updateCheck = await _updateService.CheckAsync(_lifetime.Token);
            switch (_updateCheck.State)
            {
                case DesktopUpdateState.Current:
                    UpdateButton.Content = "Up to date";
                    UpdateButton.IsEnabled = true;
                    if (presentResult)
                    {
                        MessageBox.Show(
                            this,
                            $"This app was built from the latest main commit, {ShortCommit(_updateCheck.LatestCommit)}.",
                            "Lattice is up to date",
                            MessageBoxButton.OK,
                            MessageBoxImage.Information);
                    }
                    break;
                case DesktopUpdateState.Available:
                    UpdateButton.Content = "Update available";
                    UpdateButton.IsEnabled = true;
                    if (presentResult) await ConfirmAndInstallUpdateAsync(_updateCheck);
                    break;
                case DesktopUpdateState.Preparing:
                    UpdateButton.Content = "Update preparing…";
                    UpdateButton.IsEnabled = true;
                    if (presentResult)
                    {
                        MessageBox.Show(
                            this,
                            $"GitHub main is at {ShortCommit(_updateCheck.LatestCommit)}, but its verified macOS and Windows packages are not both published yet. Try again after the build finishes.",
                            "The latest update is still being prepared",
                            MessageBoxButton.OK,
                            MessageBoxImage.Information);
                    }
                    break;
            }
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
            // The window is closing.
        }
        catch (Exception error)
        {
            _updateCheck = null;
            UpdateButton.Content = "Updates offline";
            UpdateButton.IsEnabled = true;
            if (presentResult)
            {
                MessageBox.Show(
                    this,
                    error.Message,
                    "Lattice could not check for updates",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning);
            }
        }
    }

    private async Task ConfirmAndInstallUpdateAsync(DesktopUpdateCheck update)
    {
        if (_installingUpdate || update.State != DesktopUpdateState.Available) return;
        var answer = MessageBox.Show(
            this,
            $"Installed: {ShortCommit(update.InstalledCommit)}\n"
                + $"Latest main: {ShortCommit(update.LatestCommit)}\n\n"
                + "Lattice will verify the download, replace only packaged application files, and reopen. "
                + "Books, papers, lectures, Syncthing content, and reading data are not changed.",
            "Install Lattice update?",
            MessageBoxButton.YesNo,
            MessageBoxImage.Question,
            MessageBoxResult.Yes);
        if (answer != MessageBoxResult.Yes) return;

        _installingUpdate = true;
        UpdateButton.IsEnabled = false;
        UpdateButton.Content = "Downloading update…";
        var progress = new Progress<int>(percentage =>
        {
            UpdateButton.Content = $"Downloading update… {percentage}%";
        });
        try
        {
            var stagingPath = await _updateService.DownloadAndStageAsync(
                update,
                progress,
                _lifetime.Token);
            UpdateButton.Content = "Installing update…";
            _updateService.LaunchInstaller(stagingPath, update.LatestCommit);
            Application.Current.Shutdown();
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
            // The app is already closing.
        }
        catch (Exception error)
        {
            _installingUpdate = false;
            UpdateButton.Content = "Update failed";
            UpdateButton.IsEnabled = true;
            MessageBox.Show(
                this,
                $"Nothing was installed.\n\n{error.Message}",
                "Lattice update failed",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
    }

    private static string ShortCommit(string commit) =>
        commit == "development" ? "development build" : commit[..Math.Min(12, commit.Length)];

    private void Window_Closing(object? sender, CancelEventArgs e)
    {
        _lifetime.Cancel();
        StopOwnedServer();
        Browser.Dispose();
        _lifetime.Dispose();
    }
}
