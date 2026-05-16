@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_NAME=AI Email Organizer"
set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
set "VBS_PATH=%BASE_DIR%\start_background.vbs"
set "WSCRIPT_PATH=%SystemRoot%\System32\wscript.exe"

if not exist "%VBS_PATH%" (
    echo ERROR: %VBS_PATH% was not found.
    exit /b 1
)

set "START_CMD=""%WSCRIPT_PATH%"" //B //Nologo ""%VBS_PATH%"""

reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "%APP_NAME%" /t REG_SZ /d "%START_CMD%" /f >nul 2>nul
if errorlevel 1 (
    echo ERROR: Could not create HKCU startup entry.
    exit /b 1
)

rem HKLM is best-effort. It helps all-users installs from Inno, but may fail without elevation.
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "%APP_NAME%" /t REG_SZ /d "%START_CMD%" /f >nul 2>nul

set "AIO_VBS_PATH=%VBS_PATH%"
set "AIO_BASE_DIR=%BASE_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$startup=[Environment]::GetFolderPath('Startup'); if ($startup) { $shell=New-Object -ComObject WScript.Shell; $shortcut=$shell.CreateShortcut((Join-Path $startup 'AI Email Organizer.lnk')); $shortcut.TargetPath=$env:SystemRoot + '\System32\wscript.exe'; $shortcut.Arguments='//B //Nologo ""' + $env:AIO_VBS_PATH + '""'; $shortcut.WorkingDirectory=$env:AIO_BASE_DIR; $shortcut.WindowStyle=7; $shortcut.Save() }" >nul 2>nul
if errorlevel 1 echo WARNING: Startup-folder shortcut could not be created, registry startup is still enabled.

echo Startup enabled for AI Email Organizer.
exit /b 0
