param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$studioPython = Join-Path $PSScriptRoot '.venv-studio\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $studioPython)) { throw 'Set up .venv-studio first; see docs/studio.md.' }
if (-not (Test-Path -LiteralPath 'studio/web/vendor/three.module.js')) { throw 'Run npm ci and npm run setup:web first.' }
if (-not $OpenBrowser) {
    & $studioPython -m studio serve --port 8090
    exit $LASTEXITCODE
}
$studioOrigin = 'http://127.0.0.1:8090'
$studioReady = $false
try {
    $studioPage = Invoke-WebRequest -Uri "$studioOrigin/" -UseBasicParsing -TimeoutSec 2
    if ($studioPage.Content -notmatch 'GelSight Material Studio') { throw 'Port 8090 is occupied by another application.' }
    $studioReady = $true
} catch {
    if ($_.Exception.Message -like '*occupied*') { throw }
}
if (-not $studioReady) {
    $studioLogs = Join-Path $PSScriptRoot 'studio-data\logs'
    New-Item -ItemType Directory -Force -Path $studioLogs | Out-Null
    $studioServer = Start-Process -FilePath $studioPython -ArgumentList @('-m','studio','serve','--port','8090') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $studioLogs 'server-output.log') -RedirectStandardError (Join-Path $studioLogs 'server-error.log') -PassThru
    for ($studioAttempt = 0; $studioAttempt -lt 40; $studioAttempt++) {
        Start-Sleep -Milliseconds 250
        try {
            $studioPage = Invoke-WebRequest -Uri "$studioOrigin/" -UseBasicParsing -TimeoutSec 1
            if ($studioPage.Content -match 'GelSight Material Studio') { $studioReady = $true; break }
        } catch {}
        if ($studioServer.HasExited) { break }
    }
    if (-not $studioReady) { throw 'Studio did not start. See studio-data\logs\server-error.log.' }
}
$studioNode = (Get-Command node -ErrorAction Stop).Source
Start-Process -FilePath $studioNode -ArgumentList @('tools/launch-studio-browser.mjs') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden | Out-Null
Write-Host 'Opening GelSight Material Studio in its dedicated Chrome window.'
