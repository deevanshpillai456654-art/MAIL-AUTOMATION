@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "APP_NAME=AI Email Organizer"

reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "%APP_NAME%" /f >nul 2>nul
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v "%APP_NAME%" /f >nul 2>nul

set "STARTUP_LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AI Email Organizer.lnk"
if exist "%STARTUP_LNK%" del /f /q "%STARTUP_LNK%" >nul 2>nul

echo Startup disabled for AI Email Organizer.
exit /b 0
