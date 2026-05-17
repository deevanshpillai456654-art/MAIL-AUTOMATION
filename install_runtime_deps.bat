@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Installing AI Email Organizer Python dependencies...

if exist "AIEmailOrganizer.exe" (
    echo Packaged executable found. Python dependency installation is not required.
    exit /b 0
)

set "SERVICE_DIR=%~dp0service"
if not exist "%SERVICE_DIR%\run.py" set "SERVICE_DIR=%~dp0local-service"
if not exist "%SERVICE_DIR%\run.py" set "SERVICE_DIR=%~dp0backend"
if not exist "%SERVICE_DIR%\run.py" (
    echo ERROR: Could not find service\run.py, local-service\run.py, or backend\run.py.
    exit /b 1
)

set "REQUIREMENTS_FILE=%SERVICE_DIR%\requirements.txt"
if not exist "%REQUIREMENTS_FILE%" set "REQUIREMENTS_FILE=%~dp0requirements.txt"
if not exist "%REQUIREMENTS_FILE%" (
    echo ERROR: Could not find a Python requirements.txt file.
    exit /b 1
)

set "PYTHON_CMD="
py -3.12 --version >nul 2>nul
if %ERRORLEVEL% EQU 0 set "PYTHON_CMD=py -3.12"
if not defined PYTHON_CMD (
    py -3.11 --version >nul 2>nul
    if %ERRORLEVEL% EQU 0 set "PYTHON_CMD=py -3.11"
)
if not defined PYTHON_CMD (
    py -3.10 --version >nul 2>nul
    if %ERRORLEVEL% EQU 0 set "PYTHON_CMD=py -3.10"
)
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if %ERRORLEVEL% EQU 0 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo ERROR: Python was not found and no packaged executable is available.
    echo Install: winget install -e --id Python.Python.3.12
    exit /b 1
)
echo Using Python runtime: %PYTHON_CMD%

if not exist ".venv\Scripts\python.exe" (
    %PYTHON_CMD% -m venv .venv
    if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
)

".venv\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

if exist "packages\wheels" (
    ".venv\Scripts\python.exe" -m pip install --find-links "packages\wheels" -r "%REQUIREMENTS_FILE%"
) else (
    ".venv\Scripts\python.exe" -m pip install -r "%REQUIREMENTS_FILE%"
)
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

echo Dependency installation completed.
exit /b 0
