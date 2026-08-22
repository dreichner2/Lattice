param(
  [string]$Destination = (Join-Path $env:LOCALAPPDATA "Programs\Lattice"),
  [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceExecutable = Join-Path $Source "Lattice.exe"
$SourceIcon = Join-Path $Source "Lattice.ico"

function Assert-LatticeIcon([string]$Path) {
  if (-not (Test-Path $Path)) { throw "Lattice.ico is missing from the package" }
  $Bytes = [IO.File]::ReadAllBytes($Path)
  if (
    $Bytes.Length -lt 6 -or
    $Bytes[0] -ne 0 -or $Bytes[1] -ne 0 -or
    $Bytes[2] -ne 1 -or $Bytes[3] -ne 0 -or
    [BitConverter]::ToUInt16($Bytes, 4) -lt 1
  ) { throw "Lattice.ico is not a valid Windows icon" }
}

function Assert-EmbeddedLatticeIcon([string]$ExecutablePath, [string]$IconPath) {
  try {
    Add-Type -AssemblyName System.Drawing.Common
  } catch {
    Add-Type -AssemblyName System.Drawing
  }
  $Embedded = [System.Drawing.Icon]::ExtractAssociatedIcon($ExecutablePath)
  if ($null -eq $Embedded) { throw "Lattice.exe has no embedded application icon" }
  $Expected = $null
  $EmbeddedBitmap = $null
  $ExpectedBitmap = $null
  try {
    $Expected = [System.Drawing.Icon]::new($IconPath, $Embedded.Width, $Embedded.Height)
    $EmbeddedBitmap = $Embedded.ToBitmap()
    $ExpectedBitmap = $Expected.ToBitmap()
    if ($EmbeddedBitmap.Width -ne $ExpectedBitmap.Width -or $EmbeddedBitmap.Height -ne $ExpectedBitmap.Height) {
      throw "The embedded Lattice icon has the wrong dimensions"
    }
    for ($y = 0; $y -lt $EmbeddedBitmap.Height; $y++) {
      for ($x = 0; $x -lt $EmbeddedBitmap.Width; $x++) {
        if ($EmbeddedBitmap.GetPixel($x, $y).ToArgb() -ne $ExpectedBitmap.GetPixel($x, $y).ToArgb()) {
          throw "The icon embedded in Lattice.exe does not match Lattice.ico"
        }
      }
    }
  } finally {
    if ($ExpectedBitmap) { $ExpectedBitmap.Dispose() }
    if ($EmbeddedBitmap) { $EmbeddedBitmap.Dispose() }
    if ($Expected) { $Expected.Dispose() }
    $Embedded.Dispose()
  }
}

if (-not (Test-Path $SourceExecutable)) { throw "Lattice.exe is missing from the package" }
Assert-LatticeIcon $SourceIcon
New-Item $Destination -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $Source "*") $Destination -Recurse -Force

$Executable = Join-Path $Destination "Lattice.exe"
$Icon = Join-Path $Destination "Lattice.ico"
if (-not (Test-Path $Executable)) { throw "Lattice.exe was not installed" }
Assert-LatticeIcon $Icon
Assert-EmbeddedLatticeIcon $Executable $Icon
$Shell = New-Object -ComObject WScript.Shell
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
New-Item $StartMenu -ItemType Directory -Force | Out-Null
$Shortcut = $Shell.CreateShortcut((Join-Path $StartMenu "Lattice.lnk"))
$Shortcut.TargetPath = $Executable
$Shortcut.WorkingDirectory = $Destination
$Shortcut.IconLocation = "$Executable,0"
$Shortcut.Description = "A shared knowledge library"
$Shortcut.Save()

Write-Host "Installed Lattice to $Destination"
if (-not $NoLaunch) { Start-Process $Executable }
