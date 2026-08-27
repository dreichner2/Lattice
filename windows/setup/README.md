# Lattice Windows onboarding

This setup installs Lattice for the current Windows user, installs the official
Syncthing 2.1.3 package through WinGet when needed, and configures this clone as
the `cs-library-3b8290f24f15` send-receive folder. Syncthing's certificates,
database, and API key stay in `%LOCALAPPDATA%\Syncthing`, outside the clone.
The stable app root is `%LOCALAPPDATA%\Programs\Lattice`; the active runtime is
resolved through `active-version.json` under `versions\<version>` so automatic
updates can switch versions safely.

## One click

Clone the repository, then double-click:

```text
windows\setup\Install Lattice and Connect.cmd
```

The default setup downloads the pinned public GitHub Release asset
`v2.4.2/Lattice-Windows-win-x64.zip` and its `.sha256` companion. It refuses to
install unless the SHA-256 matches. It does not download a GitHub Actions
artifact and does not need a GitHub token.

The equivalent PowerShell command, run from the clone root, is:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\setup\Setup-LatticeWindows.ps1
```

Preview every target without downloading, installing, starting, or changing
anything:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\setup\Setup-LatticeWindows.ps1 -PlanOnly
```

For an offline or test install, pass an extracted package directory or ZIP. A
neighboring `<package>.zip.sha256` file is verified automatically when present:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\setup\Setup-LatticeWindows.ps1 `
  -Offline `
  -LatticePackagePath C:\Installers\Lattice-Windows-win-x64.zip `
  -SyncthingExecutable C:\Installers\Syncthing\syncthing.exe
```

Useful switches are `-NoLaunch`, `-ReinstallLattice`, `-SyncthingHome`, and
`-InstallDestination`. If Lattice already has a different valid clone saved,
setup stops rather than silently replacing it; use `-ReplaceSavedLibraryRoot`
only when that change is intentional.

## The one unavoidable manual step

The script prints this PC's Syncthing Device ID and copies only that non-secret
ID to the clipboard when Windows provides `Set-Clipboard`. Device IDs are not
passwords, but exchange the ID privately. On the Mac mini hub, approve that
Windows Device ID and share the existing **Lattice** folder with it. The Windows
script cannot and does not use the hub's GUI credentials, so it cannot approve
itself.

Both computers must be online together to transfer files. After the first
approval, Syncthing resumes automatically whenever the Windows user signs in;
the Mac mini's machine service remains independent of which desktop account is
active.

Setup does not change Windows Firewall. If Windows asks about `syncthing.exe`,
allow **Private networks** only when this is a trusted home network; relay-based
sync can still use outbound connections without opening a public-network rule.
