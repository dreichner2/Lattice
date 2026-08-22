using Microsoft.Web.WebView2.Core;
using Microsoft.Win32;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Input;
using System.Windows.Threading;

namespace CSLibrary.Windows;

public partial class MainWindow : Window
{
    // Keep the legacy path so an in-place product rename does not strand the
    // selected library, WebView profile, or reader-state database.
    private static readonly string SettingsRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "CS Library");
    private static readonly string SavedLibraryPath = Path.Combine(SettingsRoot, "library-root.txt");
    private static readonly string SavedWindowBoundsPath = Path.Combine(SettingsRoot, "window-bounds.json");
    private static readonly string LibraryDisconnectStatePath = Path.Combine(
        SettingsRoot,
        "external-library-reconnect.json");
    private const string NativeBridgeBootstrapScript = """
        (() => {
          if (window.top !== window || window.csLibraryNativeCall || !window.chrome?.webview) return;
          const pending = new Map();
          let sequence = 0;
          window.chrome.webview.addEventListener('message', event => {
            const message = event.data;
            if (!message || typeof message !== 'object') return;
            if (message.channel === 'lattice-native-status') {
              window.dispatchEvent(new CustomEvent('lattice-native-status', { detail: message }));
              return;
            }
            if (message.channel !== 'lattice-native-response' || typeof message.id !== 'string') return;
            const request = pending.get(message.id);
            if (!request) return;
            pending.delete(message.id);
            clearTimeout(request.timer);
            if (typeof message.error === 'string' && message.error) request.reject(new Error(message.error));
            else request.resolve(message.result);
          });
          window.csLibraryNativeCall = (action, payload = {}) => new Promise((resolve, reject) => {
            const id = `windows-${Date.now().toString(36)}-${(++sequence).toString(36)}`;
            const timer = setTimeout(() => {
              pending.delete(id);
              reject(new Error('Lattice did not answer the desktop request.'));
            }, 30000);
            pending.set(id, { resolve, reject, timer });
            window.chrome.webview.postMessage({ channel: 'lattice-native', id, action, payload });
          });
          window.dispatchEvent(new CustomEvent('cs-library-native-ready'));
        })();
        """;

    private readonly LaunchOptions _launchOptions;
    private readonly CancellationTokenSource _lifetime = new();
    private readonly DispatcherTimer? _smokeTimer;
    private readonly UpdateService _updateService = new();
    private readonly UpdateCandidateSession? _updateCandidate;
    private readonly bool _candidateLaunchRequested;
    private Process? _serverProcess;
    private string? _serverUrl;
    private string? _libraryRoot;
    private string? _readerStateScriptId;
    private bool _webViewConfigured;
    private bool _openingLibrary;
    private bool _smokeCompleted;
    private bool _backgroundUpdateCheckStarted;
    private bool _updateOperationInProgress;
    private bool _libraryMoveInProgress;
    private bool _libraryDriveOperationInProgress;
    private bool _candidateLaunched;
    private bool _candidatePromoted;
    private bool _candidateErrorNotified;
    private bool _webContentFullscreen;
    private bool _browserControlsEnabled;
    private bool _librarySwitchingEnabled = true;
    private bool _updateProgressVisible;
    private bool _updateProgressIndeterminate;
    private int _updateProgressValue;
    private string _shellStatusText = "Starting";
    private ShellStatus _shellStatus = ShellStatus.Loading;
    private string? _candidatePromotionError;
    private WindowStyle _windowStyleBeforeFullscreen;
    private ResizeMode _resizeModeBeforeFullscreen;
    private WindowState _windowStateBeforeFullscreen;
    private Rect _windowBoundsBeforeFullscreen;
    private DesktopUpdateCheck? _availableUpdate;
    private StagedDesktopUpdate? _stagedUpdate;
    private Task<DesktopUpdateCheck>? _updateCheckTask;

    private string DisplayVersion => _updateCandidate?.CandidateVersion
        ?? _updateService.InstalledVersion
        ?? typeof(MainWindow).Assembly.GetName().Version?.ToString(3)
        ?? "Unknown";

    public MainWindow() : this(LaunchOptions.Empty)
    {
    }

    internal MainWindow(LaunchOptions launchOptions)
    {
        _launchOptions = launchOptions;
        var processArguments = Environment.GetCommandLineArgs().Skip(1).ToArray();
        _candidateLaunchRequested = processArguments.Contains("--update-candidate", StringComparer.Ordinal)
            || processArguments.Contains("--update-token", StringComparer.Ordinal);
        try
        {
            _updateCandidate = UpdateCandidateSession.TryOpenFromCurrentProcess(processArguments);
        }
        catch (Exception error) when (error is IOException
                                      or UnauthorizedAccessException
                                      or InvalidDataException
                                      or InvalidOperationException
                                      or ArgumentException
                                      or JsonException
                                      or System.Security.Cryptography.CryptographicException)
        {
            _candidatePromotionError = "The update launch proof could not be verified. " + error.Message;
        }
        InitializeComponent();
        if (launchOptions.SmokeTest is not null)
        {
            Width = 1280;
            Height = 800;
            WindowStartupLocation = WindowStartupLocation.CenterScreen;
            _smokeTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(50) };
            _smokeTimer.Tick += async (_, _) =>
            {
                _smokeTimer.Stop();
                await CompleteSmokeTestAsync(
                    navigationSucceeded: false,
                    stage: "timeout",
                    error: "The native shell did not reach a successful WebView navigation within 50 seconds.");
            };
        }
        else
        {
            RestoreWindowBounds();
        }
    }

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        _smokeTimer?.Start();

        var root = FindInitialLibrary();
        if (root is null && _launchOptions.SmokeTest is not null)
        {
            await CompleteSmokeTestAsync(
                navigationSucceeded: false,
                stage: "library-root",
                error: "The explicit --library-root is not a valid Lattice clone.");
            return;
        }
        root ??= ChooseLibrary();
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

    private string? FindInitialLibrary()
    {
        if (IsLibrary(_launchOptions.LibraryRoot)) return Path.GetFullPath(_launchOptions.LibraryRoot!);
        if (_launchOptions.SmokeTest is not null) return null;

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
        if (_openingLibrary) return;
        _openingLibrary = true;
        SetLoading(
            "Opening your library…",
            "Starting the private local reading service",
            chooseFolder: false,
            busy: true,
            retry: false);
        SetBrowserControlsEnabled(false);
        SetLibrarySwitchingEnabled(false);
        StopOwnedServer();
        _serverUrl = null;
        _libraryRoot = Path.GetFullPath(root);

        try
        {
            Directory.CreateDirectory(SettingsRoot);
            File.WriteAllText(SavedLibraryPath, _libraryRoot + Environment.NewLine);
            _serverUrl = await StartServerAsync(_libraryRoot, _lifetime.Token);
            if (!Uri.TryCreate(_serverUrl, UriKind.Absolute, out var serverUri)
                || !IsLoopbackHttpUri(serverUri))
            {
                throw new InvalidOperationException(
                    "The local service reported an invalid listening address.");
            }
            if (_updateCandidate is not null
                && _candidatePromotionError is null
                && !_candidatePromoted)
            {
                try
                {
                    var ownedServer = _serverProcess
                        ?? throw new InvalidOperationException("The candidate local service is not owned.");
                    await _updateCandidate.ReportServerHealthyAsync(
                        serverUri,
                        _libraryRoot!,
                        ownedServer,
                        _lifetime.Token);
                }
                catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
                {
                    throw;
                }
                catch (Exception updateError) when (updateError is IOException
                                                     or HttpRequestException
                                                     or InvalidDataException
                                                     or InvalidOperationException
                                                     or OperationCanceledException)
                {
                    RecordCandidatePromotionFailure("Server health proof failed", updateError);
                }
            }
            await ConfigureWebViewAsync(_libraryRoot);
            Browser.CoreWebView2.Navigate($"{_serverUrl}/?app=windows");
            SetShellStatus("Loading your library", ShellStatus.Loading);
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
            // The app is closing.
        }
        catch (Exception) when (_lifetime.IsCancellationRequested)
        {
            // WebView initialization can surface disposal as a non-cancellation
            // exception while the window is closing.
        }
        catch (Exception error)
        {
            StopOwnedServer();
            _serverUrl = null;
            SetLoading(
                "The library could not start",
                FriendlyStartupMessage(error),
                chooseFolder: error is not WebView2RuntimeNotFoundException and not FileNotFoundException,
                busy: false,
                retry: error is not WebView2RuntimeNotFoundException and not FileNotFoundException);
            SetShellStatus("Needs attention", ShellStatus.Attention);
            _openingLibrary = false;
            SetLibrarySwitchingEnabled(true);
            if (_candidateLaunchRequested && !_candidatePromoted)
            {
                if (_candidatePromotionError is null)
                    RecordCandidatePromotionFailure("Candidate startup failed", error);
                ApplyReadyShellStatus();
                NotifyCandidatePromotionFailure();
            }
            if (_launchOptions.SmokeTest is not null)
            {
                await CompleteSmokeTestAsync(
                    navigationSucceeded: false,
                    stage: "startup",
                    error: FriendlyStartupMessage(error));
            }
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
        // A candidate must prove the health of the server process it just
        // launched. Port zero bypasses the normal same-library reuse path and
        // gives the candidate an isolated, OS-assigned loopback port while the
        // current version remains open.
        start.ArgumentList.Add(_candidateLaunchRequested ? "0" : "8766");
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
            try
            {
                process.WaitForExit();
            }
            catch (InvalidOperationException)
            {
                // A concurrent library switch may already have disposed it.
            }
            string detail;
            lock (errors) detail = errors.ToString().Trim();
            var exitCode = TryGetExitCode(process);
            if (!ready.Task.IsCompleted)
            {
                ready.TrySetException(new InvalidOperationException(
                    string.IsNullOrEmpty(detail)
                        ? $"The local service exited with code {exitCode?.ToString() ?? "unknown"}."
                        : detail));
                return;
            }
            if (exitCode is int code && code != 0 && !_lifetime.IsCancellationRequested)
            {
                Dispatcher.InvokeAsync(() =>
                {
                    if (!ReferenceEquals(_serverProcess, process)) return;
                    _openingLibrary = false;
                    SetBrowserControlsEnabled(false);
                    SetLibrarySwitchingEnabled(true);
                    SetLoading(
                        "The private local service stopped",
                        string.IsNullOrEmpty(detail) ? "Reopen Lattice to restart it." : detail,
                        chooseFolder: true,
                        busy: false,
                        retry: true);
                    SetShellStatus("Service stopped", ShellStatus.Attention);
                    if (_candidateLaunchRequested && !_candidatePromoted)
                    {
                        if (_candidatePromotionError is null)
                        {
                            RecordCandidatePromotionFailure(
                                "Candidate local service stopped",
                                new InvalidOperationException(
                                    string.IsNullOrEmpty(detail)
                                        ? $"The local service exited with code {code}."
                                        : detail));
                        }
                        ApplyReadyShellStatus();
                        NotifyCandidatePromotionFailure();
                    }
                    if (_launchOptions.SmokeTest is not null)
                    {
                        _ = CompleteSmokeTestAsync(
                            navigationSucceeded: false,
                            stage: "server-exit",
                            error: string.IsNullOrEmpty(detail)
                                ? $"The local service exited with code {code}."
                                : detail);
                    }
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

    private static int? TryGetExitCode(Process process)
    {
        try
        {
            return process.ExitCode;
        }
        catch (InvalidOperationException)
        {
            return null;
        }
    }

    private async Task ConfigureWebViewAsync(string root)
    {
        if (!_webViewConfigured)
        {
            var userData = Path.Combine(SettingsRoot, "WebView2");
            var environment = await CoreWebView2Environment.CreateAsync(userDataFolder: userData);
            await Browser.EnsureCoreWebView2Async(environment);
            await Browser.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                NativeBridgeBootstrapScript);
            Browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
            Browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
            Browser.CoreWebView2.Settings.IsStatusBarEnabled = false;
            Browser.CoreWebView2.NavigationStarting += NavigationStarting;
            Browser.CoreWebView2.NavigationCompleted += NavigationCompleted;
            Browser.CoreWebView2.WebMessageReceived += WebMessageReceived;
            Browser.CoreWebView2.NewWindowRequested += NewWindowRequested;
            Browser.CoreWebView2.ContainsFullScreenElementChanged += (_, _) =>
            {
                if (_lifetime.IsCancellationRequested) return;
                Dispatcher.InvokeAsync(() => SetWebContentFullscreen(
                    Browser.CoreWebView2.ContainsFullScreenElement));
            };
            Browser.CoreWebView2.ProcessFailed += (_, eventArgs) =>
            {
                if (_lifetime.IsCancellationRequested) return;
                _openingLibrary = false;
                SetBrowserControlsEnabled(false);
                SetLibrarySwitchingEnabled(true);
                SetLoading(
                    "The reading window stopped",
                    $"WebView2 reported {eventArgs.ProcessFailedKind}. Reopen Lattice to recover.",
                    chooseFolder: true,
                    busy: false,
                    retry: true);
                SetShellStatus("Reader stopped", ShellStatus.Attention);
                if (_candidateLaunchRequested && !_candidatePromoted)
                {
                    if (_candidatePromotionError is null)
                    {
                        RecordCandidatePromotionFailure(
                            "Candidate WebView process failed",
                            new InvalidOperationException($"WebView2 reported {eventArgs.ProcessFailedKind}."));
                    }
                    ApplyReadyShellStatus();
                    NotifyCandidatePromotionFailure();
                }
                if (_launchOptions.SmokeTest is not null)
                {
                    _ = CompleteSmokeTestAsync(
                        navigationSucceeded: false,
                        stage: "webview-process",
                        error: $"WebView2 reported {eventArgs.ProcessFailedKind}.");
                }
            };
            Browser.CoreWebView2.DocumentTitleChanged += (_, _) =>
            {
                var title = Browser.CoreWebView2.DocumentTitle.Trim();
                Title = string.IsNullOrWhiteSpace(title)
                    || string.Equals(title, "Lattice", StringComparison.OrdinalIgnoreCase)
                    ? "Lattice"
                    : title.EndsWith(" — Lattice", StringComparison.OrdinalIgnoreCase)
                        ? title
                        : $"{title} — Lattice";
            };
            _webViewConfigured = true;
        }

        if (_readerStateScriptId is not null)
        {
            Browser.CoreWebView2.RemoveScriptToExecuteOnDocumentCreated(_readerStateScriptId);
            _readerStateScriptId = null;
        }
        var stateScript = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "native", "SharedReaderState.js"),
            Path.Combine(root, "native", "SharedReaderState.js"),
        }.FirstOrDefault(File.Exists);
        if (stateScript is not null)
        {
            _readerStateScriptId = await Browser.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(
                File.ReadAllText(stateScript));
        }
    }

    private void WebMessageReceived(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        if (Browser.CoreWebView2 is null
            || !IsOwnedServerUri(Browser.CoreWebView2.Source)) return;

        string? requestId = null;
        try
        {
            using var document = JsonDocument.Parse(e.WebMessageAsJson);
            var request = document.RootElement;
            if (request.ValueKind != JsonValueKind.Object
                || !request.TryGetProperty("channel", out var channel)
                || channel.ValueKind != JsonValueKind.String
                || channel.GetString() != "lattice-native"
                || !request.TryGetProperty("id", out var idElement)
                || idElement.ValueKind != JsonValueKind.String
                || !request.TryGetProperty("action", out var actionElement)
                || actionElement.ValueKind != JsonValueKind.String) return;

            requestId = idElement.GetString();
            var action = actionElement.GetString();
            if (string.IsNullOrWhiteSpace(requestId)
                || requestId.Length > 128
                || string.IsNullOrWhiteSpace(action)
                || action.Length > 128) return;

            if (action == "app.info")
            {
                ReplyToNativeBridge(requestId, new
                {
                    platform = "windows",
                    version = DisplayVersion,
                    capabilities = new[]
                    {
                        "app.checkForUpdates",
                        "app.moveLibrary",
                        "app.disconnectLibrary",
                        "app.reconnectLibrary",
                        "app.openLibraryFolder",
                        "app.chooseLibrary",
                        "app.reload",
                    },
                    status = NativeStatusPayload(),
                });
                return;
            }

            if (action is not ("app.checkForUpdates"
                or "app.moveLibrary"
                or "app.disconnectLibrary"
                or "app.reconnectLibrary"
                or "app.openLibraryFolder"
                or "app.chooseLibrary"
                or "app.reload"))
            {
                ReplyToNativeBridge(requestId, error: "That Lattice desktop action is unavailable.");
                return;
            }

            ReplyToNativeBridge(requestId, new { started = true });
            Dispatcher.BeginInvoke(
                DispatcherPriority.Input,
                new Action(() => DispatchNativeAppAction(action)));
        }
        catch (JsonException)
        {
            if (!string.IsNullOrWhiteSpace(requestId))
                ReplyToNativeBridge(requestId, error: "The Lattice desktop request was malformed.");
        }
    }

    private void DispatchNativeAppAction(string action)
    {
        switch (action)
        {
            case "app.checkForUpdates":
                CheckForUpdates_Click(this, new RoutedEventArgs());
                break;
            case "app.moveLibrary":
                MoveLibrary_Click(this, new RoutedEventArgs());
                break;
            case "app.disconnectLibrary":
                DisconnectLibrary_Click(this, new RoutedEventArgs());
                break;
            case "app.reconnectLibrary":
                ReconnectLibrary_Click(this, new RoutedEventArgs());
                break;
            case "app.openLibraryFolder":
                OpenFolder_Click(this, new RoutedEventArgs());
                break;
            case "app.chooseLibrary":
                ChangeLibrary_Click(this, new RoutedEventArgs());
                break;
            case "app.reload":
                Reload_Click(this, new RoutedEventArgs());
                break;
        }
    }

    private void ReplyToNativeBridge(string id, object? result = null, string? error = null)
    {
        if (Browser.CoreWebView2 is null) return;
        var message = JsonSerializer.Serialize(new
        {
            channel = "lattice-native-response",
            id,
            result,
            error,
        });
        Browser.CoreWebView2.PostWebMessageAsJson(message);
    }

    private object NativeStatusPayload() => new
    {
        channel = "lattice-native-status",
        text = _shellStatusText,
        tone = _shellStatus switch
        {
            ShellStatus.Ready => "ready",
            ShellStatus.UpdateAvailable => "updateAvailable",
            ShellStatus.Attention => "attention",
            _ => "loading",
        },
        version = DisplayVersion,
        busy = _updateOperationInProgress || _libraryDriveOperationInProgress,
        libraryActionsEnabled = _librarySwitchingEnabled
            && !_openingLibrary
            && !_libraryMoveInProgress
            && !_libraryDriveOperationInProgress,
        browserControlsEnabled = _browserControlsEnabled,
        progressVisible = _updateProgressVisible,
        progressIndeterminate = _updateProgressIndeterminate,
        progress = _updateProgressValue,
    };

    private void PostNativeStatus()
    {
        if (Browser.CoreWebView2 is null
            || !IsOwnedServerUri(Browser.CoreWebView2.Source)) return;
        try
        {
            Browser.CoreWebView2.PostWebMessageAsJson(
                JsonSerializer.Serialize(NativeStatusPayload()));
        }
        catch (InvalidOperationException)
        {
            // Navigation can replace the page between the origin check and send.
        }
    }

    private void NavigationStarting(object? sender, CoreWebView2NavigationStartingEventArgs e)
    {
        if (IsOwnedServerUri(e.Uri))
        {
            SetShellStatus("Loading", ShellStatus.Loading);
            return;
        }
        e.Cancel = true;
        if (Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri)
            && !uri.IsLoopback
            && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
        {
            Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
        }
    }

    private async void NavigationCompleted(object? sender, CoreWebView2NavigationCompletedEventArgs e)
    {
        if (_lifetime.IsCancellationRequested) return;
        if (!e.IsSuccess)
        {
            _openingLibrary = false;
            SetBrowserControlsEnabled(false);
            SetLibrarySwitchingEnabled(true);
            SetLoading(
                "Lattice could not load",
                $"The local interface reported {e.WebErrorStatus}. Try again or choose another library.",
                chooseFolder: true,
                busy: false,
                retry: true);
            SetShellStatus("Load failed", ShellStatus.Attention);
            if (_candidateLaunchRequested && !_candidatePromoted)
            {
                if (_candidatePromotionError is null)
                {
                    RecordCandidatePromotionFailure(
                        "Candidate navigation failed",
                        new InvalidOperationException($"WebView2 reported {e.WebErrorStatus}."));
                }
                ApplyReadyShellStatus();
                NotifyCandidatePromotionFailure();
            }
            if (_launchOptions.SmokeTest is not null)
            {
                await CompleteSmokeTestAsync(
                    navigationSucceeded: false,
                    stage: "navigation",
                    error: $"The local interface reported {e.WebErrorStatus}.");
            }
            return;
        }

        _openingLibrary = false;
        Browser.Visibility = Visibility.Visible;
        Browser.IsEnabled = true;
        LoadingOverlay.Visibility = Visibility.Collapsed;
        SetLibrarySwitchingEnabled(true);
        SetBrowserControlsEnabled(true);
        if (_updateCandidate is not null
            && _candidatePromotionError is null
            && !_candidatePromoted)
        {
            try
            {
                using var interfaceTimeout = CancellationTokenSource.CreateLinkedTokenSource(
                    _lifetime.Token);
                interfaceTimeout.CancelAfter(TimeSpan.FromSeconds(10));
                _ = await WaitForSharedUiAsync(interfaceTimeout.Token);
                var navigatedUri = Browser.Source
                    ?? throw new InvalidOperationException("The candidate WebView did not report its URI.");
                _updateCandidate.ReportWebViewNavigationHealthy(navigatedUri, e.IsSuccess);
                _candidatePromoted = true;
            }
            catch (Exception updateError)
            {
                RecordCandidatePromotionFailure("Candidate activation failed", updateError);
            }
        }
        ApplyReadyShellStatus();
        Browser.Focus();
        NotifyCandidatePromotionFailure();
        if (_launchOptions.SmokeTest is not null)
        {
            await CompleteSmokeTestAsync(
                navigationSucceeded: true,
                stage: "navigation-complete",
                error: null);
        }
        else
        {
            StartBackgroundUpdateCheckOnce();
        }
    }

    private void NewWindowRequested(object? sender, CoreWebView2NewWindowRequestedEventArgs e)
    {
        e.Handled = true;
        if (Uri.TryCreate(e.Uri, UriKind.Absolute, out var uri)
            && !uri.IsLoopback
            && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps))
            Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true });
    }

    private void SetWebContentFullscreen(bool fullscreen)
    {
        if (_webContentFullscreen == fullscreen) return;
        if (fullscreen)
        {
            _webContentFullscreen = true;
            _windowStyleBeforeFullscreen = WindowStyle;
            _resizeModeBeforeFullscreen = ResizeMode;
            _windowStateBeforeFullscreen = WindowState;
            _windowBoundsBeforeFullscreen = WindowState == WindowState.Normal
                ? new Rect(Left, Top, ActualWidth, ActualHeight)
                : RestoreBounds;
            WindowState = WindowState.Normal;
            WindowStyle = WindowStyle.None;
            ResizeMode = ResizeMode.NoResize;
            WindowState = WindowState.Maximized;
            return;
        }

        WindowState = WindowState.Normal;
        WindowStyle = _windowStyleBeforeFullscreen;
        ResizeMode = _resizeModeBeforeFullscreen;
        if (_windowBoundsBeforeFullscreen.Width >= MinWidth
            && _windowBoundsBeforeFullscreen.Height >= MinHeight)
        {
            Left = _windowBoundsBeforeFullscreen.Left;
            Top = _windowBoundsBeforeFullscreen.Top;
            Width = _windowBoundsBeforeFullscreen.Width;
            Height = _windowBoundsBeforeFullscreen.Height;
        }
        WindowState = _windowStateBeforeFullscreen;
        _webContentFullscreen = false;
    }

    private bool IsOwnedServerUri(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri)
            || !Uri.TryCreate(_serverUrl, UriKind.Absolute, out var server)) return false;
        return string.Equals(uri.Scheme, server.Scheme, StringComparison.OrdinalIgnoreCase)
            && string.Equals(uri.Host, server.Host, StringComparison.OrdinalIgnoreCase)
            && uri.Port == server.Port;
    }

    private static bool IsLoopbackHttpUri(Uri uri) =>
        uri.IsLoopback
        && (uri.Scheme == Uri.UriSchemeHttp || uri.Scheme == Uri.UriSchemeHttps);

    private void SetLoading(
        string title,
        string detail,
        bool chooseFolder,
        bool busy = false,
        bool retry = false)
    {
        LoadingTitle.Text = title;
        LoadingDetail.Text = detail;
        LoadingEyebrow.Text = busy ? "PRIVATE · LOCAL · SEARCHABLE" : "LATTICE NEEDS ATTENTION";
        LoadingProgress.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
        RetryButton.Visibility = retry ? Visibility.Visible : Visibility.Collapsed;
        ChooseFolderButton.Visibility = chooseFolder ? Visibility.Visible : Visibility.Collapsed;
        ChooseFolderButton.Margin = retry ? new Thickness(8, 0, 0, 0) : new Thickness(0);
        LoadingActions.Visibility = retry || chooseFolder ? Visibility.Visible : Visibility.Collapsed;
        AutomationProperties.SetName(LoadingCard, $"{title}. {detail}");
        Browser.IsEnabled = false;
        Browser.Visibility = Visibility.Hidden;
        LoadingOverlay.Visibility = Visibility.Visible;
        Dispatcher.BeginInvoke(
            DispatcherPriority.Input,
            new Action(() =>
            {
                if (retry && RetryButton.IsEnabled) RetryButton.Focus();
                else if (chooseFolder && ChooseFolderButton.IsEnabled) ChooseFolderButton.Focus();
                else LoadingCard.Focus();
            }));
    }

    private void SetBrowserControlsEnabled(bool enabled)
    {
        _browserControlsEnabled = enabled;
        PostNativeStatus();
    }

    private void SetLibrarySwitchingEnabled(bool enabled)
    {
        _librarySwitchingEnabled = enabled;
        ChooseFolderButton.IsEnabled = enabled;
        RetryButton.IsEnabled = enabled;
        PostNativeStatus();
    }

    private void SetShellStatus(string text, ShellStatus status)
    {
        _shellStatusText = text;
        _shellStatus = status;
        PostNativeStatus();
    }

    private void RecordCandidatePromotionFailure(string stage, Exception error)
    {
        if (_candidatePromoted) return;
        _candidatePromotionError = $"{stage}. {error.Message}";
        _candidatePromoted = false;
        HideUpdateProgress();
        SetShellStatus("Update not activated", ShellStatus.Attention);
    }

    private void NotifyCandidatePromotionFailure()
    {
        if (!_candidateLaunchRequested
            || string.IsNullOrWhiteSpace(_candidatePromotionError)
            || _candidateErrorNotified
            || !IsLoaded) return;
        _candidateErrorNotified = true;
        Dispatcher.BeginInvoke(
            DispatcherPriority.ApplicationIdle,
            new Action(() => MessageBox.Show(
                this,
                "This update candidate could not finish activation. The current window will stay open, "
                + "and Lattice did not mark this candidate as successfully activated.\n\n"
                + _candidatePromotionError,
                "Update not activated",
                MessageBoxButton.OK,
                MessageBoxImage.Warning)));
    }

    private void ApplyReadyShellStatus()
    {
        if (!string.IsNullOrWhiteSpace(_candidatePromotionError))
        {
            SetShellStatus("Update not activated", ShellStatus.Attention);
        }
        else if (_candidateLaunched)
        {
            SetShellStatus("Verifying update", ShellStatus.Loading);
        }
        else if (_availableUpdate is { State: DesktopUpdateState.Available, LatestVersion: not null } update)
        {
            SetShellStatus($"Update {update.LatestVersion} available", ShellStatus.UpdateAvailable);
        }
        else if (_candidatePromoted && _updateCandidate is not null)
        {
            SetShellStatus($"Version {_updateCandidate.CandidateVersion}", ShellStatus.Ready);
        }
        else
        {
            SetShellStatus("Private local library", ShellStatus.Ready);
        }
    }

    private void StartBackgroundUpdateCheckOnce()
    {
        if (_backgroundUpdateCheckStarted
            || _launchOptions.SmokeTest is not null
            || (_candidateLaunchRequested && !_candidatePromoted)
            || !_updateService.IsAutomaticUpdateSupported) return;
        _backgroundUpdateCheckStarted = true;
        _ = CheckForUpdatesInBackgroundAsync();
    }

    private async Task CheckForUpdatesInBackgroundAsync()
    {
        try
        {
            var update = await GetOrStartUpdateCheckAsync();
            if (update.State != DesktopUpdateState.Available) return;
            _availableUpdate = update;
            ApplyReadyShellStatus();
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
            // The app is closing.
        }
        catch
        {
            // Background checks are intentionally quiet. An interactive check
            // below always reports its result or error.
        }
    }

    private async Task<DesktopUpdateCheck> GetOrStartUpdateCheckAsync()
    {
        var task = _updateCheckTask ??= _updateService.CheckAsync(_lifetime.Token);
        try
        {
            return await task;
        }
        finally
        {
            if (ReferenceEquals(_updateCheckTask, task)) _updateCheckTask = null;
        }
    }

    private void ShowUpdateProgress(bool indeterminate, int value = 0)
    {
        _updateProgressVisible = true;
        _updateProgressIndeterminate = indeterminate;
        _updateProgressValue = Math.Clamp(value, 0, 100);
        UpdateProgress.IsIndeterminate = indeterminate;
        UpdateProgress.Value = _updateProgressValue;
        UpdateProgress.Visibility = Visibility.Visible;
        PostNativeStatus();
    }

    private void HideUpdateProgress()
    {
        _updateProgressVisible = false;
        _updateProgressIndeterminate = false;
        UpdateProgress.IsIndeterminate = false;
        UpdateProgress.Visibility = Visibility.Collapsed;
        PostNativeStatus();
    }

    private void Window_PreviewKeyDown(object sender, KeyEventArgs e)
    {
        var key = e.Key == Key.System ? e.SystemKey : e.Key;
        var modifiers = Keyboard.Modifiers;

        if (key == Key.Left && modifiers == ModifierKeys.Alt
            && _browserControlsEnabled && Browser.CanGoBack)
        {
            Back_Click(this, new RoutedEventArgs());
            e.Handled = true;
        }
        else if (key == Key.Home && modifiers == ModifierKeys.Alt
                 && _browserControlsEnabled && _serverUrl is not null)
        {
            Home_Click(this, new RoutedEventArgs());
            e.Handled = true;
        }
        else if ((key == Key.F5 || (key == Key.R && modifiers == ModifierKeys.Control))
                 && _browserControlsEnabled && Browser.CoreWebView2 is not null)
        {
            Reload_Click(this, new RoutedEventArgs());
            e.Handled = true;
        }
        else if (key == Key.O
                 && modifiers == (ModifierKeys.Control | ModifierKeys.Shift)
                 && _browserControlsEnabled)
        {
            AddMaterials_Click(this, new RoutedEventArgs());
            e.Handled = true;
        }
        else if (key == Key.O && modifiers == ModifierKeys.Control && _libraryRoot is not null)
        {
            OpenFolder_Click(this, new RoutedEventArgs());
            e.Handled = true;
        }
    }

    private void RestoreWindowBounds()
    {
        try
        {
            if (!File.Exists(SavedWindowBoundsPath)) return;
            var saved = JsonSerializer.Deserialize<WindowBoundsState>(
                File.ReadAllText(SavedWindowBoundsPath));
            if (saved is null
                || !double.IsFinite(saved.Left)
                || !double.IsFinite(saved.Top)
                || !double.IsFinite(saved.Width)
                || !double.IsFinite(saved.Height)) return;

            var desktopLeft = SystemParameters.VirtualScreenLeft;
            var desktopTop = SystemParameters.VirtualScreenTop;
            var desktopWidth = SystemParameters.VirtualScreenWidth;
            var desktopHeight = SystemParameters.VirtualScreenHeight;
            if (desktopWidth <= 0 || desktopHeight <= 0) return;

            var maxWidth = Math.Max(MinWidth, desktopWidth - 32);
            var maxHeight = Math.Max(MinHeight, desktopHeight - 32);
            Width = Math.Clamp(saved.Width, MinWidth, maxWidth);
            Height = Math.Clamp(saved.Height, MinHeight, maxHeight);
            Left = Math.Clamp(saved.Left, desktopLeft, desktopLeft + Math.Max(0, desktopWidth - Width));
            Top = Math.Clamp(saved.Top, desktopTop, desktopTop + Math.Max(0, desktopHeight - Height));
            WindowStartupLocation = WindowStartupLocation.Manual;
            if (saved.Maximized) WindowState = WindowState.Maximized;
        }
        catch (Exception error) when (error is IOException
                                      or UnauthorizedAccessException
                                      or JsonException
                                      or NotSupportedException
                                      or ArgumentException)
        {
            // Corrupt or inaccessible cosmetic settings must not block startup.
        }
    }

    private void SaveWindowBounds()
    {
        if (_launchOptions.SmokeTest is not null || _webContentFullscreen) return;
        try
        {
            var bounds = WindowState == WindowState.Normal
                ? new Rect(Left, Top, ActualWidth, ActualHeight)
                : RestoreBounds;
            if (!double.IsFinite(bounds.Left)
                || !double.IsFinite(bounds.Top)
                || !double.IsFinite(bounds.Width)
                || !double.IsFinite(bounds.Height)
                || bounds.Width < MinWidth
                || bounds.Height < MinHeight) return;

            Directory.CreateDirectory(SettingsRoot);
            var saved = new WindowBoundsState(
                bounds.Left,
                bounds.Top,
                bounds.Width,
                bounds.Height,
                WindowState == WindowState.Maximized);
            var json = JsonSerializer.Serialize(saved, new JsonSerializerOptions { WriteIndented = true });
            var temporaryPath = SavedWindowBoundsPath + ".tmp";
            File.WriteAllText(temporaryPath, json + Environment.NewLine);
            File.Move(temporaryPath, SavedWindowBoundsPath, overwrite: true);
        }
        catch (Exception error) when (error is IOException
                                      or UnauthorizedAccessException
                                      or NotSupportedException)
        {
            // Window persistence is best-effort and never library-critical.
        }
    }

    private async Task CompleteSmokeTestAsync(
        bool navigationSucceeded,
        string stage,
        string? error)
    {
        var smoke = _launchOptions.SmokeTest;
        if (smoke is null || _smokeCompleted) return;
        _smokeCompleted = true;
        _smokeTimer?.Stop();

        var finalStage = stage;
        var finalError = error;
        var screenshotCaptured = false;
        var pdfScreenshotCaptured = false;
        var ok = false;
        SmokeWebProbe? probe = null;
        SmokePdfProbe? pdfProbe = null;

        try
        {
            var outputDirectory = Path.GetDirectoryName(smoke.ReportPath)
                ?? throw new InvalidOperationException("The smoke output directory is invalid.");
            Directory.CreateDirectory(outputDirectory);

            if (navigationSucceeded)
            {
                using var verificationTimeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
                probe = await WaitForSharedUiAsync(verificationTimeout.Token);
                await Task.Delay(250, verificationTimeout.Token);
                await using var screenshot = new FileStream(
                    smoke.ScreenshotPath,
                    FileMode.Create,
                    FileAccess.Write,
                    FileShare.None);
                await Browser.CoreWebView2.CapturePreviewAsync(
                        CoreWebView2CapturePreviewImageFormat.Png,
                        screenshot)
                    .WaitAsync(verificationTimeout.Token);
                await screenshot.FlushAsync(verificationTimeout.Token);
                screenshotCaptured = true;
                if (!string.IsNullOrWhiteSpace(smoke.PdfPath))
                {
                    pdfProbe = await WaitForPdfReaderAsync(
                        smoke.PdfPath,
                        verificationTimeout.Token);
                    await using var pdfScreenshot = new FileStream(
                        smoke.PdfScreenshotPath,
                        FileMode.Create,
                        FileAccess.Write,
                        FileShare.None);
                    await Browser.CoreWebView2.CapturePreviewAsync(
                            CoreWebView2CapturePreviewImageFormat.Png,
                            pdfScreenshot)
                        .WaitAsync(verificationTimeout.Token);
                    await pdfScreenshot.FlushAsync(verificationTimeout.Token);
                    pdfScreenshotCaptured = true;
                    pdfProbe.ShelfReturnWorked = await WaitForPdfShelfReturnAsync(
                        verificationTimeout.Token);
                }
                ok = pdfProbe?.Ready ?? true;
                finalStage = "ready";
                finalError = null;
            }

            var report = new
            {
                schemaVersion = 1,
                ok,
                application = "Lattice",
                shell = "Windows WPF",
                stage = finalStage,
                error = finalError,
                capturedAtUtc = DateTimeOffset.UtcNow,
                library = new
                {
                    explicitRoot = true,
                    rootName = new DirectoryInfo(smoke.Root).Name,
                    catalogPresent = File.Exists(Path.Combine(smoke.Root, "CATALOG.md")),
                    taxonomyPresent = File.Exists(Path.Combine(smoke.Root, "library-taxonomy.json")),
                },
                window = new
                {
                    loaded = IsLoaded,
                    title = Title,
                    width = Math.Round(ActualWidth),
                    height = Math.Round(ActualHeight),
                    status = _shellStatusText,
                },
                web = probe,
                pdf = pdfProbe,
                screenshot = screenshotCaptured ? Path.GetFileName(smoke.ScreenshotPath) : null,
                pdfScreenshot = pdfScreenshotCaptured
                    ? Path.GetFileName(smoke.PdfScreenshotPath)
                    : null,
                captureKind = screenshotCaptured ? "WebView2 content preview" : null,
            };
            var json = JsonSerializer.Serialize(
                report,
                new JsonSerializerOptions
                {
                    WriteIndented = true,
                    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
                });
            await File.WriteAllTextAsync(smoke.ReportPath, json + Environment.NewLine);
        }
        catch (Exception smokeError)
        {
            ok = false;
            finalStage = "verification";
            finalError = smokeError.Message;
            try
            {
                var outputDirectory = Path.GetDirectoryName(smoke.ReportPath);
                if (!string.IsNullOrWhiteSpace(outputDirectory))
                {
                    Directory.CreateDirectory(outputDirectory);
                    var failure = JsonSerializer.Serialize(
                        new
                        {
                            schemaVersion = 1,
                            ok = false,
                            application = "Lattice",
                            shell = "Windows WPF",
                            stage = finalStage,
                            error = finalError,
                            capturedAtUtc = DateTimeOffset.UtcNow,
                        },
                        new JsonSerializerOptions { WriteIndented = true });
                    await File.WriteAllTextAsync(smoke.ReportPath, failure + Environment.NewLine);
                }
            }
            catch (Exception reportError) when (reportError is IOException
                                                or UnauthorizedAccessException
                                                or NotSupportedException
                                                or ArgumentException
                                                or JsonException)
            {
                // The nonzero process exit remains the proof when the requested
                // artifact directory itself cannot be written.
            }
        }

        var exitCode = ok ? 0 : 1;
        Environment.ExitCode = exitCode;
        Application.Current.Shutdown(exitCode);
    }

    private async Task<SmokeWebProbe> WaitForSharedUiAsync(CancellationToken cancellationToken)
    {
        const string script = """
            (() => {
              const brand = document.querySelector(".brand strong")?.textContent?.trim() || "";
              const syncText = document.getElementById("syncText")?.textContent?.trim() || "";
              const hasAddButton = Boolean(document.getElementById("addButton"));
              const hasLibraryGrid = Boolean(document.getElementById("libraryGrid"));
              const hasNativeAddBridge = typeof window.sharedLibraryChooseFiles === "function";
              const hasNativeDesktopBridge = typeof window.csLibraryNativeCall === "function";
              const inlineDesktopMenu = document.getElementById("nativeAppMenu");
              const hasInlineDesktopMenu = Boolean(inlineDesktopMenu && !inlineDesktopMenu.hidden);
              const connected = syncText === "Live sync" || syncText === "Auto refresh";
              return {
                ready: document.readyState === "complete"
                  && brand === "Lattice"
                  && hasAddButton
                  && hasLibraryGrid
                  && hasNativeAddBridge
                  && hasNativeDesktopBridge
                  && hasInlineDesktopMenu
                  && connected,
                readyState: document.readyState,
                title: document.title,
                brand,
                syncText,
                hasAddButton,
                hasLibraryGrid,
                hasNativeAddBridge,
                hasNativeDesktopBridge,
                hasInlineDesktopMenu
              };
            })()
            """;
        var jsonOptions = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
        SmokeWebProbe? lastProbe = null;
        Exception? lastError = null;
        for (var attempt = 0; attempt < 40; attempt++)
        {
            try
            {
                var raw = await Browser.CoreWebView2.ExecuteScriptAsync(script)
                    .WaitAsync(cancellationToken);
                lastProbe = JsonSerializer.Deserialize<SmokeWebProbe>(raw, jsonOptions);
                if (lastProbe?.Ready == true) return lastProbe;
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw new TimeoutException(
                    "The shared Lattice interface did not become ready within 10 seconds.");
            }
            catch (Exception error)
            {
                lastError = error;
            }
            await Task.Delay(200, cancellationToken);
        }

        var detail = lastProbe is null
            ? lastError?.Message ?? "No page state was returned."
            : $"readyState={lastProbe.ReadyState}, brand={lastProbe.Brand}, sync={lastProbe.SyncText}, "
                + $"add={lastProbe.HasAddButton}, grid={lastProbe.HasLibraryGrid}, bridge={lastProbe.HasNativeAddBridge}";
        throw new InvalidOperationException($"The shared Lattice interface was not ready. {detail}");
    }

    private async Task<SmokePdfProbe> WaitForPdfReaderAsync(
        string relativePath,
        CancellationToken cancellationToken)
    {
        var pathJson = JsonSerializer.Serialize(relativePath);
        const string scriptTemplate = """
            (() => {
              const requestedPath = __PDF_PATH__;
              if (!window.__latticePdfSmokeOpened) {
                const material = state.library?.materials?.find(item => item.path === requestedPath);
                const work = material ? state.workById.get(material.workId) : null;
                if (!material || !work) {
                  return { ready: false, error: "Smoke PDF is not in the library inventory." };
                }
                window.__latticePdfSmokeOpened = true;
                showPdfReader(work, material);
              }
              const frame = document.getElementById("pdfReader");
              const frameDocument = frame?.contentDocument;
              const frameRect = frame?.getBoundingClientRect();
              if (!frameDocument) {
                return { ready: false, error: "PDF reader frame has not loaded." };
              }
              const app = frameDocument.getElementById("pdfApp");
              // Be specific: once spread mode is active the document root also
              // has data-layout="spread", but only the toolbar button exposes
              // aria-pressed and accepts the mode-selection click.
              const single = frameDocument.querySelector('button[data-layout="single"]');
              const spread = frameDocument.querySelector('button[data-layout="spread"]');
              const pageInput = frameDocument.getElementById("pageNumberInput");
              if (app?.dataset.ready === "true" && !frame.dataset.smokeArrow) {
                single?.click();
                pageInput.value = "1";
                pageInput.dispatchEvent(new Event("change", { bubbles: true }));
                frameDocument.dispatchEvent(new KeyboardEvent("keydown", {
                  key: "ArrowRight",
                  bubbles: true
                }));
                frame.dataset.smokeArrow = String(Number(pageInput.value) === 2);
                frameDocument.dispatchEvent(new KeyboardEvent("keydown", {
                  key: "ArrowLeft",
                  bubbles: true
                }));
              }
              const arrowNavigationWorked = frame.dataset.smokeArrow === "true";
              if (app?.dataset.ready === "true"
                  && arrowNavigationWorked
                  && frame.dataset.smokeSpread !== "true") {
                frame.dataset.smokeSpread = "true";
                spread?.click();
              }
              const visibleCanvases = [...frameDocument.querySelectorAll(".page canvas")]
                .filter(canvas => {
                  const rect = canvas.getBoundingClientRect();
                  return rect.width > 0 && rect.height > 0
                    && rect.bottom > 0 && rect.top < frameDocument.documentElement.clientHeight;
                }).length;
              const pageCount = Number(frameDocument.documentElement.dataset.pageCount || 0);
              const spreadActive = spread?.getAttribute("aria-pressed") === "true";
              return {
                ready: app?.dataset.ready === "true"
                  && pageCount === 2
                  && arrowNavigationWorked
                  && spreadActive
                  && visibleCanvases === 2
                  && (frameRect?.height || 0) > 300,
                error: "",
                pageCount,
                layout: frameDocument.documentElement.dataset.layout || "",
                arrowNavigationWorked,
                spreadActive,
                visibleCanvases,
                frameHeight: Math.round(frameRect?.height || 0),
                hasSearch: Boolean(frameDocument.getElementById("findInput")),
                hasFullscreen: Boolean(frameDocument.getElementById("fullscreenButton")),
                allowsFullscreen: frame?.getAttribute("allow")?.includes("fullscreen") === true,
                status: frameDocument.getElementById("statusText")?.textContent?.trim() || ""
              };
            })()
            """;
        var script = scriptTemplate.Replace("__PDF_PATH__", pathJson, StringComparison.Ordinal);
        var jsonOptions = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
        SmokePdfProbe? lastProbe = null;
        Exception? lastError = null;
        for (var attempt = 0; attempt < 60; attempt++)
        {
            try
            {
                var raw = await Browser.CoreWebView2.ExecuteScriptAsync(script)
                    .WaitAsync(cancellationToken);
                lastProbe = JsonSerializer.Deserialize<SmokePdfProbe>(raw, jsonOptions);
                if (lastProbe?.Ready == true) return lastProbe;
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw new TimeoutException("The bundled PDF reader did not become ready within the allotted time.");
            }
            catch (Exception error)
            {
                lastError = error;
            }
            await Task.Delay(200, cancellationToken);
        }
        var detail = lastProbe?.Error;
        if (string.IsNullOrWhiteSpace(detail))
        {
            detail = lastProbe is null
                ? lastError?.Message ?? "No PDF reader state was returned."
                : $"pages={lastProbe.PageCount}, layout={lastProbe.Layout}, "
                    + $"arrows={lastProbe.ArrowNavigationWorked}, "
                    + $"spread={lastProbe.SpreadActive}, canvases={lastProbe.VisibleCanvases}, "
                    + $"height={lastProbe.FrameHeight}";
        }
        throw new InvalidOperationException($"The bundled PDF reader was not ready. {detail}");
    }

    private async Task<bool> WaitForPdfShelfReturnAsync(CancellationToken cancellationToken)
    {
        const string script = """
            (() => {
              const frame = document.getElementById("pdfReader");
              if (!window.__latticePdfSmokeCloseClicked) {
                const close = frame?.contentDocument?.getElementById("closeButton");
                if (!close) {
                  return { ready: false, error: "The PDF reader Shelf control is missing." };
                }
                window.__latticePdfSmokeCloseClicked = true;
                close.click();
              }
              const shell = document.getElementById("readerShell");
              const shelf = document.getElementById("libraryGrid");
              const shellHidden = shell?.getAttribute("aria-hidden") === "true"
                && !document.body.classList.contains("reader-open");
              const frameReset = frame?.hidden === true
                && (frame.getAttribute("src") === "about:blank" || frame.src === "about:blank");
              const shelfPresent = Boolean(shelf && shelf.getClientRects().length);
              return {
                ready: shellHidden && frameReset && shelfPresent,
                error: "",
                shellHidden,
                frameReset,
                shelfPresent
              };
            })()
            """;
        var jsonOptions = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
        SmokeShelfProbe? lastProbe = null;
        Exception? lastError = null;
        for (var attempt = 0; attempt < 30; attempt++)
        {
            try
            {
                var raw = await Browser.CoreWebView2.ExecuteScriptAsync(script)
                    .WaitAsync(cancellationToken);
                lastProbe = JsonSerializer.Deserialize<SmokeShelfProbe>(raw, jsonOptions);
                if (lastProbe?.Ready == true) return true;
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
            {
                throw new TimeoutException(
                    "The PDF reader did not return to the shelf within the allotted time.");
            }
            catch (Exception error)
            {
                lastError = error;
            }
            await Task.Delay(100, cancellationToken);
        }

        var detail = lastProbe is null
            ? lastError?.Message ?? "No shelf state was returned."
            : $"hidden={lastProbe.ShellHidden}, reset={lastProbe.FrameReset}, "
                + $"shelf={lastProbe.ShelfPresent}, error={lastProbe.Error}";
        throw new InvalidOperationException($"The PDF reader did not return to the shelf. {detail}");
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

    private async void CheckForUpdates_Click(object sender, RoutedEventArgs e)
    {
        if (_updateOperationInProgress
            || (_candidateLaunchRequested && !_candidatePromoted)
            || _candidateLaunched) return;
        _updateOperationInProgress = true;
        ShowUpdateProgress(indeterminate: true);
        SetShellStatus("Checking for updates", ShellStatus.Loading);

        try
        {
            var update = _availableUpdate ?? await GetOrStartUpdateCheckAsync();
            switch (update.State)
            {
                case DesktopUpdateState.NotInstalled:
                    MessageBox.Show(
                        this,
                        update.Message
                            ?? "Automatic updates are available after Lattice is installed for this Windows account.",
                        "Updates unavailable",
                        MessageBoxButton.OK,
                        MessageBoxImage.Information);
                    ApplyReadyShellStatus();
                    return;
                case DesktopUpdateState.Current:
                    MessageBox.Show(
                        this,
                        update.Message
                            ?? $"Lattice {update.InstalledVersion ?? "this version"} is current.",
                        "Lattice is up to date",
                        MessageBoxButton.OK,
                        MessageBoxImage.Information);
                    ApplyReadyShellStatus();
                    return;
                case DesktopUpdateState.Available:
                    _availableUpdate = update;
                    break;
                default:
                    throw new InvalidDataException("The update service returned an unknown state.");
            }

            var latestVersion = update.LatestVersion
                ?? throw new InvalidDataException("The available update has no version.");
            HideUpdateProgress();
            ApplyReadyShellStatus();
            var consent = MessageBox.Show(
                this,
                $"Lattice {latestVersion} is available.\n\n"
                + "Lattice will download the signed Windows package, verify its signature and SHA-256, "
                + "then open it as an isolated candidate. This window closes automatically only after "
                + "the new version proves its local service and interface are healthy.\n\nDownload and open the update?",
                $"Update to Lattice {latestVersion}",
                MessageBoxButton.YesNo,
                MessageBoxImage.Information,
                MessageBoxResult.No);
            if (consent != MessageBoxResult.Yes)
            {
                ApplyReadyShellStatus();
                return;
            }

            ShowUpdateProgress(indeterminate: false);
            SetShellStatus($"Downloading update 0%", ShellStatus.Loading);
            var progress = new Progress<int>(value =>
            {
                if (!_updateOperationInProgress) return;
                var percent = Math.Clamp(value, 0, 100);
                ShowUpdateProgress(indeterminate: false, value: percent);
                SetShellStatus($"Downloading update {percent}%", ShellStatus.Loading);
            });
            var staged = _stagedUpdate;
            if (staged is null
                || !string.Equals(staged.Version, latestVersion, StringComparison.Ordinal))
            {
                staged = await _updateService.DownloadAndStageAsync(
                    update,
                    progress,
                    _lifetime.Token);
                _stagedUpdate = staged;
            }

            ShowUpdateProgress(indeterminate: false, value: 100);
            SetShellStatus($"Opening Lattice {latestVersion}", ShellStatus.Loading);
            using (_updateService.LaunchCandidate(staged, _libraryRoot))
            {
                // Disposing the Process handle does not close the candidate.
            }
            _candidateLaunched = true;
            SetShellStatus($"Verifying Lattice {latestVersion}", ShellStatus.Loading);
        }
        catch (OperationCanceledException) when (_lifetime.IsCancellationRequested)
        {
            // The app is closing.
        }
        catch (Exception updateError)
        {
            SetShellStatus("Update failed", ShellStatus.Attention);
            MessageBox.Show(
                this,
                "Lattice did not install or activate an update. " + updateError.Message,
                "Update failed",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
        finally
        {
            _updateOperationInProgress = false;
            HideUpdateProgress();
            ApplyReadyShellStatus();
        }
    }

    private async void Retry_Click(object sender, RoutedEventArgs e)
    {
        if (_openingLibrary || _libraryRoot is null) return;
        await OpenLibraryAsync(_libraryRoot);
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

    private async void MoveLibrary_Click(object sender, RoutedEventArgs e)
    {
        if (_openingLibrary || _libraryMoveInProgress || _libraryRoot is null) return;
        if (_serverProcess is null || _serverProcess.HasExited)
        {
            MessageBox.Show(
                this,
                "Move Library requires the private local service owned by this window. Reopen Lattice, then try again.",
                "Move Library",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }
        if (_updateOperationInProgress || _candidateLaunched)
        {
            MessageBox.Show(
                this,
                "Wait for the current update operation to finish before moving the library.",
                "Move Library",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }
        var source = Path.GetFullPath(_libraryRoot);
        var picker = new OpenFolderDialog
        {
            Title = "Choose the external drive or folder for your Lattice library",
            Multiselect = false,
        };
        if (picker.ShowDialog(this) != true) return;
        var destination = LibraryMoveClient.DestinationForContainer(picker.FolderName);
        if (Directory.Exists(destination) || File.Exists(destination))
        {
            MessageBox.Show(
                this,
                $"The destination already contains '{destination}'. Choose another folder or rename the existing one.",
                "Move Library",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            return;
        }

        var consent = MessageBox.Show(
            this,
            $"Move the complete Lattice library to:\n\n{destination}\n\n"
            + "Lattice will require Syncthing to be Up to Date, pause it, copy and verify every file, "
            + "redirect the same Syncthing folder ID, and only then remove the old copy. Keep the drive "
            + "connected until Lattice reopens.\n\nContinue?",
            "Move Library",
            MessageBoxButton.YesNo,
            MessageBoxImage.Information,
            MessageBoxResult.No);
        if (consent != MessageBoxResult.Yes) return;

        _libraryMoveInProgress = true;
        _openingLibrary = true;
        SetBrowserControlsEnabled(false);
        SetLibrarySwitchingEnabled(false);
        SetLoading(
            "Moving your library…",
            "Pausing Syncthing and preparing a verified copy",
            chooseFolder: false,
            busy: true);
        SetShellStatus("Moving library", ShellStatus.Loading);
        StopOwnedServer();
        _serverUrl = null;

        LibraryMoveOutcome? outcome = null;
        Exception? failure = null;
        try
        {
            var progress = new Progress<LibraryMoveProgress>(update =>
            {
                LoadingDetail.Text = update.Message;
                SetShellStatus(
                    update.Percent is int percent ? $"Moving library {percent}%" : "Moving library",
                    ShellStatus.Loading);
            });
            outcome = await LibraryMoveClient.MoveAsync(source, destination, progress);
        }
        catch (Exception error)
        {
            failure = error;
        }
        finally
        {
            _libraryMoveInProgress = false;
            _openingLibrary = false;
        }

        if (outcome is null)
        {
            MessageBox.Show(
                this,
                "The original library was preserved. "
                + (failure?.Message ?? "The storage helper did not complete."),
                "Library move stopped",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            if (IsLibrary(source))
            {
                await OpenLibraryAsync(source);
            }
            else
            {
                SetLoading(
                    "Choose your library folder",
                    "The original location is unavailable. Select the verified library copy to continue.",
                    chooseFolder: true);
                SetLibrarySwitchingEnabled(true);
            }
            return;
        }

        await OpenLibraryAsync(outcome.Destination);
        var detail = outcome.SyncthingManaged
            ? "Lattice and Syncthing now use the library on the selected drive."
            : "Lattice now uses the library on the selected drive. This library was not managed by Syncthing.";
        if (!string.IsNullOrWhiteSpace(outcome.Warning)) detail += "\n\n" + outcome.Warning;
        MessageBox.Show(
            this,
            detail,
            "Library moved",
            MessageBoxButton.OK,
            outcome.Warning is null ? MessageBoxImage.Information : MessageBoxImage.Warning);
    }

    private async void DisconnectLibrary_Click(object sender, RoutedEventArgs e)
    {
        if (_openingLibrary
            || _libraryMoveInProgress
            || _libraryDriveOperationInProgress
            || _libraryRoot is null) return;
        if (_updateOperationInProgress || _candidateLaunched)
        {
            MessageBox.Show(
                this,
                "Wait for the current update operation to finish before disconnecting the library drive.",
                "Disconnect library drive",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }
        if (_serverProcess is null || _serverProcess.HasExited)
        {
            MessageBox.Show(
                this,
                "Reopen Lattice before disconnecting the library drive so it can release its own local service safely.",
                "Disconnect library drive",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        var source = Path.GetFullPath(_libraryRoot);
        var consent = MessageBox.Show(
            this,
            "Prepare this library drive for safe eject?\n\n"
            + "Lattice will stop its private local service, require Syncthing to be Up to Date, and pause only "
            + "the Lattice folder. This window will close when both programs have released the drive. "
            + "Then use Eject in Windows.\n\n"
            + "When the drive is connected again, open Lattice and choose Reconnect library sync.",
            "Disconnect library drive",
            MessageBoxButton.YesNo,
            MessageBoxImage.Information,
            MessageBoxResult.No);
        if (consent != MessageBoxResult.Yes) return;

        _libraryDriveOperationInProgress = true;
        _openingLibrary = true;
        SetBrowserControlsEnabled(false);
        SetLibrarySwitchingEnabled(false);
        SetLoading(
            "Releasing the library drive…",
            "Stopping Lattice's local service and pausing its Syncthing folder",
            chooseFolder: false,
            busy: true);
        SetShellStatus("Releasing library drive", ShellStatus.Loading);
        StopOwnedServer();
        _serverUrl = null;

        LibraryDisconnectOutcome? outcome = null;
        Exception? failure = null;
        try
        {
            var progress = new Progress<LibraryMoveProgress>(update =>
            {
                LoadingDetail.Text = update.Message;
            });
            outcome = await LibraryMoveClient.DisconnectAsync(
                source,
                LibraryDisconnectStatePath,
                progress);
        }
        catch (Exception error)
        {
            failure = error;
        }

        if (outcome is null)
        {
            _libraryDriveOperationInProgress = false;
            _openingLibrary = false;
            MessageBox.Show(
                this,
                "The drive was not marked ready to eject. "
                + (failure?.Message ?? "The storage helper did not complete."),
                "Drive still connected",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
            if (IsLibrary(source))
            {
                await OpenLibraryAsync(source);
            }
            else
            {
                SetLoading(
                    "Choose your library folder",
                    "The external drive is unavailable. Reconnect it or choose another library to continue.",
                    chooseFolder: true);
                SetLibrarySwitchingEnabled(true);
            }
            return;
        }

        var detail = outcome.SyncthingManaged
            ? (outcome.SyncthingRunning
                ? "Syncthing has released the Lattice folder and Lattice's local service is stopped."
                : "Syncthing was already stopped, and Lattice's local service is now stopped.")
            : "Lattice's local service is stopped. This library is not managed by Syncthing.";
        detail += "\n\nAfter this window closes, eject the drive from Windows before unplugging it.";
        MessageBox.Show(
            this,
            detail,
            "Library drive is ready",
            MessageBoxButton.OK,
            MessageBoxImage.Information);
        _libraryDriveOperationInProgress = false;
        _openingLibrary = false;
        Application.Current.Shutdown();
    }

    private async void ReconnectLibrary_Click(object sender, RoutedEventArgs e)
    {
        if (_openingLibrary
            || _libraryMoveInProgress
            || _libraryDriveOperationInProgress
            || _libraryRoot is null) return;
        if (_updateOperationInProgress || _candidateLaunched)
        {
            MessageBox.Show(
                this,
                "Wait for the current update operation to finish before reconnecting library sync.",
                "Reconnect library sync",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }

        _libraryDriveOperationInProgress = true;
        SetLibrarySwitchingEnabled(false);
        SetShellStatus("Reconnecting library sync", ShellStatus.Loading);
        try
        {
            var outcome = await LibraryMoveClient.ReconnectAsync(
                _libraryRoot,
                LibraryDisconnectStatePath,
                startIfNeeded: true);
            var detail = !outcome.SyncthingManaged
                ? "This library is not managed by Syncthing. No sync setting was changed."
                : outcome.ResumedByLattice
                    ? "Lattice resumed the folder pause it created. The library is synchronized again."
                    : outcome.SyncthingStarted
                        ? "The dedicated Lattice Syncthing instance is back online. Its existing folder pause setting was preserved."
                        : "Syncthing is online. Its existing folder pause setting was preserved.";
            MessageBox.Show(
                this,
                detail,
                "Library sync connected",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
        }
        catch (Exception error)
        {
            MessageBox.Show(
                this,
                "Lattice could not reconnect Syncthing. " + error.Message,
                "Reconnect library sync",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
        finally
        {
            _libraryDriveOperationInProgress = false;
            SetLibrarySwitchingEnabled(true);
            ApplyReadyShellStatus();
        }
    }

    private async void ChangeLibrary_Click(object sender, RoutedEventArgs e)
    {
        if (_openingLibrary) return;
        var root = ChooseLibrary();
        if (root is not null) await OpenLibraryAsync(root);
    }

    private void Window_Closing(object? sender, CancelEventArgs e)
    {
        if (_libraryMoveInProgress || _libraryDriveOperationInProgress)
        {
            e.Cancel = true;
            MessageBox.Show(
                this,
                _libraryMoveInProgress
                    ? "Lattice is still copying and verifying the library. Keep this window and the destination drive open until it finishes."
                    : "Lattice is still changing the Syncthing state for this drive. Keep this window open until it finishes.",
                _libraryMoveInProgress ? "Library move in progress" : "Library drive operation in progress",
                MessageBoxButton.OK,
                MessageBoxImage.Information);
            return;
        }
        _smokeTimer?.Stop();
        SaveWindowBounds();
        _lifetime.Cancel();
        StopOwnedServer();
        Browser.Dispose();
        _lifetime.Dispose();
    }

    private enum ShellStatus
    {
        Loading,
        Ready,
        UpdateAvailable,
        Attention,
    }

    private sealed class WindowBoundsState
    {
        public WindowBoundsState()
        {
        }

        public WindowBoundsState(double left, double top, double width, double height, bool maximized)
        {
            Left = left;
            Top = top;
            Width = width;
            Height = height;
            Maximized = maximized;
        }

        public double Left { get; init; }
        public double Top { get; init; }
        public double Width { get; init; }
        public double Height { get; init; }
        public bool Maximized { get; init; }
    }

    private sealed class SmokeWebProbe
    {
        public SmokeWebProbe()
        {
        }

        public bool Ready { get; init; }
        public string ReadyState { get; init; } = "";
        public string Title { get; init; } = "";
        public string Brand { get; init; } = "";
        public string SyncText { get; init; } = "";
        public bool HasAddButton { get; init; }
        public bool HasLibraryGrid { get; init; }
        public bool HasNativeAddBridge { get; init; }
        public bool HasNativeDesktopBridge { get; init; }
        public bool HasInlineDesktopMenu { get; init; }
    }

    private sealed class SmokePdfProbe
    {
        public SmokePdfProbe()
        {
        }

        public bool Ready { get; init; }
        public string Error { get; init; } = "";
        public int PageCount { get; init; }
        public string Layout { get; init; } = "";
        public bool ArrowNavigationWorked { get; init; }
        public bool SpreadActive { get; init; }
        public int VisibleCanvases { get; init; }
        public int FrameHeight { get; init; }
        public bool HasSearch { get; init; }
        public bool HasFullscreen { get; init; }
        public bool AllowsFullscreen { get; init; }
        public bool ShelfReturnWorked { get; set; }
        public string Status { get; init; } = "";
    }

    private sealed class SmokeShelfProbe
    {
        public bool Ready { get; init; }
        public string Error { get; init; } = "";
        public bool ShellHidden { get; init; }
        public bool FrameReset { get; init; }
        public bool ShelfPresent { get; init; }
    }
}
