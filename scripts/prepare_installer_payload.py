#!/usr/bin/env python3
r"""
Prepare the self-contained Windows installer payload.

This script prepares dist/AIEmailOrganizer for Inno Setup. It does not require
network access unless --download-wheels or --build-exe is used.

Recommended release build on Windows:
    py -3.11 scripts\prepare_installer_payload.py --clean --download-wheels --build-exe
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" scripts\installer.iss

What gets packaged:
- AIEmailOrganizer.exe when PyInstaller succeeds
- service source fallback under service/
- offline dependency wheelhouse under packages/wheels
- dashboard, Gmail extension, Outlook add-in, universal extensions
- desktop/mobile/client foundations and docs/reports needed by customers
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

APP_VERSION = "14.0.1B"
APP_NAME = "INTEMO"

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / "dist" / "AIEmailOrganizer"
BUILD_OUTPUT = ROOT / "build" / "output" / "windows" / "x64" / "AIEmailOrganizer"
WHEELHOUSE = PAYLOAD / "packages" / "wheels"

RUNTIME_DIRS = [
    "data",
    "database",
    "logs",
    "cache",
    "models",
    "backups",
    "runtime",
    "updates",
    "reports/evidence",
    "packages/wheels",
]

# Customer/runtime folders that must be present in the installer payload. These are the
# six-plus user-facing runtime groups plus hardening assets introduced in later passes.
COPY_MAP = [
    ("backend", "service"),
    ("dashboard", "dashboard"),
    ("outlook-addin", "outlook-addin"),
    ("extensions", "extensions"),
    ("browser-extension-packages", "browser-extension-packages"),
    ("desktop", "desktop"),
    ("mobile", "mobile"),
    ("clients", "clients"),
    ("frontend", "frontend"),
    ("docs", "docs"),
    ("reports", "reports"),
    ("monitoring", "monitoring"),
    ("migrations", "migrations"),
    ("updater", "updater"),
    ("shared", "shared"),
]

ROOT_FILES = [
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
    "MASTER_DOCUMENTATION.md",
    "VISUAL_FLOWS.md",
    "config.example.env",
    ".env.production.example",
    "docker-compose.prod.yml",
]

EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    ".git",
}

EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".log", ".db", ".db-wal", ".db-shm"}


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(cwd or ROOT))


def ignore_runtime_junk(dir_name: str, names: list[str]) -> set[str]:
    ignored: set[str] = set()
    for name in names:
        path = Path(dir_name) / name
        if name in EXCLUDE_DIRS:
            ignored.add(name)
        elif path.is_file() and path.suffix.lower() in EXCLUDE_SUFFIXES:
            ignored.add(name)
    return ignored


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"warning: missing source folder: {src}")
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore_runtime_junk)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def ensure_runtime_dirs() -> None:
    for rel in RUNTIME_DIRS:
        directory = PAYLOAD / rel
        directory.mkdir(parents=True, exist_ok=True)
        keep = directory / ".gitkeep"
        if not any(directory.iterdir()):
            keep.write_text("", encoding="utf-8")


def prepare_payload(clean: bool) -> None:
    if clean and PAYLOAD.exists():
        shutil.rmtree(PAYLOAD)
    PAYLOAD.mkdir(parents=True, exist_ok=True)

    for src_rel, dst_rel in COPY_MAP:
        copy_tree(ROOT / src_rel, PAYLOAD / dst_rel)

    for root_file in ROOT_FILES:
        src = ROOT / root_file
        if src.exists():
            shutil.copy2(src, PAYLOAD / root_file)

    ensure_runtime_dirs()
    write_default_config()
    write_runtime_scripts()
    write_version_files()


def write_runtime_scripts() -> None:
    start_service_bat = '@echo off\nsetlocal EnableExtensions\ncd /d "%~dp0"\ntitle INTEMO Background Service\n\nif not exist "logs" mkdir "logs"\n\ncall "%~dp0check_service.bat" >nul 2>nul\nif %ERRORLEVEL% EQU 0 exit /b 0\n\necho [%DATE% %TIME%] Starting INTEMO background service...>>"%~dp0logs\\launcher.log"\n\nset "AIO_BACKGROUND=1"\nset "API_HOST=127.0.0.1"\nif not defined API_PORT set "API_PORT=4597"\n\nif exist "%~dp0AIEmailOrganizer.exe" (\n    "%~dp0AIEmailOrganizer.exe" >>"%~dp0logs\\service.log" 2>>&1\n    exit /b %ERRORLEVEL%\n)\n\nif exist "%~dp0.venv\\Scripts\\python.exe" (\n    cd /d "%~dp0service"\n    "%~dp0.venv\\Scripts\\python.exe" run.py start >>"%~dp0logs\\service.log" 2>>&1\n    exit /b %ERRORLEVEL%\n)\n\nset "PYTHON_CMD="\nwhere py >nul 2>nul\nif %ERRORLEVEL% EQU 0 set "PYTHON_CMD=py -3.11"\nif not defined PYTHON_CMD (\n    where python >nul 2>nul\n    if %ERRORLEVEL% EQU 0 set "PYTHON_CMD=python"\n)\nif defined PYTHON_CMD (\n    cd /d "%~dp0service"\n    %PYTHON_CMD% run.py start >>"%~dp0logs\\service.log" 2>>&1\n    exit /b %ERRORLEVEL%\n)\n\necho [%DATE% %TIME%] ERROR: No packaged executable or Python runtime found.>>"%~dp0logs\\launcher.log"\nexit /b 1\n'
    check_service_bat = '@echo off\nif not defined API_PORT set "API_PORT=4597"\npowershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri \'http://127.0.0.1:%API_PORT%/api/v1/health\' -TimeoutSec 2; if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 500) { exit 0 } } catch { }; exit 1" >nul 2>nul\nexit /b %ERRORLEVEL%\n'
    start_background_vbs = 'Option Explicit\nDim shell, fso, base, cmd\nSet shell = CreateObject("WScript.Shell")\nSet fso = CreateObject("Scripting.FileSystemObject")\nbase = fso.GetParentFolderName(WScript.ScriptFullName)\ncmd = "cmd.exe /c """ & base & "\\start_service.bat"" --background"\nshell.Run cmd, 0, False\n'
    open_url_after_start_bat = '@echo off\nsetlocal EnableExtensions EnableDelayedExpansion\ncd /d "%~dp0"\nset "PAGE=%~1"\nif "%PAGE%"=="" set "PAGE=dashboard"\nif not defined API_PORT set "API_PORT=4597"\n\nset "URL=http://127.0.0.1:%API_PORT%/dashboard"\nif /I "%PAGE%"=="admin" set "URL=http://127.0.0.1:%API_PORT%/admin"\nif /I "%PAGE%"=="setup" set "URL=http://127.0.0.1:%API_PORT%/setup"\nif /I "%PAGE%"=="dashboard" set "URL=http://127.0.0.1:%API_PORT%/dashboard"\nif /I "%PAGE%"=="docs" set "URL=http://127.0.0.1:%API_PORT%/docs"\n\nwscript.exe //B //Nologo "%~dp0start_background.vbs"\n\nfor /L %%I in (1,1,45) do (\n    call "%~dp0check_service.bat" >nul 2>nul\n    if !ERRORLEVEL! EQU 0 goto :open\n    timeout /t 1 /nobreak >nul\n)\n\necho INTEMO is still starting in the background.\necho Opening %URL% now. Refresh the browser in a few seconds if it has not loaded yet.\n\n:open\nstart "" "%URL%"\nexit /b 0\n'
    start_bat = '@echo off\nsetlocal EnableExtensions EnableDelayedExpansion\ncd /d "%~dp0"\ntitle INTEMO Launcher\n\nif /I "%~1"=="--startup" (\n    wscript.exe //B //Nologo "%~dp0start_background.vbs"\n    exit /b 0\n)\n\ncall "%~dp0open_url_after_start.bat" dashboard\nexit /b %ERRORLEVEL%\n'
    run_bat = '@echo off\ncall "%~dp0start.bat" %*\n'
    admin_bat = '@echo off\ncall "%~dp0open_url_after_start.bat" admin\n'
    open_dashboard_bat = '@echo off\ncall "%~dp0open_url_after_start.bat" dashboard\n'
    open_setup_bat = '@echo off\ncall "%~dp0open_url_after_start.bat" setup\n'
    open_docs_bat = '@echo off\ncall "%~dp0open_url_after_start.bat" docs\n'
    stop_bat = '@echo off\nsetlocal EnableExtensions\ncd /d "%~dp0"\necho Stopping INTEMO background service...\ntaskkill /F /IM AIEmailOrganizer.exe >nul 2>nul\nfor /f "tokens=2" %%P in (\'tasklist /v ^| findstr /i "INTEMO Background Service"\') do taskkill /F /PID %%P >nul 2>nul\ntaskkill /F /FI "WINDOWTITLE eq INTEMO*" >nul 2>nul\necho Done.\n'
    install_deps = '@echo off\nsetlocal EnableExtensions\ncd /d "%~dp0"\n\necho Installing INTEMO bundled Python dependencies...\n\nif exist "AIEmailOrganizer.exe" (\n    echo Packaged executable found. Python dependency installation is not required.\n    exit /b 0\n)\n\nif not exist "service\\requirements.txt" (\n    echo ERROR: service\\requirements.txt not found.\n    exit /b 1\n)\n\nif not exist "packages\\wheels" (\n    echo ERROR: packages\\wheels not found. Rebuild installer with --download-wheels.\n    exit /b 1\n)\n\nset "PYTHON_CMD="\nwhere py >nul 2>nul\nif %ERRORLEVEL% EQU 0 set "PYTHON_CMD=py -3.11"\nif not defined PYTHON_CMD (\n    where python >nul 2>nul\n    if %ERRORLEVEL% EQU 0 set "PYTHON_CMD=python"\n)\nif not defined PYTHON_CMD (\n    echo ERROR: Python 3.11+ was not found and no packaged executable is available.\n    exit /b 1\n)\n\nif not exist ".venv\\Scripts\\python.exe" (\n    %PYTHON_CMD% -m venv .venv\n    if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%\n)\n\n".venv\\Scripts\\python.exe" -m pip install --upgrade pip setuptools wheel --no-index --find-links "packages\\wheels"\nif %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%\n\n".venv\\Scripts\\python.exe" -m pip install --no-index --find-links "packages\\wheels" -r "service\\requirements.txt"\nif %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%\n\necho Dependency installation completed without internet.\nexit /b 0\n'
    service_manager_bat = '@echo off\nsetlocal EnableExtensions\ncd /d "%~dp0"\n\necho INTEMO Service Manager\necho.\necho 1. Start in background\necho 2. Open Dashboard\necho 3. Open Admin\necho 4. Open Setup\necho 5. Stop background service\necho.\nset /p CHOICE=Choose option: \nif "%CHOICE%"=="1" wscript.exe //B //Nologo "%~dp0start_background.vbs"\nif "%CHOICE%"=="2" call "%~dp0open_url_after_start.bat" dashboard\nif "%CHOICE%"=="3" call "%~dp0open_url_after_start.bat" admin\nif "%CHOICE%"=="4" call "%~dp0open_url_after_start.bat" setup\nif "%CHOICE%"=="5" call "%~dp0stop.bat"\n'
    readme_run = 'INTEMO v14.0.1B - Windows Runtime\n\nThe local app listens on port 4597. Use these URLs:\n- Dashboard: http://127.0.0.1:4597/dashboard\n- Admin:     http://127.0.0.1:4597/admin\n- Setup:     http://127.0.0.1:4597/setup\n- API docs:  http://127.0.0.1:4597/docs\n\nImportant:\n- http://127.0.0.1/admin without :4597 uses Windows port 80 and will not work unless a separate port-80 proxy is installed.\n- The installer creates Start Menu shortcuts that start the service in the background before opening the page.\n- If you selected "Start with Windows", the app starts silently at login using start_background.vbs.\n\nUseful scripts:\n- start.bat                Start service and open dashboard\n- start_background.vbs     Start service silently in the background\n- open_dashboard.bat       Start service and open dashboard\n- admin.bat                Start service and open admin\n- open_setup.bat           Start service and open setup\n- stop.bat                 Stop service\n- service_manager.bat      Simple launcher menu\n'
    write_text(PAYLOAD / "start_service.bat", start_service_bat)
    write_text(PAYLOAD / "check_service.bat", check_service_bat)
    write_text(PAYLOAD / "start_background.vbs", start_background_vbs)
    write_text(PAYLOAD / "open_url_after_start.bat", open_url_after_start_bat)
    write_text(PAYLOAD / "start.bat", start_bat)
    write_text(PAYLOAD / "run.bat", run_bat)
    write_text(PAYLOAD / "admin.bat", admin_bat)
    write_text(PAYLOAD / "open_dashboard.bat", open_dashboard_bat)
    write_text(PAYLOAD / "open_setup.bat", open_setup_bat)
    write_text(PAYLOAD / "open_docs.bat", open_docs_bat)
    write_text(PAYLOAD / "stop.bat", stop_bat)
    write_text(PAYLOAD / "service_manager.bat", service_manager_bat)
    write_text(PAYLOAD / "install_runtime_deps.bat", install_deps)
    write_text(PAYLOAD / "enable_startup.bat", '@echo off\ncall "%~dp0start.bat" --startup\n')
    write_text(PAYLOAD / "disable_startup.bat", '@echo off\nreg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run" /v "INTEMO" /f >nul 2>nul\n')
    write_text(PAYLOAD / "uninstall.bat", stop_bat)
    write_text(PAYLOAD / "README_RUN_WINDOWS.txt", readme_run)

    # Keep runtime launchers in sync with the customer-tested root scripts.
    # This prevents future installer builds from regenerating an old run.bat
    # that starts silently or hides startup errors.
    for script_name in (
        "run.bat", "start.bat", "start_service.bat", "start_background.vbs",
        "check_service.bat", "open_url_after_start.bat", "admin.bat",
        "open_dashboard.bat", "open_setup.bat", "open_docs.bat",
        "install_runtime_deps.bat", "service_manager.bat", "enable_startup.bat",
        "disable_startup.bat", "stop.bat", "uninstall.bat",
    ):
        src = ROOT / script_name
        if src.exists():
            shutil.copy2(src, PAYLOAD / script_name)

def write_default_config() -> None:
    config_ini = """# INTEMO v14.0.1B - Local Runtime Configuration
[api]
host = 127.0.0.1
port = 4597
workers = 1

[paths]
# Normal Windows installs use %LOCALAPPDATA%\\AIEmailOrganizer via service/config.py.
# Portable paths are only used when AIO_PORTABLE=1.
data_dir = data
database_dir = database
log_dir = logs
cache_dir = cache
model_dir = models

[service]
auto_start = true
minimize_to_tray = true
enable_notifications = true
auto_update = true

[security]
localhost_only = true
cors_enabled = true
rate_limit = 100

[extensions]
gmail_enabled = true
outlook_enabled = true
"""
    env = """# INTEMO v14.0.1B - Local Runtime Environment
API_HOST=127.0.0.1
API_PORT=4597
AIO_DATA_DIR=
AIO_DATABASE_DIR=
AIO_LOG_DIR=
AIO_CACHE_DIR=
AIO_MODEL_DIR=
AUTO_START=true
MINIMIZE_TO_TRAY=true
ENABLE_NOTIFICATIONS=true
AUTO_UPDATE=true
LOG_LEVEL=INFO
"""
    write_text(PAYLOAD / "config.ini", config_ini)
    write_text(PAYLOAD / ".env", env)


def write_version_files() -> None:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    version_info = {
        "name": APP_NAME,
        "version": APP_VERSION,
        "build": timestamp,
        "platform": "windows-x64",
        "installer_payload": True,
        "runtime_modes": ["pyinstaller-exe", "offline-wheelhouse-fallback"],
    }
    write_text(PAYLOAD / "version.json", json.dumps(version_info, indent=2))
    write_text(PAYLOAD / "build-info.json", json.dumps(version_info, indent=2))


def download_wheels() -> None:
    req = ROOT / "backend" / "requirements.txt"
    if not req.exists():
        raise FileNotFoundError(req)
    WHEELHOUSE.mkdir(parents=True, exist_ok=True)
    run([
        sys.executable,
        "-m",
        "pip",
        "download",
        "--dest",
        str(WHEELHOUSE),
        "--requirement",
        str(req),
    ])
    # Include packaging tools for offline fallback installs.
    run([
        sys.executable,
        "-m",
        "pip",
        "download",
        "--dest",
        str(WHEELHOUSE),
        "pip",
        "setuptools",
        "wheel",
    ])


def build_exe() -> None:
    run([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"])
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(ROOT / "scripts" / "pyinstaller.spec")])

    candidate_paths = [
        ROOT / "dist" / "pyinstaller" / "AIEmailOrganizer.exe",
        ROOT / "dist" / "AIEmailOrganizer.exe",
        ROOT / "build" / "pyinstaller" / "AIEmailOrganizer.exe",
    ]
    for candidate in candidate_paths:
        if candidate.exists():
            shutil.copy2(candidate, PAYLOAD / "AIEmailOrganizer.exe")
            print(f"copied packaged executable: {candidate}")
            return
    print("warning: PyInstaller completed but AIEmailOrganizer.exe was not found in known output paths")


def mirror_to_build_output() -> None:
    if BUILD_OUTPUT.exists():
        shutil.rmtree(BUILD_OUTPUT)
    shutil.copytree(PAYLOAD, BUILD_OUTPUT, ignore=ignore_runtime_junk)
    print(f"mirrored payload to {BUILD_OUTPUT}")


def validate_payload() -> None:
    required = [
        PAYLOAD / "service" / "requirements.txt",
        PAYLOAD / "service" / "run.py",
        PAYLOAD / "dashboard" / "index.html",
        PAYLOAD / "outlook-addin" / "manifest.xml",
        PAYLOAD / "extensions" / "chrome" / "manifest.json",
        PAYLOAD / "start.bat",
        PAYLOAD / "start_background.vbs",
        PAYLOAD / "open_url_after_start.bat",
        PAYLOAD / "admin.bat",
        PAYLOAD / "open_setup.bat",
        PAYLOAD / "install_runtime_deps.bat",
        PAYLOAD / "version.json",
    ]
    missing = [str(path.relative_to(PAYLOAD)) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("missing required payload files: " + ", ".join(missing))

    version = json.loads((PAYLOAD / "version.json").read_text(encoding="utf-8"))
    if version.get("version") != APP_VERSION:
        raise RuntimeError(f"payload version mismatch: {version.get('version')} != {APP_VERSION}")
    print("payload validation passed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare INTEMO Windows installer payload")
    parser.add_argument("--clean", action="store_true", help="remove the existing dist/AIEmailOrganizer payload first")
    parser.add_argument("--download-wheels", action="store_true", help="download dependency wheels into packages/wheels")
    parser.add_argument("--build-exe", action="store_true", help="run PyInstaller and copy AIEmailOrganizer.exe into payload")
    parser.add_argument("--mirror-build-output", action="store_true", default=True, help="mirror payload to build/output/windows/x64/AIEmailOrganizer")
    args = parser.parse_args()

    prepare_payload(clean=args.clean)
    if args.download_wheels:
        download_wheels()
    if args.build_exe:
        build_exe()
    validate_payload()
    if args.mirror_build_output:
        mirror_to_build_output()
    print(f"installer payload ready: {PAYLOAD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

