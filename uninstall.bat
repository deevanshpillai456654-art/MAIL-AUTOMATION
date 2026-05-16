@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Stopping AI Email Organizer background service...
taskkill /F /IM AIEmailOrganizer.exe >nul 2>nul
for /f "tokens=2" %%P in ('tasklist /v ^| findstr /i "AI Email Organizer Background Service"') do taskkill /F /PID %%P >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq AI Email Organizer*" >nul 2>nul
echo Done.
