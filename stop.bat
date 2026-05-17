@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo Stopping AI Email Organizer background service...
taskkill /F /IM AIEmailOrganizer.exe >nul 2>nul
taskkill /F /FI "WINDOWTITLE eq AI Email Organizer*" >nul 2>nul
for /f "tokens=2" %%P in ('tasklist /v ^| findstr /i "AI Email Organizer Background Service"') do taskkill /F /PID %%P >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$listeners = Get-NetTCPConnection -LocalPort 4597 -State Listen -ErrorAction SilentlyContinue; foreach ($listener in $listeners) { $proc = Get-CimInstance Win32_Process -Filter \"ProcessId=$($listener.OwningProcess)\" -ErrorAction SilentlyContinue; if ($proc -and ($proc.CommandLine -like '*AI36*' -or $proc.CommandLine -like '*AIEmailOrganizer*' -or $proc.CommandLine -like '*backend*' -or $proc.CommandLine -like '*main.py*')) { Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue } }" >nul 2>nul
echo Done.
