@echo off
setlocal enabledelayedexpansion

echo ================================================
echo   INTEMO - Build System
echo ================================================
echo.

REM Configuration
set "PROJECT_ROOT=%~dp0.."
set "BUILD_DIR=%PROJECT_ROOT%\build\output\windows\x64"
set "INSTALL_DIR=%BUILD_DIR%\AIEmailOrganizer"
set "PYTHON_VERSION=3.10"

echo [1/7] Cleaning previous build...
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
mkdir "%INSTALL_DIR%"
mkdir "%INSTALL_DIR%\data"
mkdir "%INSTALL_DIR%\logs"
mkdir "%INSTALL_DIR%\cache"
mkdir "%INSTALL_DIR%\models"
mkdir "%INSTALL_DIR%\recovery"
mkdir "%INSTALL_DIR%\backups"
mkdir "%INSTALL_DIR%\updates"
mkdir "%INSTALL_DIR%\extensions"
mkdir "%INSTALL_DIR%\extensions\outlook"

echo [2/7] Copying local service...
xcopy /e /q "%PROJECT_ROOT%\local-service" "%INSTALL_DIR%\service\"
if exist "%INSTALL_DIR%\service\main.py" (
    echo     OK: Service files copied
) else (
    echo     ERROR: Service not found
    exit /b 1
)

echo [3/7] Copying dashboard...
xcopy /e /q "%PROJECT_ROOT%\local-service\dashboard" "%INSTALL_DIR%\dashboard\"
if exist "%INSTALL_DIR%\dashboard\index.html" (
    echo     OK: Dashboard copied
) else (
    echo     ERROR: Dashboard not found
)

echo [4/7] Packaging Outlook add-in...
xcopy /e /q "%PROJECT_ROOT%\outlook-addin" "%INSTALL_DIR%\extensions\outlook\"
if exist "%INSTALL_DIR%\extensions\outlook\manifest.xml" (
    echo     OK: Outlook add-in packaged
) else (
    echo     WARNING: Outlook add-in manifest missing
)

echo [5/7] Creating configuration files...
(
echo # INTEMO Configuration
echo API_HOST=127.0.0.1
echo API_PORT=4597
echo AIO_DATA_DIR=
echo AIO_LOG_DIR=
echo AIO_CACHE_DIR=
echo AIO_MODEL_DIR=
echo AIO_DATABASE_DIR=
echo AUTO_START=true
echo MINIMIZE_TO_TRAY=true
echo ENABLE_NOTIFICATIONS=true
echo AUTO_UPDATE=true
) > "%INSTALL_DIR%\config.env"

echo     OK: Config created

echo [6/7] Creating startup script...
(
echo @echo off
echo cd /d "%%~dp0"
echo call "%%~dp0open_dashboard.bat"
) > "%INSTALL_DIR%\start.bat"

(
echo #!/bin/bash
echo cd "%%~dp0"
echo call "%%~dp0start_service.bat"
) > "%INSTALL_DIR%\start.sh"

echo     OK: Startup scripts created

echo [7/7] Validating build...
set "ERRORS=0"
if not exist "%INSTALL_DIR%\service\main.py" (set /a ERRORS+=1 & echo     ERROR: Missing main.py)
if not exist "%INSTALL_DIR%\dashboard\index.html" (set /a ERRORS+=1 & echo     ERROR: Missing dashboard)
if not exist "%INSTALL_DIR%\config.env" (set /a ERRORS+=1 & echo     ERROR: Missing config)
if not exist "%INSTALL_DIR%\start.bat" (set /a ERRORS+=1 & echo     ERROR: Missing start.bat)

if %ERRORS% equ 0 (
    echo.
    echo ================================================
    echo   BUILD SUCCESSFUL
    echo ================================================
    echo.
    echo Output: %INSTALL_DIR%
    echo.
    echo To run:
    echo   1. Double-click start.bat
    echo   2. Or run: start_service.bat
    echo.
    echo Access:
    echo   - API: http://127.0.0.1:4597
    echo   - Dashboard: http://127.0.0.1:4597/dashboard
    echo   - Admin: http://127.0.0.1:4597/admin
    echo.
) else (
    echo.
    echo BUILD FAILED: %ERRORS% errors
    exit /b 1
)

endlocal