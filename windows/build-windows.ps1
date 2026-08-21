param(
  [ValidateSet("win-x64")]
  [string]$Runtime = "win-x64",
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptRoot
$Project = Join-Path $ScriptRoot "CSLibrary.Windows\CSLibrary.Windows.csproj"
$ReaderRoot = Join-Path $ScriptRoot "reader"
$BuildRoot = Join-Path $ScriptRoot "build"
$PublishRoot = Join-Path $BuildRoot "publish-$Runtime"
$ServerRoot = Join-Path $BuildRoot "server-$Runtime"
$PackageRoot = Join-Path $BuildRoot "package-$Runtime"
$ArtifactsRoot = Join-Path $RepoRoot "artifacts"

Write-Host "Preparing PDF.js assets..."
Push-Location $ReaderRoot
try {
  npm install --no-audit --no-fund
  $Vendor = Join-Path $ReaderRoot "vendor"
  Remove-Item $Vendor -Recurse -Force -ErrorAction SilentlyContinue
  New-Item $Vendor -ItemType Directory -Force | Out-Null
  Copy-Item "node_modules\pdfjs-dist\build\pdf.mjs" $Vendor
  Copy-Item "node_modules\pdfjs-dist\build\pdf.worker.mjs" $Vendor
  Copy-Item "node_modules\pdfjs-dist\cmaps" (Join-Path $Vendor "cmaps") -Recurse
  Copy-Item "node_modules\pdfjs-dist\standard_fonts" (Join-Path $Vendor "standard_fonts") -Recurse
} finally {
  Pop-Location
}

Write-Host "Preparing shared reader scripts..."
$Resources = Join-Path $ScriptRoot "CSLibrary.Windows\Resources"
New-Item $Resources -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $RepoRoot "native\SharedReaderState.js") $Resources -Force
Copy-Item (Join-Path $RepoRoot "native\ImmersiveEPUB.js") $Resources -Force

if (-not $SkipTests) {
  Write-Host "Running cross-platform tests..."
  python tests/test_cross_platform_server.py
  node --test tests/test_reader_state.mjs
  node --test tests/test_immersive_epub.mjs
  node --check windows/reader/pdf-reader.js
  node --check native/SharedReaderState.js
}

Write-Host "Building the standalone local server..."
python -m pip install --disable-pip-version-check --quiet pyinstaller
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

Write-Host "Assembling a ready-to-run portable library..."
Remove-Item $PackageRoot -Recurse -Force -ErrorAction SilentlyContinue
New-Item $PackageRoot -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $PublishRoot "*") $PackageRoot -Recurse -Force

foreach ($directory in @("ui", "metadata", "manifests", "notes", "assets")) {
  $source = Join-Path $RepoRoot $directory
  if (Test-Path $source) { Copy-Item $source (Join-Path $PackageRoot $directory) -Recurse -Force }
}

New-Item (Join-Path $PackageRoot "scripts") -ItemType Directory -Force | Out-Null
foreach ($script in @("library_ui.py", "cross_platform_server.py", "fetch.py")) {
  Copy-Item (Join-Path $RepoRoot "scripts\$script") (Join-Path $PackageRoot "scripts\$script") -Force
}

New-Item (Join-Path $PackageRoot "native") -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $RepoRoot "native\SharedReaderState.js") (Join-Path $PackageRoot "native\SharedReaderState.js") -Force
Copy-Item (Join-Path $RepoRoot "native\ImmersiveEPUB.js") (Join-Path $PackageRoot "native\ImmersiveEPUB.js") -Force
Copy-Item $ReaderRoot (Join-Path $PackageRoot "windows\reader") -Recurse -Force
Remove-Item (Join-Path $PackageRoot "windows\reader\node_modules") -Recurse -Force -ErrorAction SilentlyContinue

foreach ($file in @("CATALOG.md", "LIBRARY_RULES.md", "README.md", "STUDY_GUIDE.md")) {
  Copy-Item (Join-Path $RepoRoot $file) (Join-Path $PackageRoot $file) -Force
}
New-Item (Join-Path $PackageRoot "books") -ItemType Directory -Force | Out-Null
New-Item (Join-Path $PackageRoot "papers") -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $ScriptRoot "install.ps1") (Join-Path $PackageRoot "Install CS Library.ps1") -Force

New-Item $ArtifactsRoot -ItemType Directory -Force | Out-Null
$Archive = Join-Path $ArtifactsRoot "CS-Library-Windows-$Runtime.zip"
Remove-Item $Archive -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $Archive -CompressionLevel Optimal
Write-Host "Built $Archive"
