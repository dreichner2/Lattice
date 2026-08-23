Set-StrictMode -Version Latest

$script:HubDeviceId = "MTECQEG-YI6OB3G-LI5UG6T-VTGJGQ2-MBBUWW2-G4VVCNS-3DGDGL6-AV4JJAQ"
$script:FolderId = "cs-library-3b8290f24f15"
$script:FolderLabel = "Lattice"
$script:SyncthingPackageId = "Syncthing.Syncthing"
$script:SyncthingPackageVersion = "2.1.3"
$script:DefaultLatticeVersion = "v2.2.9"
$script:ReleaseRoot = "https://github.com/dreichner2/Lattice/releases/download"
$script:LatticeAssetName = "Lattice-Windows-win-x64.zip"

function Resolve-SetupPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

function Test-PathInside {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate,
        [Parameter(Mandatory = $true)]
        [string]$Parent
    )

    $candidatePath = (Resolve-SetupPath $Candidate).TrimEnd('\', '/')
    $parentPath = (Resolve-SetupPath $Parent).TrimEnd('\', '/')
    if ([string]::Equals($candidatePath, $parentPath, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $candidatePath.StartsWith(
        $parentPath + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase
    )
}

function Get-ValidatedLibraryLayout {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LibraryRoot
    )

    $root = Resolve-SetupPath $LibraryRoot
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "The library clone does not exist: $root"
    }

    foreach ($relative in @(
        ".git",
        ".stignore",
        "CATALOG.md",
        "library-layout.json",
        "library-taxonomy.json",
        "metadata",
        "ui"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $root $relative))) {
            throw "This is not a complete Lattice clone; required entry is missing: $relative"
        }
    }

    $layoutPath = Join-Path $root "library-layout.json"
    $layout = Get-Content -LiteralPath $layoutPath -Raw | ConvertFrom-Json
    if ([int]$layout.schema_version -ne 1) {
        throw "Unsupported library-layout.json schema: $($layout.schema_version)"
    }
    if ([string]$layout.syncthing.folder_id -ne $script:FolderId) {
        throw "library-layout.json does not name the expected Syncthing folder ID $($script:FolderId)."
    }
    if ([string]$layout.syncthing.folder_type -ne "sendreceive") {
        throw "The Lattice Syncthing folder must be send-receive."
    }

    foreach ($relativeValue in @($layout.content_directories)) {
        $relative = [string]$relativeValue
        $segments = $relative -split "[/\\]"
        if (
            [string]::IsNullOrWhiteSpace($relative) -or
            [IO.Path]::IsPathRooted($relative) -or
            ($segments -contains "..")
        ) {
            throw "Unsafe content directory in library-layout.json: $relative"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $root $relative) -PathType Container)) {
            throw "The clone is missing its scaffold directory: $relative"
        }
    }

    return [pscustomobject]@{
        Root = $root
        Layout = $layout
    }
}

function Test-LatticeInstall {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InstallDestination
    )

    $executable = Get-ActiveLatticeExecutable $InstallDestination
    return -not [string]::IsNullOrWhiteSpace($executable)
}

function Get-ActiveLatticeExecutable {
    param(
        [Parameter(Mandatory = $true)]
        [string]$InstallDestination
    )

    $activePath = Join-Path $InstallDestination "active-version.json"
    if (-not (Test-Path -LiteralPath $activePath -PathType Leaf)) { return $null }
    $activeFile = Get-Item -LiteralPath $activePath
    if ($activeFile.Length -le 0 -or $activeFile.Length -gt 16KB) {
        throw "Lattice's active-version.json has an unsafe size."
    }
    try {
        $active = Get-Content -LiteralPath $activePath -Raw | ConvertFrom-Json
    } catch {
        throw "Lattice's active-version.json is malformed."
    }
    $versionProperty = $active.PSObject.Properties["version"]
    $schemaProperty = $active.PSObject.Properties["schemaVersion"]
    if ($null -eq $versionProperty -or $null -eq $schemaProperty) {
        throw "Lattice's active-version.json is missing required fields."
    }
    $version = [string]$versionProperty.Value
    if ([int]$schemaProperty.Value -ne 1 -or $version -notmatch '^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$') {
        throw "Lattice's active-version.json names an invalid installed version."
    }

    $versionsRoot = Join-Path $InstallDestination "versions"
    $versionRoot = Join-Path $versionsRoot $version
    if (-not (Test-Path -LiteralPath $versionRoot -PathType Container)) {
        throw "Lattice's active version directory is missing: $version"
    }
    $versionItem = Get-Item -LiteralPath $versionRoot
    if (($versionItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Lattice's active version directory cannot be a reparse point."
    }

    foreach ($relative in @(
        "Lattice.exe",
        "Lattice.ico",
        "Server\LatticeServer.exe",
        "ui\index.html",
        "update-package.json"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $versionRoot $relative) -PathType Leaf)) {
            throw "Lattice's active version is incomplete; required file is missing: $relative"
        }
    }
    Assert-LatticePackageDirectory -PackageRoot $versionRoot -ExpectedVersion $version
    return Join-Path $versionRoot "Lattice.exe"
}

function Assert-LatticePackageDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackageRoot,
        [string]$ExpectedVersion
    )

    foreach ($relative in @(
        "Install Lattice.ps1",
        "Lattice.exe",
        "Lattice.ico",
        "Server\LatticeServer.exe",
        "ui\index.html",
        "library-layout.json",
        "library-taxonomy.json",
        "update-package.json",
        ".stignore"
    )) {
        if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot $relative) -PathType Leaf)) {
            throw "The Lattice package is incomplete; required file is missing: $relative"
        }
    }

    $metadataPath = Join-Path $PackageRoot "update-package.json"
    $metadataFile = Get-Item -LiteralPath $metadataPath
    if ($metadataFile.Length -le 0 -or $metadataFile.Length -gt 16KB) {
        throw "The Lattice package metadata has an unsafe size."
    }
    try {
        $metadata = Get-Content -LiteralPath $metadataPath -Raw | ConvertFrom-Json
    } catch {
        throw "The Lattice package metadata is malformed."
    }
    foreach ($propertyName in @("schemaVersion", "repository", "platform", "version")) {
        if ($null -eq $metadata.PSObject.Properties[$propertyName]) {
            throw "The Lattice package metadata is missing: $propertyName"
        }
    }
    $packageVersion = [string]$metadata.PSObject.Properties["version"].Value
    if (
        [int]$metadata.PSObject.Properties["schemaVersion"].Value -ne 1 -or
        [string]$metadata.PSObject.Properties["repository"].Value -ne "dreichner2/Lattice" -or
        [string]$metadata.PSObject.Properties["platform"].Value -ne "windows-x64" -or
        $packageVersion -notmatch '^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$'
    ) {
        throw "The Lattice package metadata names an unsupported package."
    }
    if (
        -not [string]::IsNullOrWhiteSpace($ExpectedVersion) -and
        -not [string]::Equals($packageVersion, $ExpectedVersion, [StringComparison]::Ordinal)
    ) {
        throw "The Lattice package version is $packageVersion, not the requested $ExpectedVersion."
    }
}

function Assert-SafeZipArchive {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchivePath,
        [Parameter(Mandatory = $true)]
        [string]$Destination
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $destinationRoot = (Resolve-SetupPath $Destination).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        foreach ($entry in $archive.Entries) {
            $entryName = [string]$entry.FullName
            if ([string]::IsNullOrWhiteSpace($entryName)) { continue }
            $segments = $entryName -split "[/\\]"
            if ([IO.Path]::IsPathRooted($entryName) -or ($segments -contains "..")) {
                throw "The Lattice archive contains an unsafe path: $entryName"
            }
            $target = [IO.Path]::GetFullPath((Join-Path $Destination $entryName))
            if (-not $target.StartsWith($destinationRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw "The Lattice archive would write outside its temporary directory: $entryName"
            }
        }
    } finally {
        $archive.Dispose()
    }
}

function Expand-LatticePackage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchivePath
    )

    $temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("LatticeSetup-" + [guid]::NewGuid().ToString("N"))
    New-Item -Path $temporaryRoot -ItemType Directory -Force | Out-Null
    try {
        Assert-SafeZipArchive -ArchivePath $ArchivePath -Destination $temporaryRoot
        Expand-Archive -LiteralPath $ArchivePath -DestinationPath $temporaryRoot -Force

        $installers = @(
            Get-ChildItem -LiteralPath $temporaryRoot -Filter "Install Lattice.ps1" -File -Recurse
        )
        if ($installers.Count -eq 0) {
            $nestedArchives = @(Get-ChildItem -LiteralPath $temporaryRoot -Filter "*.zip" -File -Recurse)
            if ($nestedArchives.Count -eq 1) {
                $nestedRoot = Join-Path $temporaryRoot "package"
                New-Item -Path $nestedRoot -ItemType Directory -Force | Out-Null
                Assert-SafeZipArchive -ArchivePath $nestedArchives[0].FullName -Destination $nestedRoot
                Expand-Archive -LiteralPath $nestedArchives[0].FullName -DestinationPath $nestedRoot -Force
                $installers = @(
                    Get-ChildItem -LiteralPath $nestedRoot -Filter "Install Lattice.ps1" -File -Recurse
                )
            }
        }
        if ($installers.Count -ne 1) {
            throw "The Lattice ZIP must contain exactly one 'Install Lattice.ps1' file."
        }

        $packageRoot = $installers[0].Directory.FullName
        Assert-LatticePackageDirectory $packageRoot
        return [pscustomobject]@{
            PackageRoot = $packageRoot
            CleanupRoot = $temporaryRoot
        }
    } catch {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Get-ChecksumFromFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ChecksumPath,
        [Parameter(Mandatory = $true)]
        [string]$ExpectedFileName
    )

    foreach ($line in @(Get-Content -LiteralPath $ChecksumPath)) {
        $match = [regex]::Match(
            [string]$line,
            "^\s*([0-9a-fA-F]{64})(?:\s+\*?(.+?))?\s*$"
        )
        if (-not $match.Success) { continue }
        $namedFile = $match.Groups[2].Value.Trim()
        if (
            -not [string]::IsNullOrWhiteSpace($namedFile) -and
            -not [string]::Equals(
                [IO.Path]::GetFileName($namedFile),
                $ExpectedFileName,
                [StringComparison]::OrdinalIgnoreCase
            )
        ) {
            continue
        }
        return $match.Groups[1].Value.ToUpperInvariant()
    }
    throw "The checksum file does not contain a SHA-256 for $ExpectedFileName."
}

function Assert-ArchiveChecksum {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ArchivePath,
        [Parameter(Mandatory = $true)]
        [string]$ChecksumPath
    )

    $expected = Get-ChecksumFromFile -ChecksumPath $ChecksumPath -ExpectedFileName ([IO.Path]::GetFileName($ArchivePath))
    $actual = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToUpperInvariant()
    if (-not [string]::Equals($expected, $actual, [StringComparison]::Ordinal)) {
        throw "Lattice package SHA-256 mismatch. Expected $expected but downloaded $actual."
    }
}

function Get-ReleaseLatticePackage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Version
    )

    if ($Version -notmatch '^v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$') {
        throw "LatticeVersion must be a pinned version such as v2.0.0."
    }

    $temporaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("LatticeDownload-" + [guid]::NewGuid().ToString("N"))
    New-Item -Path $temporaryRoot -ItemType Directory -Force | Out-Null
    $archivePath = Join-Path $temporaryRoot $script:LatticeAssetName
    $checksumPath = $archivePath + ".sha256"
    $assetUri = "$($script:ReleaseRoot)/$Version/$($script:LatticeAssetName)"
    $checksumUri = $assetUri + ".sha256"

    try {
        Write-Host "Downloading the pinned Lattice $Version Windows package..."
        Invoke-WebRequest -Uri $assetUri -OutFile $archivePath -UseBasicParsing
        Invoke-WebRequest -Uri $checksumUri -OutFile $checksumPath -UseBasicParsing
        Assert-ArchiveChecksum -ArchivePath $archivePath -ChecksumPath $checksumPath
        Write-Host "Verified Lattice package SHA-256."
        return [pscustomobject]@{
            ArchivePath = $archivePath
            CleanupRoot = $temporaryRoot
        }
    } catch {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force -ErrorAction SilentlyContinue
        throw
    }
}

function Resolve-SuppliedLatticePackage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackagePath
    )

    $path = Resolve-SetupPath $PackagePath
    if (Test-Path -LiteralPath $path -PathType Container) {
        Assert-LatticePackageDirectory $path
        return [pscustomobject]@{
            PackageRoot = $path
            CleanupRoot = $null
        }
    }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "The supplied Lattice package does not exist: $path"
    }
    if ([IO.Path]::GetExtension($path) -ne ".zip") {
        throw "LatticePackagePath must be a package directory or ZIP file."
    }

    $companion = $path + ".sha256"
    if (Test-Path -LiteralPath $companion -PathType Leaf) {
        Assert-ArchiveChecksum -ArchivePath $path -ChecksumPath $companion
        Write-Host "Verified the local Lattice package SHA-256."
    } else {
        Write-Warning "The explicitly supplied local ZIP has no .sha256 companion; treating it as operator-trusted local input."
    }
    return Expand-LatticePackage $path
}

function Invoke-LatticePackageInstall {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PackageRoot,
        [Parameter(Mandatory = $true)]
        [string]$InstallDestination
    )

    Assert-LatticePackageDirectory $PackageRoot
    $installer = Join-Path $PackageRoot "Install Lattice.ps1"
    & $installer -Destination $InstallDestination -NoLaunch |
        ForEach-Object { Write-Host ([string]$_) }
    $executable = Get-ActiveLatticeExecutable $InstallDestination
    if ([string]::IsNullOrWhiteSpace($executable)) {
        throw "Lattice installation did not produce a complete runtime at $InstallDestination."
    }
    return $executable
}

function Save-LatticeLibraryRoot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LibraryRoot,
        [Parameter(Mandatory = $true)]
        [bool]$ReplaceExisting
    )

    # Keep the intentional legacy state path so existing Lattice/CS Library users
    # retain their selected root and reader data after the product rename.
    $settingsRoot = Join-Path $env:LOCALAPPDATA "CS Library"
    $savedPath = Join-Path $settingsRoot "library-root.txt"
    if (Test-Path -LiteralPath $savedPath -PathType Leaf) {
        $savedRoot = (Get-Content -LiteralPath $savedPath -Raw).Trim()
        if (-not [string]::IsNullOrWhiteSpace($savedRoot)) {
            $savedFull = Resolve-SetupPath $savedRoot
            if (
                -not [string]::Equals($savedFull, $LibraryRoot, [StringComparison]::OrdinalIgnoreCase) -and
                -not $ReplaceExisting
            ) {
                throw "Lattice already points at '$savedFull'. Rerun with -ReplaceSavedLibraryRoot to change it to this clone."
            }
        }
    }

    New-Item -Path $settingsRoot -ItemType Directory -Force | Out-Null
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($savedPath, $LibraryRoot + [Environment]::NewLine, $utf8NoBom)
}

function Find-SyncthingExecutable {
    param(
        [string]$ExplicitPath
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        $resolved = Resolve-SetupPath $ExplicitPath
        if (-not (Test-Path -LiteralPath $resolved -PathType Leaf)) {
            throw "SyncthingExecutable does not exist: $resolved"
        }
        return $resolved
    }

    foreach ($commandName in @("syncthing.exe", "syncthing")) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $command -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
            return $command.Source
        }
    }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\syncthing.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Syncthing\syncthing.exe")
    )
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $candidates += Join-Path $env:ProgramFiles "Syncthing\syncthing.exe"
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }

    $wingetPackages = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path -LiteralPath $wingetPackages -PathType Container) {
        foreach ($packageDirectory in @(
            Get-ChildItem -LiteralPath $wingetPackages -Directory -Filter "Syncthing.Syncthing_*" |
                Sort-Object LastWriteTime -Descending
        )) {
            $foundExecutables = @(
                Get-ChildItem -LiteralPath $packageDirectory.FullName -Filter "syncthing.exe" -File -Recurse
            )
            if ($foundExecutables.Count -gt 0) { return $foundExecutables[0].FullName }
        }
    }
    return $null
}

function Install-Syncthing {
    $winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $winget) {
        throw "Syncthing is not installed and WinGet is unavailable. Install Syncthing $($script:SyncthingPackageVersion), or pass -SyncthingExecutable."
    }

    Write-Host "Installing Syncthing $($script:SyncthingPackageVersion) for this Windows user..."
    $arguments = @(
        "install",
        "--id", $script:SyncthingPackageId,
        "--exact",
        "--version", $script:SyncthingPackageVersion,
        "--source", "winget",
        "--scope", "user",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity"
    )
    & $winget.Source @arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "WinGet could not install Syncthing (exit code $exitCode)."
    }
}

function Get-SyncthingDeviceId {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string]$Home
    )

    $output = @(& $Executable device-id "--home=$Home" 2>&1)
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Syncthing could not read its local Device ID (exit code $exitCode)."
    }
    $deviceId = (@($output | ForEach-Object { ([string]$_).Trim() }) |
        Where-Object { $_ -match '^(?:[A-Z2-7]{7}-){7}[A-Z2-7]{7}$' } |
        Select-Object -Last 1)
    if ([string]::IsNullOrWhiteSpace($deviceId)) {
        throw "Syncthing returned an invalid local Device ID."
    }
    return $deviceId
}

function Initialize-SyncthingHome {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string]$Home
    )

    $configPath = Join-Path $Home "config.xml"
    if (Test-Path -LiteralPath $configPath -PathType Leaf) { return }
    New-Item -Path $Home -ItemType Directory -Force | Out-Null
    Write-Host "Generating a private per-user Syncthing identity..."
    & $Executable generate "--home=$Home" --no-port-probing | ForEach-Object { Write-Host ([string]$_) }
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0 -or -not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
        throw "Syncthing could not create its per-user configuration (exit code $exitCode)."
    }
}

function Get-SyncthingConnectionInfo {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Home
    )

    $configPath = Join-Path $Home "config.xml"
    [xml]$configuration = Get-Content -LiteralPath $configPath -Raw
    $gui = $configuration.configuration.gui
    if ($null -eq $gui) {
        throw "Syncthing's local GUI/API configuration is missing."
    }
    $enabled = [string]$gui.GetAttribute("enabled")
    if ($enabled -eq "false") {
        throw "Syncthing's local GUI/API is disabled. Enable it before running setup."
    }
    $tls = [string]$gui.GetAttribute("tls")
    if ([string]::IsNullOrWhiteSpace($tls)) {
        $tls = [string]$gui.GetAttribute("useTLS")
    }
    if ($tls -eq "true") {
        throw "This setup will not bypass certificate checks for a TLS-enabled Syncthing GUI. Use the default loopback HTTP GUI for onboarding."
    }

    $addressNode = $gui.SelectSingleNode("address")
    $address = ""
    if ($null -ne $addressNode) { $address = [string]$addressNode.InnerText }
    if ([string]::IsNullOrWhiteSpace($address)) { $address = "127.0.0.1:8384" }
    if ($address -match '^unix') {
        throw "A Unix-socket Syncthing GUI address is not supported on Windows."
    }
    try {
        $uri = [uri]("http://" + $address)
    } catch {
        throw "Syncthing has an unsupported GUI address: $address"
    }

    $hostName = $uri.Host
    if ($hostName -eq "0.0.0.0" -or $hostName -eq "::" -or $hostName -eq "[::]") {
        $hostName = "127.0.0.1"
    } elseif (-not $uri.IsLoopback -and $hostName -ne "localhost") {
        throw "Refusing to send the Syncthing API key to a non-loopback GUI address: $address"
    }

    $apiKeyNode = $gui.SelectSingleNode("apikey")
    if ($null -eq $apiKeyNode) { $apiKeyNode = $gui.SelectSingleNode("apiKey") }
    $apiKey = ""
    if ($null -ne $apiKeyNode) { $apiKey = [string]$apiKeyNode.InnerText }
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        throw "Syncthing's local API key is missing from config.xml."
    }

    return [pscustomobject]@{
        BaseUri = "http://$($hostName):$($uri.Port)"
        ApiKey = $apiKey
    }
}

function Wait-SyncthingHealth {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseUri,
        [int]$TimeoutSeconds = 40
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $health = Invoke-RestMethod -Uri "$BaseUri/rest/noauth/health" -Method Get -TimeoutSec 3
            if ([string]$health.status -eq "OK") { return }
        } catch {
            # Startup races are expected until the deadline.
        }
        Start-Sleep -Milliseconds 400
    } while ([DateTime]::UtcNow -lt $deadline)
    throw "Syncthing did not become healthy at its loopback API within $TimeoutSeconds seconds."
}

function Start-SyncthingIfNeeded {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string]$Home,
        [Parameter(Mandatory = $true)]
        [string]$BaseUri
    )

    try {
        $health = Invoke-RestMethod -Uri "$BaseUri/rest/noauth/health" -Method Get -TimeoutSec 2
        if ([string]$health.status -eq "OK") { return }
    } catch {
        # Start the current user's instance below.
    }

    $homeArgument = '--home="' + $Home + '"'
    $process = Start-Process -FilePath $Executable -ArgumentList @(
        "serve",
        "--no-browser",
        "--no-console",
        $homeArgument
    ) -WindowStyle Hidden -PassThru
    if ($null -eq $process) { throw "Windows did not start Syncthing." }
    Wait-SyncthingHealth -BaseUri $BaseUri
}

function Invoke-SyncthingApi {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseUri,
        [Parameter(Mandatory = $true)]
        [string]$ApiKey,
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [ValidateSet("Get", "Put", "Patch", "Post")]
        [string]$Method = "Get",
        [object]$Body
    )

    $parameters = @{
        Uri = $BaseUri + $Path
        Method = $Method
        Headers = @{ "X-API-Key" = $ApiKey }
        TimeoutSec = 10
    }
    if ($PSBoundParameters.ContainsKey("Body")) {
        $parameters.ContentType = "application/json"
        $parameters.Body = $Body | ConvertTo-Json -Depth 20 -Compress
    }
    return Invoke-RestMethod @parameters
}

function Get-SyncthingApiObjectOrNull {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseUri,
        [Parameter(Mandatory = $true)]
        [string]$ApiKey,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    try {
        return Invoke-SyncthingApi -BaseUri $BaseUri -ApiKey $ApiKey -Path $Path
    } catch {
        $response = $_.Exception.Response
        if ($null -ne $response -and [int]$response.StatusCode -eq 404) { return $null }
        throw
    }
}

function Set-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)]
        [object]$InputObject,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [object]$Value
    )

    if ($null -ne $InputObject.PSObject.Properties[$Name]) {
        $InputObject.$Name = $Value
    } else {
        $InputObject | Add-Member -NotePropertyName $Name -NotePropertyValue $Value
    }
}

function Configure-SyncthingLibrary {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BaseUri,
        [Parameter(Mandatory = $true)]
        [string]$ApiKey,
        [Parameter(Mandatory = $true)]
        [string]$LibraryRoot,
        [Parameter(Mandatory = $true)]
        [string]$LocalDeviceId
    )

    $encodedHub = [uri]::EscapeDataString($script:HubDeviceId)
    $hubPath = "/rest/config/devices/$encodedHub"
    $hub = Get-SyncthingApiObjectOrNull -BaseUri $BaseUri -ApiKey $ApiKey -Path $hubPath
    if ($null -eq $hub) {
        $hub = Invoke-SyncthingApi -BaseUri $BaseUri -ApiKey $ApiKey -Path "/rest/config/defaults/device"
        Set-ObjectProperty $hub "deviceID" $script:HubDeviceId
        Set-ObjectProperty $hub "name" "Lattice Mac mini hub"
        Set-ObjectProperty $hub "addresses" @("dynamic")
        Set-ObjectProperty $hub "introducer" $false
        Set-ObjectProperty $hub "autoAcceptFolders" $false
        Invoke-SyncthingApi -BaseUri $BaseUri -ApiKey $ApiKey -Path $hubPath -Method Put -Body $hub | Out-Null
    }

    $encodedFolder = [uri]::EscapeDataString($script:FolderId)
    $folderPath = "/rest/config/folders/$encodedFolder"
    $folder = Get-SyncthingApiObjectOrNull -BaseUri $BaseUri -ApiKey $ApiKey -Path $folderPath
    if ($null -ne $folder) {
        $existingRoot = Resolve-SetupPath ([string]$folder.path)
        if (-not [string]::Equals($existingRoot, $LibraryRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Syncthing folder '$($script:FolderId)' already points at '$existingRoot'. It was not changed."
        }
        if ([string]$folder.type -ne "sendreceive") {
            throw "Syncthing folder '$($script:FolderId)' already exists with type '$($folder.type)'. It was not changed."
        }
    } else {
        $folder = Invoke-SyncthingApi -BaseUri $BaseUri -ApiKey $ApiKey -Path "/rest/config/defaults/folder"
        Set-ObjectProperty $folder "id" $script:FolderId
    }

    $devicesById = [ordered]@{}
    foreach ($device in @($folder.devices)) {
        $id = [string]$device.deviceID
        if (-not [string]::IsNullOrWhiteSpace($id)) { $devicesById[$id] = $device }
    }
    if (-not $devicesById.Contains($LocalDeviceId)) {
        $devicesById[$LocalDeviceId] = [pscustomobject]@{ deviceID = $LocalDeviceId }
    }
    if (-not $devicesById.Contains($script:HubDeviceId)) {
        $devicesById[$script:HubDeviceId] = [pscustomobject]@{ deviceID = $script:HubDeviceId }
    }

    Set-ObjectProperty $folder "label" $script:FolderLabel
    Set-ObjectProperty $folder "path" $LibraryRoot
    Set-ObjectProperty $folder "type" "sendreceive"
    Set-ObjectProperty $folder "fsWatcherEnabled" $true
    Set-ObjectProperty $folder "paused" $false
    Set-ObjectProperty $folder "devices" @($devicesById.Values)
    Invoke-SyncthingApi -BaseUri $BaseUri -ApiKey $ApiKey -Path $folderPath -Method Put -Body $folder | Out-Null

    $verifiedHub = Get-SyncthingApiObjectOrNull -BaseUri $BaseUri -ApiKey $ApiKey -Path $hubPath
    $verifiedFolder = Get-SyncthingApiObjectOrNull -BaseUri $BaseUri -ApiKey $ApiKey -Path $folderPath
    if ($null -eq $verifiedHub -or $null -eq $verifiedFolder) {
        throw "Syncthing did not retain the Lattice device/folder configuration."
    }
    $verifiedIds = @($verifiedFolder.devices | ForEach-Object { [string]$_.deviceID })
    if ($verifiedIds -notcontains $LocalDeviceId -or $verifiedIds -notcontains $script:HubDeviceId) {
        throw "The Lattice Syncthing folder is not shared with both required devices."
    }
}

function Install-SyncthingStartupShortcut {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,
        [Parameter(Mandatory = $true)]
        [string]$Home
    )

    $startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
    New-Item -Path $startup -ItemType Directory -Force | Out-Null
    $shortcutPath = Join-Path $startup "Lattice Syncthing.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $Executable
    $shortcut.Arguments = 'serve --no-browser --no-console --home="' + $Home + '"'
    $shortcut.WorkingDirectory = $Home
    $shortcut.WindowStyle = 7
    $shortcut.Description = "Keep the Lattice library synchronized after Windows sign-in"
    $shortcut.Save()
}

function Write-LatticeSetupPlan {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LibraryRoot,
        [Parameter(Mandatory = $true)]
        [string]$InstallDestination,
        [Parameter(Mandatory = $true)]
        [string]$SyncthingHome,
        [string]$LatticePackagePath,
        [Parameter(Mandatory = $true)]
        [string]$LatticeVersion,
        [bool]$Offline
    )

    Write-Host "Lattice Windows onboarding plan (no changes):"
    Write-Host "  Library and Syncthing folder path: $LibraryRoot"
    Write-Host "  Lattice install path: $InstallDestination"
    if (-not [string]::IsNullOrWhiteSpace($LatticePackagePath)) {
        Write-Host "  Lattice source: local package $LatticePackagePath"
    } elseif (Test-LatticeInstall $InstallDestination) {
        Write-Host "  Lattice source: existing complete per-user installation"
    } elseif ($Offline) {
        Write-Host "  Lattice source: unavailable in offline mode; supply -LatticePackagePath"
    } else {
        Write-Host "  Lattice source: pinned GitHub Release $LatticeVersion with SHA-256 companion"
    }
    Write-Host "  Syncthing state: $SyncthingHome (outside the synchronized clone)"
    Write-Host "  Syncthing package: $($script:SyncthingPackageId) $($script:SyncthingPackageVersion) if not already installed"
    Write-Host "  Hub Device ID: $($script:HubDeviceId)"
    Write-Host "  Folder ID: $($script:FolderId) (send-receive)"
    Write-Host "  Final manual step: approve this PC's Device ID on the Mac mini hub and share the Lattice folder."
}

function Invoke-LatticeWindowsSetup {
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
    param(
        [Parameter(Mandatory = $true)]
        [string]$LibraryRoot,
        [string]$LatticePackagePath,
        [string]$LatticeVersion = $script:DefaultLatticeVersion,
        [string]$InstallDestination,
        [string]$SyncthingExecutable,
        [string]$SyncthingHome,
        [switch]$PlanOnly,
        [switch]$Offline,
        [switch]$NoLaunch,
        [switch]$ReinstallLattice,
        [switch]$ReplaceSavedLibraryRoot
    )

    if ($LatticeVersion -notmatch '^v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$') {
        throw "LatticeVersion must be a pinned stable version such as v2.0.0."
    }
    $requestedLatticeVersion = $LatticeVersion.Substring(1)
    $validated = Get-ValidatedLibraryLayout $LibraryRoot
    $root = $validated.Root
    $planning = $PlanOnly -or [bool]$WhatIfPreference
    $localStateRoot = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($localStateRoot)) {
        if (-not $planning) {
            throw "LOCALAPPDATA is unavailable. Run setup as the intended Windows user."
        }
        $localStateRoot = Join-Path ([IO.Path]::GetTempPath()) "Lattice-Windows-Plan"
    }
    if ([string]::IsNullOrWhiteSpace($InstallDestination)) {
        $InstallDestination = Join-Path $localStateRoot "Programs\Lattice"
    }
    $InstallDestination = Resolve-SetupPath $InstallDestination
    if ([string]::IsNullOrWhiteSpace($SyncthingHome)) {
        $SyncthingHome = Join-Path $localStateRoot "Syncthing"
    }
    $SyncthingHome = Resolve-SetupPath $SyncthingHome
    if (Test-PathInside -Candidate $SyncthingHome -Parent $root) {
        throw "SyncthingHome must stay outside the synchronized clone so certificates and API credentials can never sync."
    }

    if ($planning) {
        Write-LatticeSetupPlan `
            -LibraryRoot $root `
            -InstallDestination $InstallDestination `
            -SyncthingHome $SyncthingHome `
            -LatticePackagePath $LatticePackagePath `
            -LatticeVersion $LatticeVersion `
            -Offline ([bool]$Offline)
        return
    }
    if ($env:OS -ne "Windows_NT") {
        throw "This onboarding script must be run on the Windows PC. Use -PlanOnly for a non-mutating preview."
    }

    $downloadCleanup = $null
    $packageCleanup = $null
    $latticeExecutable = Get-ActiveLatticeExecutable $InstallDestination
    $activeLatticeVersion = if ([string]::IsNullOrWhiteSpace($latticeExecutable)) {
        ""
    } else {
        Split-Path -Leaf (Split-Path -Parent $latticeExecutable)
    }
    $needsLatticeInstall = (
        $ReinstallLattice -or
        [string]::IsNullOrWhiteSpace($latticeExecutable) -or
        -not [string]::Equals(
            $activeLatticeVersion,
            $requestedLatticeVersion,
            [StringComparison]::Ordinal
        )
    )
    try {
        if ($needsLatticeInstall) {
            $package = $null
            if (-not [string]::IsNullOrWhiteSpace($LatticePackagePath)) {
                $package = Resolve-SuppliedLatticePackage $LatticePackagePath
            } else {
                if ($Offline) {
                    throw "Lattice $requestedLatticeVersion is not active. Offline mode requires -LatticePackagePath pointing at that package directory or ZIP."
                }
                if (-not $PSCmdlet.ShouldProcess("Lattice $LatticeVersion", "Download and verify pinned Windows release")) { return }
                $download = Get-ReleaseLatticePackage $LatticeVersion
                $downloadCleanup = $download.CleanupRoot
                $package = Expand-LatticePackage $download.ArchivePath
            }
            $packageCleanup = $package.CleanupRoot
            Assert-LatticePackageDirectory `
                -PackageRoot $package.PackageRoot `
                -ExpectedVersion $requestedLatticeVersion
            if ($PSCmdlet.ShouldProcess($InstallDestination, "Install Lattice for the current user")) {
                $latticeExecutable = Invoke-LatticePackageInstall `
                    -PackageRoot $package.PackageRoot `
                    -InstallDestination $InstallDestination
            } else { return }
            $installedLatticeVersion = Split-Path -Leaf (Split-Path -Parent $latticeExecutable)
            if (-not [string]::Equals(
                $installedLatticeVersion,
                $requestedLatticeVersion,
                [StringComparison]::Ordinal
            )) {
                throw "Lattice installation activated $installedLatticeVersion instead of requested $requestedLatticeVersion."
            }
        } else {
            Write-Host "Using the existing complete Lattice $activeLatticeVersion installation at $InstallDestination."
        }

        if ($PSCmdlet.ShouldProcess($root, "Save as Lattice's selected library root")) {
            Save-LatticeLibraryRoot `
                -LibraryRoot $root `
                -ReplaceExisting ([bool]$ReplaceSavedLibraryRoot)
        }

        $syncthing = Find-SyncthingExecutable $SyncthingExecutable
        if ([string]::IsNullOrWhiteSpace($syncthing)) {
            if ($Offline) {
                throw "Syncthing is not installed. Offline mode requires -SyncthingExecutable pointing at syncthing.exe."
            }
            if ($PSCmdlet.ShouldProcess($script:SyncthingPackageId, "Install pinned Syncthing with WinGet")) {
                Install-Syncthing
            }
            $syncthing = Find-SyncthingExecutable $null
        }
        if ([string]::IsNullOrWhiteSpace($syncthing)) {
            throw "Syncthing installation finished, but syncthing.exe could not be located."
        }

        if ($PSCmdlet.ShouldProcess($SyncthingHome, "Generate or reuse the private per-user Syncthing identity")) {
            Initialize-SyncthingHome -Executable $syncthing -Home $SyncthingHome
        }
        $localDeviceId = Get-SyncthingDeviceId -Executable $syncthing -Home $SyncthingHome
        $connection = Get-SyncthingConnectionInfo $SyncthingHome
        if ($PSCmdlet.ShouldProcess("Syncthing loopback API", "Start the current user's Syncthing instance")) {
            Start-SyncthingIfNeeded -Executable $syncthing -Home $SyncthingHome -BaseUri $connection.BaseUri
        }

        $status = Invoke-SyncthingApi `
            -BaseUri $connection.BaseUri `
            -ApiKey $connection.ApiKey `
            -Path "/rest/system/status"
        if (-not [string]::Equals([string]$status.myID, $localDeviceId, [StringComparison]::Ordinal)) {
            throw "Another Syncthing instance owns $($connection.BaseUri). Its configuration was not changed."
        }

        if ($PSCmdlet.ShouldProcess($root, "Configure Lattice hub device and send-receive folder in Syncthing")) {
            Configure-SyncthingLibrary `
                -BaseUri $connection.BaseUri `
                -ApiKey $connection.ApiKey `
                -LibraryRoot $root `
                -LocalDeviceId $localDeviceId
        }
        if ($PSCmdlet.ShouldProcess("Current user's Startup folder", "Create Syncthing sign-in shortcut")) {
            Install-SyncthingStartupShortcut -Executable $syncthing -Home $SyncthingHome
        }

        Write-Host ""
        Write-Host "Windows setup is complete."
        Write-Host "Windows Device ID: $localDeviceId"
        Write-Host "Hub approval is still required: on the Mac mini, approve this Windows Device ID and share the Lattice folder."
        Write-Host "The Device ID is not a password, but exchange it privately. No GUI password or API key was printed."

        $setClipboard = Get-Command "Set-Clipboard" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $setClipboard) {
            if ($PSCmdlet.ShouldProcess("Windows clipboard", "Copy this PC's non-secret Syncthing Device ID")) {
                try {
                    Set-Clipboard -Value $localDeviceId
                    Write-Host "Copied the Windows Device ID to the clipboard; paste it only into the trusted Mac mini hub."
                } catch {
                    Write-Warning "Windows could not copy the Device ID; copy it from this window instead."
                }
            }
        } else {
            Write-Host "Clipboard support is unavailable, so copy the Windows Device ID from this window."
        }

        if (-not $NoLaunch) {
            if ($PSCmdlet.ShouldProcess($latticeExecutable, "Launch Lattice")) {
                Start-Process -FilePath $latticeExecutable | Out-Null
            }
        }
    } finally {
        foreach ($cleanupRoot in @($packageCleanup, $downloadCleanup)) {
            if (-not [string]::IsNullOrWhiteSpace([string]$cleanupRoot)) {
                Remove-Item -LiteralPath $cleanupRoot -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

Export-ModuleMember -Function Invoke-LatticeWindowsSetup
