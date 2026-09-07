<#
.SYNOPSIS
    Builds the Draft Assistant Windows installer.

.DESCRIPTION
    Runs PyInstaller against packaging/DraftAssistant.spec, then compiles
    packaging/windows/DraftAssistant.iss with Inno Setup.

    Output: dist/installers/DraftAssistant-Setup-<version>.exe

.PARAMETER SkipInstaller
    Build the unpacked app only and skip the Inno Setup step. Useful when
    Inno Setup is not installed, or for a quick smoke test.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#>
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BuildVenv = Join-Path $Root ".venv-build"
$Python = Join-Path $BuildVenv "Scripts\python.exe"
$PyInstallerDist = Join-Path $Root "dist\pyinstaller"
$AppDir = Join-Path $PyInstallerDist "DraftAssistant"
$InstallerDir = Join-Path $Root "dist\installers"

Set-Location $Root

$Version = (& python -c "import draft_assistant; print(draft_assistant.__version__)").Trim()
Write-Host "Building Draft Assistant $Version (Windows)" -ForegroundColor Cyan

# --- build venv -----------------------------------------------------------
if (!(Test-Path $Python)) {
    Write-Host "Creating build venv..." -ForegroundColor DarkGray
    python -m venv $BuildVenv
}
& $Python -m pip install --upgrade pip --quiet
& $Python -m pip install -r (Join-Path $Root "requirements-build.txt") --quiet
& $Python -m pip install -r (Join-Path $Root "requirements-desktop.txt") --quiet

# --- release gate ---------------------------------------------------------
# Refuse to ship a silently degraded board (for example, a single-source pull
# with no byes/history or an entire position with empty projections).
& $Python (Join-Path $Root "scripts\check_projection_quality.py") `
    (Join-Path $Root "data\projections.json")
if ($LASTEXITCODE -ne 0) { throw "Projection quality gate failed - not shipping this board." }

# --- icons ----------------------------------------------------------------
& $Python (Join-Path $Root "packaging\make_icons.py")

# --- PyInstaller ----------------------------------------------------------
Remove-Item -LiteralPath $AppDir -Recurse -Force -ErrorAction SilentlyContinue
& $Python -m PyInstaller `
    (Join-Path $Root "packaging\DraftAssistant.spec") `
    --noconfirm `
    --clean `
    --distpath $PyInstallerDist `
    --workpath (Join-Path $Root "build\pyinstaller")

if (!(Test-Path (Join-Path $AppDir "DraftAssistant.exe"))) {
    throw "PyInstaller did not produce DraftAssistant.exe"
}

# --- smoke test -----------------------------------------------------------
# Point the build at a throwaway data dir and confirm it serves the UI, so a
# broken bundle fails here rather than on a tester's machine.
Write-Host "Smoke-testing the packaged app..." -ForegroundColor DarkGray
& (Join-Path $Root "packaging\windows\smoke_test.ps1") -AppDir $AppDir

if ($SkipInstaller) {
    Write-Host "`nUnpacked app: $AppDir" -ForegroundColor Green
    Write-Host "Skipped installer (-SkipInstaller)."
    return
}

# --- Inno Setup -----------------------------------------------------------
# winget installs Inno Setup per-user by default, hence the LOCALAPPDATA entry.
$Iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $Iscc) {
    $Iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
}
if (-not $Iscc) {
    Write-Warning "Inno Setup 6 not found. Install it with:"
    Write-Warning "    winget install -e --id JRSoftware.InnoSetup"
    Write-Warning "Then re-run this script. The unpacked app is ready at: $AppDir"
    return
}

New-Item -ItemType Directory -Force -Path $InstallerDir | Out-Null
& $Iscc `
    "/DAppVersion=$Version" `
    "/DSourceDir=$AppDir" `
    (Join-Path $Root "packaging\windows\DraftAssistant.iss")

$Setup = Join-Path $InstallerDir "DraftAssistant-Setup-$Version.exe"
Write-Host ""
Write-Host "Installer created:" -ForegroundColor Green
Write-Host "  $Setup"
Write-Host ""
Write-Host "Note: this installer is unsigned, so Windows SmartScreen will show" -ForegroundColor Yellow
Write-Host "'Windows protected your PC'. Testers click More info > Run anyway." -ForegroundColor Yellow
