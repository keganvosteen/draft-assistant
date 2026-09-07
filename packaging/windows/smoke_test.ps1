<#
.SYNOPSIS
    Verifies a packaged Windows build actually boots and serves the UI.

.DESCRIPTION
    Runs the built exe in browser mode against a throwaway data directory,
    then checks that the static UI and the /api/state endpoint respond. This
    catches the classic PyInstaller failure where the bundle builds fine but
    is missing a data file or a hidden import at runtime.
#>
param(
    [Parameter(Mandatory = $true)][string]$AppDir,
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

$Exe = Join-Path $AppDir "DraftAssistant.exe"
if (!(Test-Path $Exe)) { throw "Not found: $Exe" }

$DataDir = Join-Path $env:TEMP "DraftAssistant-smoke-$([guid]::NewGuid().ToString('N'))"
$Port = Get-Random -Minimum 49200 -Maximum 65000
$proc = $null

# Set on the parent and let the child inherit: Start-Process -Environment needs
# PowerShell 7.4+, and this script has to run under whatever the CI image ships.
$saved = @{}
foreach ($name in "DRAFT_ASSISTANT_HOME", "DRAFT_ASSISTANT_PORT", "DRAFT_ASSISTANT_NO_OPEN") {
    $saved[$name] = [Environment]::GetEnvironmentVariable($name)
}
$env:DRAFT_ASSISTANT_HOME = $DataDir
$env:DRAFT_ASSISTANT_PORT = "$Port"
$env:DRAFT_ASSISTANT_NO_OPEN = "1"

try {
    $proc = Start-Process -FilePath $Exe -ArgumentList "--browser" -PassThru

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($proc.HasExited) {
            throw "App exited early with code $($proc.ExitCode)"
        }
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/state" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }

    if (-not $ready) { throw "App did not serve /api/state within $TimeoutSeconds seconds" }

    $index = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec 5
    if ($index.Content -notmatch "(?i)draft") {
        throw "Served index.html does not look like the Draft Assistant UI"
    }

    $board = Join-Path $DataDir "data\projections.json"
    if (!(Test-Path $board)) { throw "First-run seeding did not create $board" }
    $players = (Get-Content $board -Raw | ConvertFrom-Json).players.Count
    if ($players -lt 1) { throw "Seeded player board is empty" }

    $context = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/context" -TimeoutSec 5
    if ($null -eq $context.stale -or $null -eq $context.sources) {
        throw "/api/context did not return the freshness contract"
    }
    $update = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/update" -TimeoutSec 10
    if ($null -eq $update.currentVersion -or $null -eq $update.updateAvailable) {
        throw "/api/update did not return the version contract"
    }

    Write-Host "  smoke test OK - served UI, context/update APIs, seeded $players players" -ForegroundColor Green
}
finally {
    if ($proc -and -not $proc.HasExited) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $DataDir -Recurse -Force -ErrorAction SilentlyContinue
    foreach ($name in $saved.Keys) {
        Set-Item -Path "Env:$name" -Value $saved[$name] -ErrorAction SilentlyContinue
    }
}
