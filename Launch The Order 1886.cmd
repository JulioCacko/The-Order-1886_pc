@echo off
setlocal
cd /d "%~dp0"
rem Source checkout: start the Go launcher built in launcher-go (see docs/order1886-build.md).
set "LAUNCHER=launcher-go\build\bin\The Order 1886.exe"
if not exist "%LAUNCHER%" (
    echo Go launcher not built yet: "%LAUNCHER%" is missing.
    echo Build it as described in docs\order1886-build.md, or use the release package.
    pause
    exit /b 1
)
start "" "%LAUNCHER%" --project-root "%~dp0."
