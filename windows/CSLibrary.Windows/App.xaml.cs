using System.Windows;

namespace CSLibrary.Windows;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (UpdateInstaller.IsInstallerInvocation(e.Args))
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown;
            var exitCode = UpdateInstaller.Run(e.Args);
            Shutdown(exitCode);
            return;
        }

        var window = new MainWindow();
        MainWindow = window;
        window.Show();
        UpdateService.FinalizeSuccessfulUpdate();
        var installerError = UpdateService.TakeInstallerError();
        if (!string.IsNullOrWhiteSpace(installerError))
        {
            MessageBox.Show(
                window,
                installerError,
                "Lattice update",
                MessageBoxButton.OK,
                MessageBoxImage.Warning);
        }
    }
}
