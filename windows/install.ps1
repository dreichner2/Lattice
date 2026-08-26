param(
  [string]$Destination = (Join-Path $env:LOCALAPPDATA "Programs\Lattice"),
  [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$SourceExecutable = Join-Path $Source "Lattice.exe"
$SourceIcon = Join-Path $Source "Lattice.ico"
$SourceMetadata = Join-Path $Source "update-package.json"

function Assert-StableSemanticVersion([string]$Value) {
  if ($Value -notmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
    throw "The Lattice package version must be a stable major.minor.patch release."
  }
  foreach ($part in $Value.Split('.')) {
    $parsed = 0
    if (-not [int]::TryParse($part, [ref]$parsed)) {
      throw "The Lattice package version is outside the supported numeric range."
    }
  }
}

function Assert-LatticeIcon([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Lattice.ico is missing from the package" }
  $Bytes = [IO.File]::ReadAllBytes($Path)
  if (
    $Bytes.Length -lt 6 -or
    $Bytes[0] -ne 0 -or $Bytes[1] -ne 0 -or
    $Bytes[2] -ne 1 -or $Bytes[3] -ne 0 -or
    [BitConverter]::ToUInt16($Bytes, 4) -lt 1
  ) { throw "Lattice.ico is not a valid Windows icon" }
}

function Assert-EmbeddedLatticeIcon([string]$ExecutablePath, [string]$IconPath) {
  try { Add-Type -AssemblyName System.Drawing.Common } catch { Add-Type -AssemblyName System.Drawing }
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

function Resolve-ContainedPackagePath([string]$Root, [string]$Relative) {
  if (
    [string]::IsNullOrWhiteSpace($Relative) -or
    [IO.Path]::IsPathRooted($Relative) -or
    $Relative.Contains('\') -or
    $Relative.Contains(':') -or
    @($Relative.Split('/') | Where-Object { $_ -in @('', '.', '..') }).Count -ne 0
  ) { throw "Unsafe package file path: $Relative" }
  $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
  $full = [IO.Path]::GetFullPath((Join-Path $Root $Relative))
  if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Package file escapes its version directory: $Relative"
  }
  return $full
}

function Assert-PackageFileManifest([string]$Root) {
  $manifestPath = Join-Path $Root "update-files.json"
  if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw "update-files.json is missing from the package" }
  if ((Get-Item -LiteralPath $manifestPath).Length -gt 4MB) { throw "update-files.json is too large" }
  $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  $manifestNames = @($manifest.PSObject.Properties.Name | Sort-Object)
  if (Compare-Object $manifestNames @("files", "schemaVersion")) { throw "The package file manifest has unexpected fields" }
  if ($manifest.schemaVersion -ne 1 -or @($manifest.files).Count -eq 0 -or @($manifest.files).Count -gt 20000) {
    throw "The package file manifest has an unsupported shape"
  }
  $expected = @{}
  foreach ($file in @($manifest.files)) {
    $fileNames = @($file.PSObject.Properties.Name | Sort-Object)
    if (Compare-Object $fileNames @("path", "sha256", "size")) { throw "A package file entry has unexpected fields" }
    $relative = [string]$file.path
    if (
      $expected.ContainsKey($relative) -or
      $relative -ieq "update-files.json" -or
      [string]$file.sha256 -cnotmatch '^[0-9a-f]{64}$' -or
      [long]$file.size -lt 0
    ) { throw "Invalid package file entry: $relative" }
    $path = Resolve-ContainedPackagePath $Root $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Package file is missing: $relative" }
    $information = Get-Item -LiteralPath $path
    if (
      ($information.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
      $information.Length -ne [long]$file.size -or
      (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -cne [string]$file.sha256
    ) { throw "Package file failed verification: $relative" }
    $expected[$relative] = $true
  }
  foreach ($required in @(
    "Lattice.exe",
    "Lattice.ico",
    "Server/LatticeServer.exe",
    "Tools/LatticeStorage.exe",
    "ui/index.html",
    "ui/app.js",
    "ui/reader-desk.css",
    "ui/reader-desk.js",
    "ui/audio-player.css",
    "ui/audio-player.js",
    "ui/study-lab.html",
    "ui/study-lab.css",
    "ui/study-lab.js",
    "ui/vendor/katex/LICENSE",
    "ui/vendor/katex/README-LATTICE.md",
    "ui/vendor/katex/katex.min.css",
    "ui/vendor/katex/katex.min.js",
    "ui/vendor/katex/fonts/KaTeX_Main-Regular.woff2",
    "update-package.json"
  )) {
    if (-not $expected.ContainsKey($required)) { throw "The package file manifest omits $required" }
  }
  $actual = @{}
  $rootPrefix = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
  $rootManifest = [IO.Path]::GetFullPath($manifestPath)
  foreach ($item in Get-ChildItem -LiteralPath $Root -Force -Recurse) {
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Package reparse points are not allowed" }
    if ($item.PSIsContainer) { continue }
    $itemPath = [IO.Path]::GetFullPath($item.FullName)
    if ($itemPath -ceq $rootManifest) { continue }
    if (-not $itemPath.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Package file escapes the version directory: $itemPath"
    }
    $relative = $itemPath.Substring($rootPrefix.Length).Replace('\', '/')
    $actual[$relative] = $true
  }
  if ($actual.Count -ne $expected.Count) { throw "The package contains unverified or missing files" }
  foreach ($relative in $actual.Keys) {
    if (-not $expected.ContainsKey($relative)) { throw "The package contains an unverified file: $relative" }
  }
}

function Write-JsonAtomically([string]$Path, [object]$Value, [string]$BackupPath) {
  $temporary = Join-Path (Split-Path -Parent $Path) (".{0}.{1}.tmp" -f ([IO.Path]::GetFileName($Path)), [Guid]::NewGuid().ToString('N'))
  try {
    [IO.File]::WriteAllText($temporary, (($Value | ConvertTo-Json -Depth 4 -Compress) + [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
      [IO.File]::Replace($temporary, $Path, $BackupPath, $true)
    } else {
      [IO.File]::Move($temporary, $Path)
    }
  } finally {
    if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
  }
}

function Get-ValidatedActiveVersion([string]$Path) {
  $ActiveFile = Get-Item -LiteralPath $Path
  if (
    ($ActiveFile.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    $ActiveFile.Length -le 0 -or
    $ActiveFile.Length -gt 16KB
  ) { throw "The existing Lattice active-version.json is unsafe." }

  try {
    $Active = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
  } catch {
    throw "The existing Lattice active-version.json is malformed."
  }
  $ActiveNames = @($Active.PSObject.Properties.Name | Sort-Object)
  if (Compare-Object $ActiveNames @("previousVersion", "promotedAt", "schemaVersion", "version")) {
    throw "The existing Lattice active-version.json has an unsupported shape."
  }
  if ([int]$Active.schemaVersion -ne 1) {
    throw "The existing Lattice active-version.json has an unsupported schema."
  }

  $ActiveVersion = [string]$Active.version
  try { Assert-StableSemanticVersion $ActiveVersion } catch {
    throw "The existing Lattice active-version.json names an invalid active version."
  }
  $ActivePreviousVersion = ""
  if ($null -ne $Active.previousVersion) {
    $ActivePreviousVersion = [string]$Active.previousVersion
    try { Assert-StableSemanticVersion $ActivePreviousVersion } catch {
      throw "The existing Lattice active-version.json names an invalid previous version."
    }
    if (
      [Version]::Parse($ActivePreviousVersion).CompareTo(
        [Version]::Parse($ActiveVersion)
      ) -ge 0
    ) { throw "The existing Lattice active-version.json has an invalid rollback version." }
  }
  $PromotedAt = [DateTimeOffset]::MinValue
  if (
    -not [DateTimeOffset]::TryParse([string]$Active.promotedAt, [ref]$PromotedAt) -or
    $PromotedAt.Offset -ne [TimeSpan]::Zero
  ) { throw "The existing Lattice active-version.json has an invalid promotion timestamp." }
  return [pscustomobject]@{
    Version = $ActiveVersion
    PreviousVersion = $ActivePreviousVersion
  }
}

function Set-LatticeShortcutAtomically([string]$Executable, [string]$PreviousVersion) {
  $Shell = New-Object -ComObject WScript.Shell
  $StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
  New-Item $StartMenu -ItemType Directory -Force | Out-Null
  $ShortcutPath = Join-Path $StartMenu "Lattice.lnk"
  $TemporaryPath = Join-Path $StartMenu (".Lattice-{0}.lnk" -f [Guid]::NewGuid().ToString('N'))
  $RollbackRoot = Join-Path $Destination "rollback"
  New-Item $RollbackRoot -ItemType Directory -Force | Out-Null
  $PreviousLabel = if ([string]::IsNullOrWhiteSpace($PreviousVersion)) { "pre-versioned" } else { $PreviousVersion }
  $BackupPath = Join-Path $RollbackRoot ("Lattice-{0}-{1}.lnk" -f $PreviousLabel, [Guid]::NewGuid().ToString('N'))
  try {
    $Shortcut = $Shell.CreateShortcut($TemporaryPath)
    $Shortcut.TargetPath = $Executable
    $Shortcut.WorkingDirectory = Split-Path -Parent $Executable
    $Shortcut.IconLocation = "$Executable,0"
    $Shortcut.Description = "A shared knowledge library"
    $Shortcut.Save()
    if (-not (Test-Path -LiteralPath $TemporaryPath -PathType Leaf)) { throw "The versioned Lattice shortcut was not created." }
    if (Test-Path -LiteralPath $ShortcutPath -PathType Leaf) {
      [IO.File]::Replace($TemporaryPath, $ShortcutPath, $BackupPath, $true)
    } else {
      [IO.File]::Move($TemporaryPath, $ShortcutPath)
    }
  } finally {
    if (Test-Path -LiteralPath $TemporaryPath -PathType Leaf) { Remove-Item -LiteralPath $TemporaryPath -Force }
  }
}

if (-not (Test-Path -LiteralPath $SourceExecutable -PathType Leaf)) { throw "Lattice.exe is missing from the package" }
if (-not (Test-Path -LiteralPath $SourceMetadata -PathType Leaf)) { throw "update-package.json is missing from the package" }
Assert-LatticeIcon $SourceIcon
Assert-PackageFileManifest $Source

$Metadata = Get-Content -LiteralPath $SourceMetadata -Raw | ConvertFrom-Json
$MetadataNames = @($Metadata.PSObject.Properties.Name | Sort-Object)
$ExpectedMetadataNames = @("platform", "repository", "schemaVersion", "version")
if (Compare-Object $MetadataNames $ExpectedMetadataNames) { throw "The Lattice package metadata has unexpected fields." }
if (
  $Metadata.schemaVersion -ne 1 -or
  $Metadata.repository -cne "dreichner2/Lattice" -or
  $Metadata.platform -cne "windows-x64"
) { throw "The Lattice package metadata is invalid." }
$Version = [string]$Metadata.version
Assert-StableSemanticVersion $Version

$Destination = [IO.Path]::GetFullPath($Destination)
if (
  (Test-Path -LiteralPath $Destination) -and
  ((Get-Item -LiteralPath $Destination).Attributes -band [IO.FileAttributes]::ReparsePoint)
) { throw "The Lattice installation root cannot be a reparse point." }
$VersionsRoot = Join-Path $Destination "versions"
$VersionDestination = Join-Path $VersionsRoot $Version
$StagingRoot = Join-Path $Destination ".installing"
$Staging = Join-Path $StagingRoot ("{0}-{1}" -f $Version, [Guid]::NewGuid().ToString('N'))
$RollbackRoot = Join-Path $Destination "rollback"
New-Item $VersionsRoot -ItemType Directory -Force | Out-Null
New-Item $StagingRoot -ItemType Directory -Force | Out-Null
New-Item $RollbackRoot -ItemType Directory -Force | Out-Null

$ActivePath = Join-Path $Destination "active-version.json"
$PreviousVersion = ""
if (Test-Path -LiteralPath $ActivePath -PathType Leaf) {
  $ExistingActive = Get-ValidatedActiveVersion $ActivePath
  $ExistingVersionOrder = [Version]::Parse([string]$ExistingActive.Version).CompareTo(
    [Version]::Parse($Version)
  )
  if ($ExistingVersionOrder -gt 0) {
    throw "Refusing to replace active Lattice $($ExistingActive.Version) with older version $Version."
  }
  $PreviousVersion = if ($ExistingVersionOrder -eq 0) {
    [string]$ExistingActive.PreviousVersion
  } else {
    [string]$ExistingActive.Version
  }
}

if (-not (Test-Path -LiteralPath $VersionDestination -PathType Container)) {
  try {
    New-Item $Staging -ItemType Directory | Out-Null
    Copy-Item (Join-Path $Source "*") $Staging -Recurse -Force
    $StagedExecutable = Join-Path $Staging "Lattice.exe"
    $StagedIcon = Join-Path $Staging "Lattice.ico"
    $StagedMetadata = Join-Path $Staging "update-package.json"
    if (-not (Test-Path -LiteralPath $StagedExecutable -PathType Leaf)) { throw "Lattice.exe was not staged" }
    if (-not (Test-Path -LiteralPath (Join-Path $Staging "Server\LatticeServer.exe") -PathType Leaf)) { throw "LatticeServer.exe was not staged" }
    if (-not (Test-Path -LiteralPath (Join-Path $Staging "Tools\LatticeStorage.exe") -PathType Leaf)) { throw "LatticeStorage.exe was not staged" }
    if (-not (Test-Path -LiteralPath (Join-Path $Staging "ui\index.html") -PathType Leaf)) { throw "The Lattice interface was not staged" }
    if ((Get-Content -LiteralPath $StagedMetadata -Raw | ConvertFrom-Json).version -cne $Version) { throw "The staged package version changed" }
    Assert-LatticeIcon $StagedIcon
    Assert-EmbeddedLatticeIcon $StagedExecutable $StagedIcon
    Assert-PackageFileManifest $Staging
    [IO.Directory]::Move($Staging, $VersionDestination)
  } finally {
    if (Test-Path -LiteralPath $Staging -PathType Container) { Remove-Item -LiteralPath $Staging -Recurse -Force }
  }
}

$Executable = Join-Path $VersionDestination "Lattice.exe"
$Icon = Join-Path $VersionDestination "Lattice.ico"
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) { throw "The versioned Lattice executable is missing" }
if (-not (Test-Path -LiteralPath (Join-Path $VersionDestination "Server\LatticeServer.exe") -PathType Leaf)) { throw "The versioned Lattice server is missing" }
if (-not (Test-Path -LiteralPath (Join-Path $VersionDestination "Tools\LatticeStorage.exe") -PathType Leaf)) { throw "The versioned Lattice storage helper is missing" }
if ((Get-Content -LiteralPath (Join-Path $VersionDestination "update-package.json") -Raw | ConvertFrom-Json).version -cne $Version) {
  throw "An existing version directory has inconsistent metadata; refusing to overwrite it."
}
Assert-LatticeIcon $Icon
Assert-EmbeddedLatticeIcon $Executable $Icon
Assert-PackageFileManifest $VersionDestination

$PreviousLabel = if ($PreviousVersion) { $PreviousVersion } else { "pre-versioned" }
$ActiveBackup = Join-Path $RollbackRoot ("active-version-{0}-{1}.json" -f $PreviousLabel, [Guid]::NewGuid().ToString('N'))
# The active record is the authority used by stale shortcuts. Publish it first:
# if shortcut replacement is interrupted, the prior executable redirects here.
Write-JsonAtomically -Path $ActivePath -BackupPath $ActiveBackup -Value @{
  schemaVersion = 1
  version = $Version
  previousVersion = $(if ($PreviousVersion -and $PreviousVersion -ne $Version) { $PreviousVersion } else { $null })
  promotedAt = [DateTimeOffset]::UtcNow.ToString("O")
}
Set-LatticeShortcutAtomically -Executable $Executable -PreviousVersion $PreviousVersion

Write-Host "Installed Lattice $Version to $VersionDestination"
Write-Host "Previous versions were retained under $VersionsRoot for rollback."
if (-not $NoLaunch) { Start-Process $Executable }
