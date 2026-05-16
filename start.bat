@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title AI Email Organizer Launcher
if /I "%~1"=="--startup" (
    wscript.exe //B //Nologo "%~dp0start_background.vbs"
    exit /b 0
)
call "%~dp0open_url_after_start.bat" dashboard
exit /b %ERRORLEVEL%
