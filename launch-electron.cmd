@echo off
setlocal

cd /d "%~dp0"
title Zenonzard Electron Launcher
set "PYTHONIOENCODING=utf-8"

echo.
echo Starting Zenonzard Electron...
echo Project: %CD%
echo.

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm was not found in PATH.
  echo Please install Node.js or open this from a shell where npm is available.
  echo.
  pause
  exit /b 1
)

if not exist "package.json" (
  echo [ERROR] package.json was not found next to this launcher.
  echo Put launch-electron.cmd in the project root and try again.
  echo.
  pause
  exit /b 1
)

echo Closing previous Zenonzard Electron windows, if any...
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$target = (Join-Path (Get-Location) 'node_modules\electron\dist\electron.exe'); Get-Process electron -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $target } | ForEach-Object { $_.Id }"`) do (
  taskkill /PID %%P /T /F >nul 2>nul
)
echo.

if not exist "node_modules\.bin\electron.cmd" (
  echo Electron dependencies were not found. Installing npm dependencies once...
  call npm install
  if errorlevel 1 (
    echo.
    echo [ERROR] npm install failed.
    pause
    exit /b 1
  )
)

if /I "%~1"=="--check" (
  echo Launcher check passed.
  exit /b 0
)

echo Launching desktop client...
echo.
call npm run electron:dev

if errorlevel 1 (
  echo.
  echo [ERROR] Electron exited with an error.
  pause
  exit /b 1
)

endlocal
