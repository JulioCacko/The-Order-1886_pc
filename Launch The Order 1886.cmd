@echo off
setlocal
cd /d "%~dp0"
if exist "dist\order1886\The Order 1886\The Order 1886.exe" (
    start "" "dist\order1886\The Order 1886\The Order 1886.exe" --state-dir "%~dp0user\order1886"
    exit /b 0
)
python launcher\order1886_launcher.py
if errorlevel 1 pause
