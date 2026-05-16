@echo off
setlocal EnableDelayedExpansion

echo ================================================
echo INTEMO - Uninstallation
echo ================================================
echo.

set "APP_NAME=AIEmailOrganizer"

echo Checking administrator privileges...
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] This script requires administrator privileges.
    echo Please right-click and select "Run as administrator"
    pause
    exit /b 1
)

echo.
echo Getting installation path from registry...
for /f "tokens=2*" %%a in ('reg query "HKLM\Software\%APP_NAME%" /v InstallPath 2^>nul') do set "INSTALL_PATH=%%b"

if not defined INSTALL_PATH (
    for /f "tokens=2*" %%a in ('reg query "HKCU\Software\%APP_NAME%" /v InstallPath 2^>nul') do set "INSTALL_PATH=%%b"
)

if not defined INSTALL_PATH (
    set "INSTALL_PATH=C:\Program Files\AIEmailOrganizer"
)

echo Installation path: %INSTALL_PATH%
echo.

set /p CONFIRM="Are you sure you want to uninstall? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo Uninstallation cancelled.
    exit /b 0
)

echo.
echo Step 1: Stopping application processes...
taskkill /F /IM "AIEmailOrganizer.exe" >nul 2>&1
taskkill /F /IM "python.exe" /FI "WINDOWTITLE eq AIEmailOrganizer*" >nul 2>&1
echo Done.

echo.
echo Step 2: Removing auto-start registry entries...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "%APP_NAME%" /f >nul 2>&1
echo Done.

echo.
echo Step 3: Removing firewall rules...
netsh advfirewall firewall delete rule name="INTEMO" >nul 2>&1
echo Done.

echo.
echo Step 4: Removing file associations...
reg delete "HKCR\.aieo" /f >nul 2>&1
reg delete "HKCR\%APP_NAME%.Config" /f >nul 2>&1
echo Done.

echo.
echo Step 5: Removing Start Menu shortcuts...
if exist "%ProgramData%\Microsoft\Windows\Start Menu\Programs\AIEmailOrganizer" (
    rmdir /S /Q "%ProgramData%\Microsoft\Windows\Start Menu\Programs\AIEmailOrganizer"
)
echo Done.

echo.
echo Step 6: Removing desktop shortcut...
for /f "tokens=2*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Desktop" /v Namespace 2^>nul') do (
    set "DESKTOP_FOLDER=%%b"
)
if defined DESKTOP_FOLDER (
    del /Q /F "%USERPROFILE%\Desktop\AIEmailOrganizer.lnk" >nul 2>&1
)
echo Done.

echo.
echo Step 7: Removing registry entries...
reg delete "HKLM\Software\%APP_NAME%" /f >nul 2>&1
reg delete "HKCU\Software\%APP_NAME%" /f >nul 2>&1
echo Done.

echo.
echo Step 8: Backing up user data...
set "BACKUP_PATH=%USERPROFILE%\Documents\AIEmailOrganizer_Backup_%date:~-4%%date:~4,2%%date:~7,2%"
if exist "%INSTALL_PATH%\data" (
    mkdir "%BACKUP_PATH%" 2>nul
    xcopy /E /Y /Q "%INSTALL_PATH%\data\*" "%BACKUP_PATH%\" >nul 2>&1
    echo User data backed up to: %BACKUP_PATH%
)
echo Done.

echo.
echo Step 9: Removing application files...
if exist "%INSTALL_PATH%" (
    rmdir /S /Q "%INSTALL_PATH%"
)
echo Done.

echo.
echo Step 10: Cleaning up remaining files...
del /Q /F /S "%APPDATA%\%APP_NAME%" >nul 2>&1
del /Q /F /S "%LOCALAPPDATA%\%APP_NAME%" >nul 2>&1
echo Done.

echo.
echo ================================================
echo Uninstallation completed!
echo ================================================
echo.
echo User data has been backed up to:
echo %BACKUP_PATH%
echo.
echo Thank you for using INTEMO.
echo.

pause
exit /b 0