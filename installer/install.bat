@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0\.."

echo ================================================
echo INTEMO - Manual Windows Installation
echo ================================================
echo.

set "APP_DISPLAY=INTEMO"
set "APP_REG=INTEMO"
set "INSTALL_PATH=%ProgramFiles%\INTEMO"
set "RUNTIME_HOME=%LOCALAPPDATA%\INTEMO"
if not defined LOCALAPPDATA set "RUNTIME_HOME=%APPDATA%\INTEMO"

net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Please run this installer as Administrator.
    pause
    exit /b 1
)

echo Install path: %INSTALL_PATH%
echo Runtime data: %RUNTIME_HOME%
echo.

if not exist "%INSTALL_PATH%" mkdir "%INSTALL_PATH%"
for %%D in (data logs cache models database backups runtime updates) do if not exist "%RUNTIME_HOME%\%%D" mkdir "%RUNTIME_HOME%\%%D" >nul 2>nul

if exist "production_runtime\AIEmailOrganizer\start.bat" (
    echo Copying production runtime payload...
    robocopy "production_runtime\AIEmailOrganizer" "%INSTALL_PATH%" /MIR /XD __pycache__ .pytest_cache .git /XF *.pyc *.pyo >nul
    if !ERRORLEVEL! GEQ 8 exit /b !ERRORLEVEL!
) else if exist "dist\AIEmailOrganizer\start.bat" (
    echo Copying prepared installer payload...
    robocopy "dist\AIEmailOrganizer" "%INSTALL_PATH%" /MIR /XD __pycache__ .pytest_cache .git /XF *.pyc *.pyo >nul
    if !ERRORLEVEL! GEQ 8 exit /b !ERRORLEVEL!
) else (
    echo Copying project files...
    robocopy "%CD%" "%INSTALL_PATH%" /MIR /XD .git .pytest_cache __pycache__ build installers internal_docs /XF *.pyc *.pyo >nul
    if !ERRORLEVEL! GEQ 8 exit /b !ERRORLEVEL!
)

if not exist "%INSTALL_PATH%\start_background.vbs" (
    echo [ERROR] start_background.vbs is missing after copy.
    exit /b 1
)

(
echo API_HOST=127.0.0.1
echo API_PORT=4597
echo AIO_DATA_DIR=%RUNTIME_HOME%\data
echo AIO_LOG_DIR=%RUNTIME_HOME%\logs
echo AIO_CACHE_DIR=%RUNTIME_HOME%\cache
echo AIO_MODEL_DIR=%RUNTIME_HOME%\models
echo AIO_DATABASE_DIR=%RUNTIME_HOME%\database
echo LOG_LEVEL=INFO
) > "%INSTALL_PATH%\.env"

reg add "HKLM\Software\%APP_REG%" /v "InstallPath" /t REG_SZ /d "%INSTALL_PATH%" /f >nul
reg add "HKLM\Software\%APP_REG%" /v "Version" /t REG_SZ /d "14.0.1B" /f >nul
reg add "HKCU\Software\%APP_REG%" /v "InstallPath" /t REG_SZ /d "%INSTALL_PATH%" /f >nul
reg add "HKCU\Software\%APP_REG%" /v "Version" /t REG_SZ /d "14.0.1B" /f >nul

call "%INSTALL_PATH%\enable_startup.bat"
if errorlevel 1 (
    echo [ERROR] Startup registration failed.
    exit /b 1
)

if not exist "%INSTALL_PATH%\INTEMO.exe" (
    call "%INSTALL_PATH%\install_runtime_deps.bat"
    if errorlevel 1 echo WARNING: dependency fallback installation failed. The packaged EXE path is preferred.
)

echo.
echo Installation completed.
echo Accounts and tokens will be stored under:
echo   %RUNTIME_HOME%\data\emails.db
echo.
set /p RUN_NOW="Launch dashboard now? (Y/N): "
if /i "%RUN_NOW%"=="Y" start "" "%INSTALL_PATH%\open_dashboard.bat"
exit /b 0

REM INTEMO v14.0.1B offline setup note: dependencies must be bundled before installer execution.
