@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo AI Email Organizer Service Manager
echo.
echo 1. Start in background
echo 2. Open Dashboard
echo 3. Open Admin
echo 4. Open Setup
echo 5. Stop background service
echo.
set /p CHOICE=Choose option: 
if "%CHOICE%"=="1" wscript.exe //B //Nologo "%~dp0start_background.vbs"
if "%CHOICE%"=="2" call "%~dp0open_url_after_start.bat" dashboard
if "%CHOICE%"=="3" call "%~dp0open_url_after_start.bat" admin
if "%CHOICE%"=="4" call "%~dp0open_url_after_start.bat" setup
if "%CHOICE%"=="5" call "%~dp0stop.bat"
