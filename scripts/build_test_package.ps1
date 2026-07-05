param(
    [string]$PackageName = "DraftAssistant-test-package"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Resolve-Path (Join-Path $ScriptDir "..")
$BuildVenv = Join-Path $Root ".venv-build"
$BuildDir = Join-Path $Root "build"
$DistDir = Join-Path $Root "dist"
$PyInstallerDist = Join-Path $DistDir "pyinstaller"
$PackageDir = Join-Path $DistDir $PackageName
$ZipPath = "$PackageDir.zip"

function Copy-RequiredFile($Source, $Destination) {
    if (!(Test-Path $Source)) {
        throw "Required file not found: $Source"
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Force
}

Set-Location $Root

if (!(Test-Path $BuildVenv)) {
    python -m venv $BuildVenv
}

$Python = Join-Path $BuildVenv "Scripts\python.exe"
& $Python -m pip install --upgrade pip
& $Python -m pip install pyinstaller

Remove-Item -LiteralPath $PyInstallerDist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PackageDir -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $ZipPath -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $DistDir | Out-Null

$StaticSpec = "$(Join-Path $Root "draft_assistant\web\static");draft_assistant\web\static"
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --console `
    --name DraftAssistant `
    --distpath $PyInstallerDist `
    --workpath (Join-Path $BuildDir "pyinstaller") `
    --specpath $BuildDir `
    --add-data $StaticSpec `
    (Join-Path $Root "packaging\windows_web_launcher.py")

New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null
Copy-Item -Path (Join-Path $PyInstallerDist "DraftAssistant\*") -Destination $PackageDir -Recurse -Force

New-Item -ItemType Directory -Force -Path (Join-Path $PackageDir "data") | Out-Null
Copy-RequiredFile (Join-Path $Root "data\projections.json") (Join-Path $PackageDir "data\projections.json")
Copy-RequiredFile (Join-Path $Root "league.config.yaml") (Join-Path $PackageDir "league.config.yaml")
Copy-RequiredFile (Join-Path $Root "draft_state.json") (Join-Path $PackageDir "draft_state.json")

@"
@echo off
cd /d "%~dp0"
start "" DraftAssistant.exe
"@ | Set-Content -LiteralPath (Join-Path $PackageDir "Start Draft Assistant.bat") -Encoding ASCII

@"
Draft Assistant test package

How to run:
1. Unzip the whole folder.
2. Double-click "Start Draft Assistant.bat".
3. Your browser should open automatically. If it does not, copy the local URL shown in the console window.
4. Keep the console window open while testing. Closing it stops the app.

Notes:
- No Python install is required.
- Draft state, league config, and player data live inside this folder.
- This is a local-only app. It starts a server on 127.0.0.1 and opens your browser.
"@ | Set-Content -LiteralPath (Join-Path $PackageDir "README_TESTER.txt") -Encoding ASCII

Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath -Force

Write-Host ""
Write-Host "Package created:"
Write-Host $ZipPath
