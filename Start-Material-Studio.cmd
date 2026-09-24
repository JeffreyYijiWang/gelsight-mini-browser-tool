@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -File "%~dp0start-studio.ps1" -OpenBrowser
if errorlevel 1 pause
