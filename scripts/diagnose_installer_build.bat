@echo off
setlocal EnableExtensions
cd /d "%~dp0.."

echo ============================================================
echo INTEMO - Installer Build Diagnostics
echo ============================================================
echo Current folder: %CD%
echo.

echo [Project files]
if exist scripts\build_installer.bat (echo OK scripts\build_installer.bat) else (echo MISSING scripts\build_installer.bat)
if exist scripts\installer.iss (echo OK scripts\installer.iss) else (echo MISSING scripts\installer.iss)
if exist scripts\prepare_installer_payload.py (echo OK scripts\prepare_installer_payload.py) else (echo MISSING scripts\prepare_installer_payload.py)
if exist local-service\requirements.txt (echo OK local-service\requirements.txt) else (echo MISSING local-service\requirements.txt)
if exist dist\AIEmailOrganizer (echo OK dist\AIEmailOrganizer) else (echo MISSING dist\AIEmailOrganizer)
echo.

echo [Python]
py -0p 2>nul
py -3.11 --version 2>nul
py -3.12 --version 2>nul
py -3.13 --version 2>nul
python --version 2>nul
echo.

echo [Inno Setup]
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" echo OK "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" echo OK "%ProgramFiles%\Inno Setup 6\ISCC.exe"
where ISCC.exe 2>nul
echo.

echo [Installer output]
if exist installers dir installers
echo.

echo [Next command]
echo build_installer.bat
echo.
pause
