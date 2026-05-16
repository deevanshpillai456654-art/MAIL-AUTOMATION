@echo off
setlocal EnableExtensions EnableDelayedExpansion

title INTEMO v14.0.1B - Installer Builder

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

set "APP_VERSION=14.0.1B"
set "BUILD_LOG=%PROJECT_ROOT%\installers\build_installer.log"
set "PYTHON_CMD="
set "ISCC_PATH="
set "SKIP_EXE=0"
set "SKIP_WHEELS=0"

if /I "%~1"=="--skip-exe" set "SKIP_EXE=1"
if /I "%~1"=="--skip-wheels" set "SKIP_WHEELS=1"
if /I "%~2"=="--skip-exe" set "SKIP_EXE=1"
if /I "%~2"=="--skip-wheels" set "SKIP_WHEELS=1"

if not exist "%PROJECT_ROOT%\installers" mkdir "%PROJECT_ROOT%\installers" >nul 2>nul

echo ============================================================
echo INTEMO v%APP_VERSION% - Windows Installer Build
echo ============================================================
echo Project root: %PROJECT_ROOT%
echo Build log:    %BUILD_LOG%
echo Started:      %DATE% %TIME%
echo.
>"%BUILD_LOG%" echo INTEMO installer build log
>>"%BUILD_LOG%" echo Started: %DATE% %TIME%
>>"%BUILD_LOG%" echo Project root: %PROJECT_ROOT%

if not exist "%PROJECT_ROOT%\scripts\prepare_installer_payload.py" goto :bad_project
if not exist "%PROJECT_ROOT%\scripts\installer.iss" goto :bad_project
if not exist "%PROJECT_ROOT%\local-service\requirements.txt" goto :bad_project

call :find_python
if not defined PYTHON_CMD goto :missing_python

call :find_inno
if not defined ISCC_PATH goto :missing_inno

echo Python command: %PYTHON_CMD%
echo Inno compiler: %ISCC_PATH%
echo.
>>"%BUILD_LOG%" echo Python command: %PYTHON_CMD%
>>"%BUILD_LOG%" echo Inno compiler: %ISCC_PATH%

%PYTHON_CMD% --version
if %ERRORLEVEL% NEQ 0 goto :missing_python

if "%SKIP_EXE%"=="1" (
    echo NOTE: --skip-exe enabled. Installer will use source fallback runtime.
)
if "%SKIP_WHEELS%"=="1" (
    echo NOTE: --skip-wheels enabled. Offline dependencies will not be bundled.
)

echo.
echo [1/5] Upgrading build tooling...
echo This can take a few minutes on the first run.
%PYTHON_CMD% -m pip install --upgrade pip setuptools wheel pyinstaller
if %ERRORLEVEL% NEQ 0 goto :fail

echo.
echo [2/5] Preparing installer payload...
set "PREPARE_ARGS=--clean"
if not "%SKIP_WHEELS%"=="1" set "PREPARE_ARGS=!PREPARE_ARGS! --download-wheels"
if not "%SKIP_EXE%"=="1" set "PREPARE_ARGS=!PREPARE_ARGS! --build-exe"

echo Running: %PYTHON_CMD% scripts\prepare_installer_payload.py !PREPARE_ARGS!
%PYTHON_CMD% scripts\prepare_installer_payload.py !PREPARE_ARGS!
if %ERRORLEVEL% NEQ 0 goto :fail

echo.
echo [3/5] Preparing production runtime payload...
if exist "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer" rmdir /s /q "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer" >nul 2>nul
xcopy /E /I /Y "%PROJECT_ROOT%\dist\AIEmailOrganizer" "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer" >nul
if !ERRORLEVEL! NEQ 0 goto :payload_missing

echo Checking installer payload...
if not exist "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer\start.bat" goto :payload_missing
if not exist "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer\start_background.vbs" goto :payload_missing
if not exist "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer\service\requirements.txt" goto :payload_missing
if not exist "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer\dashboard\index.html" goto :payload_missing
if not exist "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer\outlook-addin\manifest.xml" goto :payload_missing
if "%SKIP_WHEELS%"=="0" (
    dir /b "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer\packages\wheels\*.whl" >nul 2>nul
    if !ERRORLEVEL! NEQ 0 goto :wheelhouse_missing
)

echo Payload looks good.

echo.
echo [4/5] Building Inno Setup installer...
echo Running: "%ISCC_PATH%" scripts\installer.iss
"%ISCC_PATH%" scripts\installer.iss
if %ERRORLEVEL% NEQ 0 goto :fail

echo.
echo [5/5] Verifying installer output...
if not exist "%PROJECT_ROOT%\installers\AIEmailOrganizer-Setup-%APP_VERSION%.exe" goto :installer_missing

echo.
echo ============================================================
echo SUCCESS: Installer build completed.
echo Output:
echo   %PROJECT_ROOT%\installers\AIEmailOrganizer-Setup-%APP_VERSION%.exe
echo.
echo The installer includes:
echo - app version %APP_VERSION%
echo - silent background auto-start at Windows login
echo - Dashboard/Admin/Setup/API Docs shortcuts
echo - full app payload under production_runtime\AIEmailOrganizer
echo - bundled offline dependency wheelhouse when --skip-wheels is not used
echo ============================================================
>>"%BUILD_LOG%" echo SUCCESS: %DATE% %TIME%
exit /b 0

:find_python
py -3.11 --version >nul 2>nul && set "PYTHON_CMD=py -3.11" && exit /b 0
py -3.12 --version >nul 2>nul && set "PYTHON_CMD=py -3.12" && exit /b 0
py -3.13 --version >nul 2>nul && set "PYTHON_CMD=py -3.13" && exit /b 0
python --version >nul 2>nul && set "PYTHON_CMD=python" && exit /b 0
exit /b 1

:find_inno
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if defined ISCC_PATH exit /b 0
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC_PATH=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC_PATH exit /b 0
for %%P in (ISCC.exe) do (
    set "FOUND_ISCC=%%~$PATH:P"
)
if defined FOUND_ISCC set "ISCC_PATH=%FOUND_ISCC%"
exit /b 0

:bad_project
echo ERROR: This does not look like the AIEmailOrganizer project root.
echo Missing one of:
echo   scripts\prepare_installer_payload.py
echo   scripts\installer.iss
echo   local-service\requirements.txt
echo.
echo Current folder: %CD%
echo Extract the ZIP fully, then run build_installer.bat from the folder containing scripts\ and local-service\.
goto :fail_no_pause

:missing_python
echo ERROR: Python was not found.
echo.
echo Install Python 3.11 or 3.12, then reopen Command Prompt:
echo   winget install -e --id Python.Python.3.11
echo.
echo Then run:
echo   py -3.11 --version
echo   build_installer.bat
goto :fail_no_pause

:missing_inno
echo WARNING: Inno Setup 6 compiler was not found.
echo.
echo Creating portable ZIP fallback instead of exiting silently.
echo To build a full .exe installer later, install Inno Setup 6:
echo   winget install -e --id JRSoftware.InnoSetup
echo.
>>"%BUILD_LOG%" echo Inno Setup missing; creating portable ZIP fallback.
%PYTHON_CMD% scripts\prepare_installer_payload.py --clean
if %ERRORLEVEL% NEQ 0 goto :fail_no_pause
if exist "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer" rmdir /s /q "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer" >nul 2>nul
xcopy /E /I /Y "%PROJECT_ROOT%\dist\AIEmailOrganizer" "%PROJECT_ROOT%\production_runtime\AIEmailOrganizer" >nul
if %ERRORLEVEL% NEQ 0 goto :payload_missing
set "PORTABLE_ZIP=%PROJECT_ROOT%\installers\AIEmailOrganizer-Portable-%APP_VERSION%.zip"
if exist "%PORTABLE_ZIP%" del /f /q "%PORTABLE_ZIP%" >nul 2>nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%PROJECT_ROOT%\production_runtime\AIEmailOrganizer\*' -DestinationPath '%PORTABLE_ZIP%' -Force"
if %ERRORLEVEL% NEQ 0 goto :fail_no_pause
echo.
echo SUCCESS: Portable ZIP created:
echo   %PORTABLE_ZIP%
>>"%BUILD_LOG%" echo SUCCESS portable ZIP: %PORTABLE_ZIP%
exit /b 0

:payload_missing
echo ERROR: Installer payload is incomplete.
echo Expected files are missing under production_runtime\AIEmailOrganizer.
goto :fail_no_pause

:wheelhouse_missing
echo ERROR: Offline wheelhouse was not created.
echo.
echo This usually means pip could not download dependencies.
echo Check your internet connection, then run again:
echo   build_installer.bat
echo.
echo For quick testing only, you can run:
echo   build_installer.bat --skip-wheels
goto :fail_no_pause

:installer_missing
echo ERROR: Inno Setup finished but installer EXE was not found:
echo   installers\AIEmailOrganizer-Setup-%APP_VERSION%.exe
goto :fail_no_pause

:fail
echo.
echo ERROR: Installer build failed.
echo Check the output above.
echo.
>>"%BUILD_LOG%" echo FAILED: %DATE% %TIME%
exit /b 1

:fail_no_pause
echo.
echo Build log location:
echo   %BUILD_LOG%
echo.
>>"%BUILD_LOG%" echo FAILED: %DATE% %TIME%
exit /b 1
