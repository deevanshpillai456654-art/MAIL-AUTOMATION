@echo off
setlocal
cd /d "%~dp0.."
python "%~dp0sync_packaged_service.py"
if errorlevel 1 (
  echo.
  echo Sync failed. From repo root run:  python scripts\sync_packaged_service.py
  echo Requires Python 3.8+ on PATH. Copies local-service into dist and build service folders.
  exit /b 1
)
endlocal
