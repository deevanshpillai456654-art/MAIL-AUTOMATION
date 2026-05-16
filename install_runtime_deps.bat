@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Installing AI Email Organizer Python dependencies...

if exist "AIEmailOrganizer.exe" (
    echo Packaged executable found. Python dependency installation is not required.
    exit /b 0
)

set "SERVICE_DIR=%~dp0service"
if not exist "%SERVICE_DIR%\requirements.txt" set "SERVICE_DIR=%~dp0local-service"
if not exist "%SERVICE_DIR%\requirements.txt" (
    echo ERROR: Could not find service\requirements.txt or local-service\requirements.txt.
    exit /b 1
)

set "PYTHON_CMD="
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 set "PYTHON_CMD=py -3.11"
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo ERROR: Python 3.11+ was not found and no packaged executable is available.
    echo Install: winget install -e --id Python.Python.3.11
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    %PYTHON_CMD% -m venv .venv
    if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
)

".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

if exist "packages\wheels" (
    ".venv\Scripts\python.exe" -m pip install --find-links "packages\wheels" -r "%SERVICE_DIR%\requirements.txt"
) else (
    ".venv\Scripts\python.exe" -m pip install -r "%SERVICE_DIR%\requirements.txt"
)
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo Dependency installation completed.
exit /b 0
