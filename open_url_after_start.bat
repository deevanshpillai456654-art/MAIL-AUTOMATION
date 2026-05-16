@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PAGE=%~1"
if "%PAGE%"=="" set "PAGE=dashboard"
set "URL=http://127.0.0.1:4597/dashboard"
if /I "%PAGE%"=="admin" set "URL=http://127.0.0.1:4597/admin"
if /I "%PAGE%"=="setup" set "URL=http://127.0.0.1:4597/setup"
if /I "%PAGE%"=="docs" set "URL=http://127.0.0.1:4597/docs"

wscript.exe //B //Nologo "%~dp0start_background.vbs"

for /L %%I in (1,1,45) do (
    call "%~dp0check_service.bat" >nul 2>nul
    if !ERRORLEVEL! EQU 0 goto :open
    timeout /t 1 /nobreak >nul
)

echo AI Email Organizer is still starting in the background.
echo Opening %URL% now. Refresh the browser in a few seconds if it has not loaded yet.

:open
start "" "%URL%"
exit /b 0
