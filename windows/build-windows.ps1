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
$PackageMetadataPath = Join-Path $PackageRoot "update-package.json"
$RequiredUiFiles = @(
  "index.html",
  "app.js",
  "tutor.js",
  "styles.css",
  "tutor-styles.css",
  "study-lab.html",
  "study-lab.css",
  "study-lab.js",
  "vendor/katex/LICENSE",
  "vendor/katex/README-LATTICE.md",
  "vendor/katex/katex.min.css",
  "vendor/katex/katex.min.js",
  "vendor/katex/fonts/KaTeX_Main-Regular.woff2",
  "video-styles.css",
  "videos.js",
  "pdf-reader.html",
  "pdf-reader.css",
  "pdf-reader.js",
  "pdf-reader-lifecycle.mjs",
  "vendor/pdfjs/LICENSE",
  "vendor/pdfjs/build/pdf.min.mjs",
  "vendor/pdfjs/build/pdf.worker.min.mjs",
  "vendor/pdfjs/web/pdf_viewer.mjs",
  "vendor/pdfjs/web/pdf_viewer.css"
)
$RequiredNativeFiles = @("SharedReaderState.js", "ImmersiveEPUB.js")
$RequiredRootFiles = @(
  ".stignore",
  "CATALOG.md",
  "LIBRARY_RULES.md",
  "README.md",
  "STUDY_GUIDE.md",
  "THIRD_PARTY_NOTICES.md",
  "library-layout.json",
  "library-taxonomy.json"
)

function Assert-NativeSuccess([string]$Action) {
  if ($LASTEXITCODE -ne 0) {
    throw "$Action failed with exit code $LASTEXITCODE"
  }
}

if (-not (Test-Path $LayoutPath)) { throw "library-layout.json is missing" }
if (-not (Test-Path $IconGenerator)) { throw "Lattice icon generator is missing" }
$Layout = Get-Content $LayoutPath -Raw | ConvertFrom-Json
if ($Layout.schema_version -ne 1) { throw "Unsupported library layout schema" }
$ProjectXml = [xml](Get-Content $Project -Raw)
$PackageVersion = [string]$ProjectXml.Project.PropertyGroup.Version
if ($PackageVersion -notmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
  throw "The Windows project Version must be a stable major.minor.patch release"
}
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
    python -m py_compile scripts/library_ui.py scripts/library_vault.py scripts/lattice_tutor.py scripts/study_lab.py scripts/cross_platform_server.py scripts/move_library.py windows/server_bootstrap.py windows/generate_icon.py
    Assert-NativeSuccess "Python compilation"
    python -m unittest discover -s tests -p "test_*.py" -v
    Assert-NativeSuccess "Python tests"
    node --check ui/app.js
    Assert-NativeSuccess "ui/app.js syntax check"
    node --check ui/pdf-reader.js
    Assert-NativeSuccess "ui/pdf-reader.js syntax check"
    node --check ui/videos.js
    Assert-NativeSuccess "ui/videos.js syntax check"
    node --check ui/tutor.js
    Assert-NativeSuccess "ui/tutor.js syntax check"
    node --check ui/study-lab.js
    Assert-NativeSuccess "ui/study-lab.js syntax check"
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
    --paths (Join-Path $RepoRoot "scripts\vendor") `
    --hidden-import pypdf `
    --hidden-import study_lab `
    --distpath $ServerRoot `
    --workpath (Join-Path $BuildRoot "pyinstaller-work") `
    --specpath (Join-Path $BuildRoot "pyinstaller-spec") `
    (Join-Path $ScriptRoot "server_bootstrap.py")
  Assert-NativeSuccess "Standalone service build"

  Write-Host "Building the standalone storage relocation helper..."
  python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name LatticeStorage `
    --distpath $ServerRoot `
    --workpath (Join-Path $BuildRoot "pyinstaller-storage-work") `
    --specpath (Join-Path $BuildRoot "pyinstaller-spec") `
    (Join-Path $RepoRoot "scripts\move_library.py")
  Assert-NativeSuccess "Standalone storage helper build"

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
  Assert-NativeSuccess "Windows desktop application build"

  New-Item (Join-Path $PublishRoot "Server") -ItemType Directory -Force | Out-Null
  Copy-Item (Join-Path $ServerRoot "LatticeServer.exe") (Join-Path $PublishRoot "Server\LatticeServer.exe") -Force
  New-Item (Join-Path $PublishRoot "Tools") -ItemType Directory -Force | Out-Null
  Copy-Item (Join-Path $ServerRoot "LatticeStorage.exe") (Join-Path $PublishRoot "Tools\LatticeStorage.exe") -Force

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
  [IO.File]::WriteAllText(
    $PackageMetadataPath,
    (([ordered]@{
      schemaVersion = 1
      repository = "dreichner2/Lattice"
      platform = "windows-x64"
      version = $PackageVersion
    } | ConvertTo-Json -Compress) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false)
  )
  $PackageFiles = @(
    Get-ChildItem $PackageRoot -File -Recurse |
      Sort-Object FullName |
      ForEach-Object {
        $packagePrefix = [IO.Path]::GetFullPath($PackageRoot).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        $packageFile = [IO.Path]::GetFullPath($_.FullName)
        if (-not $packageFile.StartsWith($packagePrefix, [StringComparison]::OrdinalIgnoreCase)) {
          throw "Package file escapes the package root: $packageFile"
        }
        $relative = $packageFile.Substring($packagePrefix.Length).Replace("\", "/")
        if ($relative -cne "update-files.json") {
          [ordered]@{
            path = $relative
            sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            size = $_.Length
          }
        }
      }
  )
  [IO.File]::WriteAllText(
    (Join-Path $PackageRoot "update-files.json"),
    (([ordered]@{ schemaVersion = 1; files = $PackageFiles } | ConvertTo-Json -Depth 5 -Compress) + [Environment]::NewLine),
    [Text.UTF8Encoding]::new($false)
  )

  New-Item $ArtifactsRoot -ItemType Directory -Force | Out-Null
  $Archive = Join-Path $ArtifactsRoot "Lattice-Windows-$Runtime.zip"
  Remove-Item $Archive -Force -ErrorAction SilentlyContinue
  Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $Archive -CompressionLevel Optimal

  if (-not (Test-Path (Join-Path $PackageRoot "Lattice.exe"))) { throw "Windows app was not published" }
  if (-not (Test-Path (Join-Path $PackageRoot "Server\LatticeServer.exe"))) { throw "Local service was not bundled" }
  if (-not (Test-Path (Join-Path $PackageRoot "Tools\LatticeStorage.exe"))) { throw "Storage helper was not bundled" }
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
    foreach ($entry in @("Lattice.exe", "Lattice.ico", "Server/LatticeServer.exe", "Tools/LatticeStorage.exe", "Install Lattice.ps1", "update-package.json", "update-files.json")) {
      if ($EntryNames -notcontains $entry) { throw "Runtime file is missing from the archive: $entry" }
    }
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
