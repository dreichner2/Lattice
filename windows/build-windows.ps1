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
$IconGenerator = Join-Path $ScriptRoot "generate_icon.py"
$IconPath = Join-Path $BuildRoot "Lattice.ico"
$RequiredUiFiles = @("index.html", "app.js", "styles.css", "video-styles.css", "videos.js")
$RequiredNativeFiles = @("SharedReaderState.js", "ImmersiveEPUB.js")
$RequiredRootFiles = @(
  ".stignore",
  "CATALOG.md",
  "LIBRARY_RULES.md",
  "README.md",
  "STUDY_GUIDE.md",
  "library-layout.json",
  "library-taxonomy.json"
)

function Assert-NativeSuccess([string]$Action) {
  if ($LASTEXITCODE -ne 0) {
    throw "$Action failed with exit code $LASTEXITCODE"
  }
}
$BuildCommit = $env:LATTICE_BUILD_COMMIT
if ([string]::IsNullOrWhiteSpace($BuildCommit)) {
  $BuildCommit = (& git -C $RepoRoot rev-parse HEAD 2>$null)
}
if ($BuildCommit -notmatch "^[0-9a-f]{40}$") { $BuildCommit = "development" }

if (-not (Test-Path $LayoutPath)) { throw "library-layout.json is missing" }
if (-not (Test-Path $IconGenerator)) { throw "Lattice icon generator is missing" }
$Layout = Get-Content $LayoutPath -Raw | ConvertFrom-Json
if ($Layout.schema_version -ne 1) { throw "Unsupported library layout schema" }
foreach ($relative in $RequiredRootFiles) {
  if (-not (Test-Path (Join-Path $RepoRoot $relative))) { throw "Required package file is missing: $relative" }
}
foreach ($relative in $RequiredUiFiles) {
  if (-not (Test-Path (Join-Path $RepoRoot "ui\$relative"))) { throw "Required interface file is missing: ui/$relative" }
}
foreach ($relative in $RequiredNativeFiles) {
  if (-not (Test-Path (Join-Path $RepoRoot "native\$relative"))) { throw "Required native file is missing: native/$relative" }
}

Push-Location $RepoRoot
try {
  Write-Host "Generating the Windows application icon..."
  python $IconGenerator --output $IconPath
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $IconPath)) { throw "Lattice.ico was not generated" }

  if (-not $SkipTests) {
    Write-Host "Running portable checks..."
    python -m py_compile scripts/library_ui.py scripts/cross_platform_server.py windows/server_bootstrap.py windows/generate_icon.py
    Assert-NativeSuccess "Python compilation"
    python -m unittest discover -s tests -p "test_*.py" -v
    Assert-NativeSuccess "Python tests"
    node --check ui/app.js
    Assert-NativeSuccess "ui/app.js syntax check"
    node --check ui/videos.js
    Assert-NativeSuccess "ui/videos.js syntax check"
    node --check native/ImmersiveEPUB.js
    Assert-NativeSuccess "native/ImmersiveEPUB.js syntax check"
    node --check native/LibraryWorkspace.js
    Assert-NativeSuccess "native/LibraryWorkspace.js syntax check"
    node --check native/SharedReaderState.js
    Assert-NativeSuccess "native/SharedReaderState.js syntax check"
    $NodeTests = @(
      Get-ChildItem (Join-Path $RepoRoot "tests") -Filter "test_*.mjs" -File |
        Sort-Object Name |
        ForEach-Object { $_.FullName }
    )
    if ($NodeTests.Count -eq 0) { throw "No Node test files were found" }
    if ((Split-Path $NodeTests -Leaf) -notcontains "test_lattice_import_ui.mjs") {
      throw "The Lattice import UI test is missing"
    }
    node --test @NodeTests
    Assert-NativeSuccess "Node tests"
  }

  Write-Host "Building the standalone local service..."
  python -m pip install --disable-pip-version-check --quiet "pyinstaller==6.21.0"
  Assert-NativeSuccess "PyInstaller installation"
  Remove-Item $ServerRoot -Recurse -Force -ErrorAction SilentlyContinue
  New-Item $ServerRoot -ItemType Directory -Force | Out-Null
  python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name LatticeServer `
    --paths (Join-Path $RepoRoot "scripts") `
    --distpath $ServerRoot `
    --workpath (Join-Path $BuildRoot "pyinstaller-work") `
    --specpath (Join-Path $BuildRoot "pyinstaller-spec") `
    (Join-Path $ScriptRoot "server_bootstrap.py")
  Assert-NativeSuccess "Standalone service build"

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
    -p:DebugSymbols=false `
    "-p:SourceRevisionId=$BuildCommit"
  Assert-NativeSuccess "Windows desktop application build"

  New-Item (Join-Path $PublishRoot "Server") -ItemType Directory -Force | Out-Null
  Copy-Item (Join-Path $ServerRoot "LatticeServer.exe") (Join-Path $PublishRoot "Server\LatticeServer.exe") -Force

  Write-Host "Assembling the portable library..."
  Remove-Item $PackageRoot -Recurse -Force -ErrorAction SilentlyContinue
  New-Item $PackageRoot -ItemType Directory -Force | Out-Null
  Copy-Item (Join-Path $PublishRoot "*") $PackageRoot -Recurse -Force

  foreach ($directory in @("ui", "metadata", "manifests", "notes", "assets")) {
    $source = Join-Path $RepoRoot $directory
    if (Test-Path $source) { Copy-Item $source (Join-Path $PackageRoot $directory) -Recurse -Force }
  }

  New-Item (Join-Path $PackageRoot "native") -ItemType Directory -Force | Out-Null
  foreach ($file in $RequiredNativeFiles) {
    Copy-Item (Join-Path $RepoRoot "native\$file") (Join-Path $PackageRoot "native\$file") -Force
  }

  foreach ($file in $RequiredRootFiles) {
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
  Copy-Item (Join-Path $ScriptRoot "install.ps1") (Join-Path $PackageRoot "Install Lattice.ps1") -Force
  Copy-Item $IconPath (Join-Path $PackageRoot "Lattice.ico") -Force

  $BuildInfo = [ordered]@{
    schemaVersion = 1
    repository = "dreichner2/cs-library"
    channel = "main"
    commit = $BuildCommit
  }
  $Utf8NoBom = [System.Text.UTF8Encoding]::new($false)
  [IO.File]::WriteAllText(
    (Join-Path $PackageRoot "update-build.json"),
    (($BuildInfo | ConvertTo-Json -Depth 3) + [Environment]::NewLine),
    $Utf8NoBom)

  $MutableRoots = @($Layout.content_directories | ForEach-Object {
    (([string]$_) -split "[/\\]")[0]
  } | Sort-Object -Unique)
  $OwnedFiles = @(Get-ChildItem $PackageRoot -Recurse -File -Force | ForEach-Object {
    [IO.Path]::GetRelativePath($PackageRoot, $_.FullName).Replace("\", "/")
  } | Where-Object {
    $TopLevel = ($_ -split "/")[0]
    $TopLevel -notin $MutableRoots -and $_ -ne "update-files.json"
  })
  $OwnedFiles += "update-files.json"
  $OwnedFiles = @($OwnedFiles | Sort-Object -Unique)
  $OwnedManifest = [ordered]@{
    schemaVersion = 1
    files = $OwnedFiles
  }
  [IO.File]::WriteAllText(
    (Join-Path $PackageRoot "update-files.json"),
    (($OwnedManifest | ConvertTo-Json -Depth 4) + [Environment]::NewLine),
    $Utf8NoBom)

  New-Item $ArtifactsRoot -ItemType Directory -Force | Out-Null
  $Archive = Join-Path $ArtifactsRoot "Lattice-Windows-$Runtime.zip"
  Remove-Item $Archive -Force -ErrorAction SilentlyContinue
  Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $Archive -CompressionLevel Optimal

  if (-not (Test-Path (Join-Path $PackageRoot "Lattice.exe"))) { throw "Windows app was not published" }
  if (-not (Test-Path (Join-Path $PackageRoot "Server\LatticeServer.exe"))) { throw "Local service was not bundled" }
  if (-not (Test-Path (Join-Path $PackageRoot "Lattice.ico"))) { throw "Windows icon was not bundled" }
  if (-not (Test-Path (Join-Path $PackageRoot ".stignore"))) { throw "Syncthing rules were not bundled" }
  foreach ($file in $RequiredRootFiles) {
    if (-not (Test-Path (Join-Path $PackageRoot $file))) { throw "Package file is missing: $file" }
  }
  foreach ($file in $RequiredUiFiles) {
    if (-not (Test-Path (Join-Path $PackageRoot "ui\$file"))) { throw "Interface file is missing: ui/$file" }
  }
  foreach ($file in $RequiredNativeFiles) {
    if (-not (Test-Path (Join-Path $PackageRoot "native\$file"))) { throw "Native file is missing: native/$file" }
  }
  if (-not (Test-Path (Join-Path $PackageRoot "update-build.json"))) { throw "Build revision metadata was not bundled" }
  if (-not (Test-Path (Join-Path $PackageRoot "update-files.json"))) { throw "Updater-owned file metadata was not bundled" }
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
    foreach ($file in $RequiredRootFiles) {
      $entry = $file.Replace("\", "/")
      if ($EntryNames -notcontains $entry) { throw "Package file is missing from the archive: $entry" }
    }
    foreach ($file in $RequiredUiFiles) {
      $entry = "ui/$file"
      if ($EntryNames -notcontains $entry) { throw "Interface file is missing from the archive: $entry" }
    }
    foreach ($file in $RequiredNativeFiles) {
      $entry = "native/$file"
      if ($EntryNames -notcontains $entry) { throw "Native file is missing from the archive: $entry" }
    }
    foreach ($entry in @("Lattice.exe", "Lattice.ico", "Server/LatticeServer.exe", "Install Lattice.ps1")) {
      if ($EntryNames -notcontains $entry) { throw "Runtime file is missing from the archive: $entry" }
    }
    if ($EntryNames -notcontains "update-build.json") { throw "Build revision metadata is missing from the archive" }
    if ($EntryNames -notcontains "update-files.json") { throw "Updater-owned file metadata is missing from the archive" }
    foreach ($directory in @($Layout.content_directories)) {
      $entry = (([string]$directory).TrimEnd("/") + "/.gitkeep")
      if ($EntryNames -notcontains $entry) { throw "Scaffold is missing from the archive: $entry" }
    }
  } finally {
    $Zip.Dispose()
  }
  Write-Host "Built $Archive at $BuildCommit"
} finally {
  Pop-Location
}
