$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$studioPython = Join-Path $PSScriptRoot '.venv-studio\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $studioPython)) { throw 'Set up .venv-studio first; see docs/studio.md.' }
if (-not (Test-Path -LiteralPath 'studio/web/vendor/three.module.js')) { throw 'Run npm ci and npm run setup:web first.' }
& $studioPython -m studio serve --port 8090
