param(
  [ValidateSet("win-x64")]
  [string]$Runtime = "win-x64",
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptRoot
$Project = Join-Path $ScriptRoot "CSLibrary.Windows\CSLibrary.Windows.csproj"
$BuildRoot = Join-Path $ScriptRoot "build"
$PublishRoot = Join-Path $BuildRoot "publish-$Runtime"
$ServerRoot = Join-Path $BuildRoot "server-$Runtime"
$PackageRoot = Join-Path $BuildRoot "package-$Runtime"
$ArtifactsRoot = Join-Path $RepoRoot "artifacts"
$LayoutPath = Join-Path $RepoRoot "library-layout.json"

if (-not (Test-Path $LayoutPath)) { throw "library-layout.json is missing" }
$Layout = Get-Content $LayoutPath -Raw | ConvertFrom-Json
if ($Layout.schema_version -ne 1) { throw "Unsupported library layout schema" }

Push-Location $RepoRoot
try {
  if (-not $SkipTests) {
    Write-Host "Running portable checks..."
    python -m py_compile scripts/library_ui.py scripts/cross_platform_server.py windows/server_bootstrap.py
    python -m unittest discover -s tests -p "test_*.py" -v
    node --check ui/app.js
    node --check native/ImmersiveEPUB.js
    node --check native/LibraryWorkspace.js
    node --check native/SharedReaderState.js
    node --test tests/test_immersive_epub.mjs tests/test_library_workspace.mjs tests/test_reader_state.mjs
  }

  Write-Host "Building the standalone local service..."
  python -m pip install --disable-pip-version-check --quiet "pyinstaller==6.21.0"
  Remove-Item $ServerRoot -Recurse -Force -ErrorAction SilentlyContinue
  New-Item $ServerRoot -ItemType Directory -Force | Out-Null
  python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name CSLibraryServer `
    --paths (Join-Path $RepoRoot "scripts") `
    --distpath $ServerRoot `
    --workpath (Join-Path $BuildRoot "pyinstaller-work") `
    --specpath (Join-Path $BuildRoot "pyinstaller-spec") `
    (Join-Path $ScriptRoot "server_bootstrap.py")

  Write-Host "Publishing the Windows desktop application..."
  Remove-Item $PublishRoot -Recurse -Force -ErrorAction SilentlyContinue
  dotnet publish $Project `
    --configuration Release `
    --runtime $Runtime `
    --self-contained true `
    --output $PublishRoot `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:DebugType=None `
    -p:DebugSymbols=false

  New-Item (Join-Path $PublishRoot "Server") -ItemType Directory -Force | Out-Null
  Copy-Item (Join-Path $ServerRoot "CSLibraryServer.exe") (Join-Path $PublishRoot "Server\CSLibraryServer.exe") -Force

  Write-Host "Assembling the portable library..."
  Remove-Item $PackageRoot -Recurse -Force -ErrorAction SilentlyContinue
  New-Item $PackageRoot -ItemType Directory -Force | Out-Null
  Copy-Item (Join-Path $PublishRoot "*") $PackageRoot -Recurse -Force

  foreach ($directory in @("ui", "metadata", "manifests", "notes", "assets")) {
    $source = Join-Path $RepoRoot $directory
    if (Test-Path $source) { Copy-Item $source (Join-Path $PackageRoot $directory) -Recurse -Force }
  }

  New-Item (Join-Path $PackageRoot "native") -ItemType Directory -Force | Out-Null
  Copy-Item (Join-Path $RepoRoot "native\SharedReaderState.js") (Join-Path $PackageRoot "native\SharedReaderState.js") -Force
  Copy-Item (Join-Path $RepoRoot "native\ImmersiveEPUB.js") (Join-Path $PackageRoot "native\ImmersiveEPUB.js") -Force

  foreach ($file in @(".stignore", "CATALOG.md", "LIBRARY_RULES.md", "README.md", "STUDY_GUIDE.md", "library-layout.json")) {
    Copy-Item (Join-Path $RepoRoot $file) (Join-Path $PackageRoot $file) -Force
  }
  foreach ($directory in @($Layout.content_directories)) {
    $relative = [string]$directory
    $segments = $relative -split "[/\\]"
    if ([string]::IsNullOrWhiteSpace($relative) -or [IO.Path]::IsPathRooted($relative) -or ($segments -contains "..")) {
      throw "Unsafe content directory in library-layout.json: $relative"
    }
    $packageDirectory = Join-Path $PackageRoot $relative
    $placeholder = Join-Path (Join-Path $RepoRoot $relative) ".gitkeep"
    if (-not (Test-Path $placeholder)) { throw "Scaffold placeholder is missing: $relative/.gitkeep" }
    New-Item $packageDirectory -ItemType Directory -Force | Out-Null
    Copy-Item $placeholder (Join-Path $packageDirectory ".gitkeep") -Force
  }
  Copy-Item (Join-Path $ScriptRoot "install.ps1") (Join-Path $PackageRoot "Install CS Library.ps1") -Force

  New-Item $ArtifactsRoot -ItemType Directory -Force | Out-Null
  $Archive = Join-Path $ArtifactsRoot "CS-Library-Windows-$Runtime.zip"
  Remove-Item $Archive -Force -ErrorAction SilentlyContinue
  Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $Archive -CompressionLevel Optimal

  if (-not (Test-Path (Join-Path $PackageRoot "CS Library.exe"))) { throw "Windows app was not published" }
  if (-not (Test-Path (Join-Path $PackageRoot "Server\CSLibraryServer.exe"))) { throw "Local service was not bundled" }
  if (-not (Test-Path (Join-Path $PackageRoot ".stignore"))) { throw "Syncthing rules were not bundled" }
  foreach ($directory in @($Layout.content_directories)) {
    $packageDirectory = Join-Path $PackageRoot ([string]$directory)
    if (-not (Test-Path (Join-Path $packageDirectory ".gitkeep"))) {
      throw "Library scaffold directory was not bundled: $directory"
    }
  }
  if (-not (Test-Path $Archive)) { throw "Portable archive was not created" }
  Add-Type -AssemblyName System.IO.Compression.FileSystem
  $Zip = [IO.Compression.ZipFile]::OpenRead($Archive)
  try {
    $EntryNames = @($Zip.Entries | ForEach-Object { $_.FullName })
    if ($EntryNames -notcontains ".stignore") { throw "Syncthing rules are missing from the archive" }
    foreach ($directory in @($Layout.content_directories)) {
      $entry = (([string]$directory).TrimEnd("/") + "/.gitkeep")
      if ($EntryNames -notcontains $entry) { throw "Scaffold is missing from the archive: $entry" }
    }
  } finally {
    $Zip.Dispose()
  }
  Write-Host "Built $Archive"
} finally {
  Pop-Location
}
