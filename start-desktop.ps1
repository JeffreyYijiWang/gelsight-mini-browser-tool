param([string]$Project = '', [switch]$Setup, [ValidateSet('ffmpeg','windows')][string]$CameraBackend = 'ffmpeg')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$desktopPython = Join-Path $PSScriptRoot '.venv-studio\Scripts\python.exe'
if (!(Test-Path -LiteralPath $desktopPython)) {
    py -3.11 -m venv .venv-studio
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 and try again.' }
    $Setup = $true
}
if ($Setup) {
    & $desktopPython -m pip install --use-feature=truststore -r requirements-desktop.txt
    if ($LASTEXITCODE -ne 0) { throw 'Desktop dependency installation failed.' }
}
& $desktopPython -c 'import PySide6, pyqtgraph, OpenGL'
if ($LASTEXITCODE -ne 0) { throw 'Run .\start-desktop.ps1 -Setup once to install the native dependencies.' }
$env:QT_MEDIA_BACKEND = $CameraBackend
$desktopArgs = @('-m', 'desktop_studio')
if ($Project) { $desktopArgs += @('--project', $Project) }
& $desktopPython @desktopArgs
if ($LASTEXITCODE -ne 0) { throw 'Desktop application exited with an error. See the messages above.' }
