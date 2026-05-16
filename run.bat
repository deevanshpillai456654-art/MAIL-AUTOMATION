@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title AI Email Organizer Launcher

echo ============================================================
echo AI Email Organizer
echo ============================================================
echo Starting local service and dashboard...
echo.

call "%~dp0check_service.bat" >nul 2>nul
if !ERRORLEVEL! EQU 0 goto :open

if exist "%~dp0install_runtime_deps.bat" (
    if not exist "%~dp0.venv\Scripts\python.exe" if not exist "%~dp0AIEmailOrganizer.exe" (
        echo First run: installing local Python dependencies...
        call "%~dp0install_runtime_deps.bat"
        if !ERRORLEVEL! NEQ 0 goto :failed
    )
)

wscript.exe //B //Nologo "%~dp0start_background.vbs"

for /L %%I in (1,1,45) do (
    call "%~dp0check_service.bat" >nul 2>nul
    if !ERRORLEVEL! EQU 0 goto :open
    timeout /t 1 /nobreak >nul
)

goto :failed

:open
echo Service is running.
echo Opening dashboard: http://127.0.0.1:4597/dashboard
start "" "http://127.0.0.1:4597/dashboard"
echo.
echo Runtime data is stored under %%LOCALAPPDATA%%\AIEmailOrganizer so connected accounts survive restart and upgrades.
timeout /t 3 /nobreak >nul
exit /b 0

:failed
echo.
echo ERROR: AI Email Organizer did not start.
echo.
set "AIO_LOG_DIR=%LOCALAPPDATA%\AIEmailOrganizer\logs"
if not defined LOCALAPPDATA set "AIO_LOG_DIR=%APPDATA%\AIEmailOrganizer\logs"
echo Recent launcher log:
if exist "%AIO_LOG_DIR%\launcher.log" powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content '%AIO_LOG_DIR%\launcher.log' -Tail 30" 2>nul
echo.
echo Recent service log:
if exist "%AIO_LOG_DIR%\service.log" powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content '%AIO_LOG_DIR%\service.log' -Tail 40" 2>nul
echo.
echo Press any key to close.
pause >nul
exit /b 1
