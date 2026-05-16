@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title AI Email Organizer Background Service

set "AIO_APP_NAME=AIEmailOrganizer"
set "AIO_LOCALAPPDATA=%LOCALAPPDATA%"
if not defined AIO_LOCALAPPDATA set "AIO_LOCALAPPDATA=%APPDATA%"
if not defined AIO_LOCALAPPDATA set "AIO_LOCALAPPDATA=%~dp0runtime"
set "AIO_RUNTIME_HOME=%AIO_LOCALAPPDATA%\%AIO_APP_NAME%"
set "AIO_DATA_DIR=%AIO_RUNTIME_HOME%\data"
set "AIO_LOG_DIR=%AIO_RUNTIME_HOME%\logs"
set "AIO_CACHE_DIR=%AIO_RUNTIME_HOME%\cache"
set "AIO_MODEL_DIR=%AIO_RUNTIME_HOME%\models"
set "AIO_DATABASE_DIR=%AIO_RUNTIME_HOME%\database"

if not exist "%AIO_RUNTIME_HOME%" mkdir "%AIO_RUNTIME_HOME%" >nul 2>nul
if not exist "%AIO_DATA_DIR%" mkdir "%AIO_DATA_DIR%" >nul 2>nul
if not exist "%AIO_LOG_DIR%" mkdir "%AIO_LOG_DIR%" >nul 2>nul
if not exist "%AIO_CACHE_DIR%" mkdir "%AIO_CACHE_DIR%" >nul 2>nul
if not exist "%AIO_MODEL_DIR%" mkdir "%AIO_MODEL_DIR%" >nul 2>nul
if not exist "%AIO_DATABASE_DIR%" mkdir "%AIO_DATABASE_DIR%" >nul 2>nul

if not defined API_HOST set "API_HOST=127.0.0.1"
if not defined API_PORT set "API_PORT=4597"
set "AIO_BACKGROUND=1"

echo [%DATE% %TIME%] Starting AI Email Organizer service from %~dp0>>"%AIO_LOG_DIR%\launcher.log"
echo [%DATE% %TIME%] Runtime data: %AIO_RUNTIME_HOME%>>"%AIO_LOG_DIR%\launcher.log"

call "%~dp0check_service.bat" >nul 2>nul
if !ERRORLEVEL! EQU 0 (
    echo [%DATE% %TIME%] Service already running.>>"%AIO_LOG_DIR%\launcher.log"
    exit /b 0
)

if exist "%~dp0AIEmailOrganizer.exe" (
    "%~dp0AIEmailOrganizer.exe" >>"%AIO_LOG_DIR%\service.log" 2>>&1
    exit /b !ERRORLEVEL!
)

set "SERVICE_DIR=%~dp0service"
if not exist "%SERVICE_DIR%\run.py" set "SERVICE_DIR=%~dp0local-service"
if not exist "%SERVICE_DIR%\run.py" (
    echo [%DATE% %TIME%] ERROR: Could not find service\run.py or local-service\run.py.>>"%AIO_LOG_DIR%\launcher.log"
    exit /b 1
)

if exist "%~dp0.venv\Scripts\python.exe" (
    cd /d "%SERVICE_DIR%"
    "%~dp0.venv\Scripts\python.exe" run.py start >>"%AIO_LOG_DIR%\service.log" 2>>&1
    exit /b !ERRORLEVEL!
)

set "PYTHON_CMD="
where py >nul 2>nul
if !ERRORLEVEL! EQU 0 set "PYTHON_CMD=py -3"
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if !ERRORLEVEL! EQU 0 set "PYTHON_CMD=python"
)
if defined PYTHON_CMD (
    cd /d "%SERVICE_DIR%"
    !PYTHON_CMD! run.py start >>"%AIO_LOG_DIR%\service.log" 2>>&1
    exit /b !ERRORLEVEL!
)

echo [%DATE% %TIME%] ERROR: No packaged executable or Python runtime found.>>"%AIO_LOG_DIR%\launcher.log"
exit /b 1
