[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [string]$LibraryRoot,
    [string]$LatticePackagePath,
    [string]$LatticeVersion = "v2.2.5",
    [string]$InstallDestination,
    [string]$SyncthingExecutable,
    [string]$SyncthingHome,
    [switch]$PlanOnly,
    [switch]$Offline,
    [switch]$NoLaunch,
    [switch]$ReinstallLattice,
    [switch]$ReplaceSavedLibraryRoot
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($LibraryRoot)) {
    # Windows PowerShell 5.1 does not reliably populate $PSScriptRoot while
    # parameter default expressions are being evaluated. Resolve the clone
    # root from the script location only after parameter binding completes.
    $LibraryRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
}
$modulePath = Join-Path $PSScriptRoot "LatticeWindowsSetup.psm1"
Import-Module $modulePath -Force

$parameters = @{
    LibraryRoot = $LibraryRoot
    LatticeVersion = $LatticeVersion
    PlanOnly = $PlanOnly
    Offline = $Offline
    NoLaunch = $NoLaunch
    ReinstallLattice = $ReinstallLattice
    ReplaceSavedLibraryRoot = $ReplaceSavedLibraryRoot
}
foreach ($name in @(
    "LatticePackagePath",
    "InstallDestination",
    "SyncthingExecutable",
    "SyncthingHome"
)) {
    if ($PSBoundParameters.ContainsKey($name)) {
        $parameters[$name] = $PSBoundParameters[$name]
    }
}
if ($PSBoundParameters.ContainsKey("WhatIf")) { $parameters["WhatIf"] = [bool]$PSBoundParameters["WhatIf"] }
if ($PSBoundParameters.ContainsKey("Confirm")) { $parameters["Confirm"] = $PSBoundParameters["Confirm"] }
if ($PSBoundParameters.ContainsKey("Verbose")) { $parameters["Verbose"] = [bool]$PSBoundParameters["Verbose"] }

Invoke-LatticeWindowsSetup @parameters
