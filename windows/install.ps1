param(
  [string]$Destination = (Join-Path $env:LOCALAPPDATA "Programs\CS Library")
)

$ErrorActionPreference = "Stop"
$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item $Destination -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $Source "*") $Destination -Recurse -Force

$Executable = Join-Path $Destination "CS Library.exe"
$Shell = New-Object -ComObject WScript.Shell
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$Shortcut = $Shell.CreateShortcut((Join-Path $StartMenu "CS Library.lnk"))
$Shortcut.TargetPath = $Executable
$Shortcut.WorkingDirectory = $Destination
$Shortcut.IconLocation = "$Executable,0"
$Shortcut.Save()

Write-Host "Installed CS Library to $Destination"
Start-Process $Executable
