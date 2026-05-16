#!/usr/bin/env python3
"""
INTEMO - Complete Build System
Builds production-ready Windows EXE and installer
"""

import os
import sys
import shutil
import json
import sqlite3
import subprocess
from pathlib import Path
from datetime import datetime


class FullBuildSystem:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.build_dir = self.project_root / "dist" / "AIEmailOrganizer"
        self.pyinstaller_dir = self.project_root / "dist" / "pyinstaller"
        
    def clean(self):
        """Clean previous builds"""
        print("\n[1/15] Cleaning previous builds...")
        for d in [self.build_dir, self.pyinstaller_dir]:
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)
        
        output_dir = self.project_root / "output"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        
        print("    OK: Build directories ready")
        
    def run_python_build(self):
        """Run the Python package build"""
        print("\n[2/15] Running Python package build...")
        build_script = self.project_root / "scripts" / "build.py"
        
        result = subprocess.run(
            [sys.executable, str(build_script)],
            capture_output=True,
            text=True,
            cwd=str(self.project_root)
        )
        
        if result.returncode != 0:
            print(f"    WARNING: Python build returned {result.returncode}")
            print(f"    stdout: {result.stdout[:500]}")
            print(f"    stderr: {result.stderr[:500]}")
        else:
            print("    OK: Python package build complete")
            
    def build_with_pyinstaller(self):
        """Build standalone EXE with PyInstaller"""
        print("\n[3/15] Building standalone EXE with PyInstaller...")
        
        try:
            import PyInstaller
            print(f"    PyInstaller version: {PyInstaller.__version__}")
        except ImportError:
            print("    ERROR: PyInstaller not installed")
            print("    Install with: pip install pyinstaller")
            return False
            
        main_py = self.project_root / "backend" / "main.py"
        
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--console",
            "--name", "AIEmailOrganizer",
            "--distpath", str(self.pyinstaller_dir),
            "--workpath", str(self.project_root / "build" / "pyinstaller"),
            "--specpath", str(self.project_root / "scripts"),
            "--add-data", f"{self.project_root / 'backend' / 'dashboard'};dashboard",
            "--hidden-import", "uvicorn",
            "--hidden-import", "fastapi",
            "--hidden-import", "starlette",
            "--hidden-import", "pydantic",
            "--hidden-import", "jinja2",
            "--collect-all", "starlette",
            "--collect-all", "fastapi",
            "--exclude-module", "matplotlib",
            "--exclude-module", "scipy",
            "--exclude-module", "pandas",
            "--exclude-module", "pytest",
            str(main_py)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.project_root))
        
        if result.returncode == 0:
            exe_path = self.pyinstaller_dir / "AIEmailOrganizer.exe"
            if exe_path.exists():
                size_mb = exe_path.stat().st_size / 1024 / 1024
                print(f"    OK: EXE built ({size_mb:.2f} MB)")
                return True
            else:
                print(f"    ERROR: EXE not found at {exe_path}")
        else:
            print(f"    ERROR: PyInstaller failed")
            print(f"    stdout: {result.stdout[-1000:]}")
            print(f"    stderr: {result.stderr[-1000:]}")
            
        return False
        
    def copy_exe_to_package(self):
        """Copy EXE to the build output"""
        print("\n[4/15] Copying EXE to package...")
        
        src_exe = self.pyinstaller_dir / "AIEmailOrganizer.exe"
        
        if src_exe.exists():
            dst_exe = self.build_dir / "AIEmailOrganizer.exe"
            shutil.copy2(src_exe, dst_exe)
            print(f"    OK: EXE copied to {dst_exe}")
        else:
            print(f"    WARNING: Source EXE not found")
            
    def copy_service_files(self):
        """Copy service Python files"""
        print("\n[5/15] Copying service files...")
        
        src = self.project_root / "backend"
        dst = self.build_dir / "service"
        
        for item in src.rglob("*"):
            if item.is_file() and item.suffix == ".py":
                rel = item.relative_to(src)
                dest_file = dst / rel
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest_file)
                
        if (src / "requirements.txt").exists():
            shutil.copy2(src / "requirements.txt", dst / "requirements.txt")
        if (src / "config.py").exists():
            shutil.copy2(src / "config.py", dst / "config.py")
            
        # Fix config paths for built package
        config_file = dst / "config.py"
        if config_file.exists():
            config_content = config_file.read_text(encoding='utf-8')
            # Replace local-service references with proper paths
            config_content = config_content.replace('"backend", "data"', '"database"')
            config_content = config_content.replace('"backend", "logs"', '"logs"')
            config_content = config_content.replace('"backend", "models"', '"models"')
            config_file.write_text(config_content, encoding='utf-8')
            
        # Fix dashboard path in main.py
        main_file = dst / "main.py"
        if main_file.exists():
            main_content = main_file.read_text(encoding='utf-8')
            # Fix dashboard path - go up two levels from service/ to root
            main_content = main_content.replace(
                'dashboard_path = Path(__file__).parent / "dashboard"',
                'dashboard_path = Path(__file__).parent.parent / "dashboard"'
            )
            main_file.write_text(main_content, encoding='utf-8')
            
        print(f"    OK: Service files copied (paths fixed)")
        
    def copy_dashboard(self):
        """Copy dashboard files"""
        print("\n[6/15] Copying dashboard...")
        
        src = self.project_root / "dashboard"
        dst = self.build_dir / "dashboard"
        
        if src.exists():
            for item in src.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(src)
                    dest_file = dst / rel
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_file)
            print(f"    OK: Dashboard copied")
        else:
            print(f"    WARNING: Dashboard not found")
            
    def copy_extensions(self):
        """Copy browser extensions"""
        print("\n[7/15] Packaging extensions...")
        
        gmail_src = self.project_root / "gmail-extension"
        gmail_dst = self.build_dir / "extensions" / "gmail"
        
        if gmail_src.exists():
            for item in gmail_src.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(gmail_src)
                    dest_file = gmail_dst / rel
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_file)
            print(f"    OK: Gmail extension packaged")
        
        outlook_src = self.project_root / "outlook-addin"
        outlook_dst = self.build_dir / "extensions" / "outlook"
        
        if outlook_src.exists():
            for item in outlook_src.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(outlook_src)
                    dest_file = outlook_dst / rel
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_file)
            print(f"    OK: Outlook add-in packaged")
            
    def copy_runtime_dirs(self):
        """Copy/create runtime directories"""
        print("\n[8/15] Setting up runtime directories...")
        
        dirs = ["database", "logs", "cache", "models", "embeddings", "recovery", "backups", "updates", "runtime", "configs", "installers", "temp", "docs", "shared"]
        
        for d in dirs:
            (self.build_dir / d).mkdir(parents=True, exist_ok=True)
            
        print(f"    OK: {len(dirs)} directories created")
        
    def create_config_files(self):
        """Create configuration files"""
        print("\n[9/15] Creating configuration files...")
        
        config_content = """# INTEMO - Production Configuration
# Generated: {timestamp}

[api]
host = 127.0.0.1
port = 4597
workers = 1

[database]
path = database/emails.db
wal_mode = true
timeout = 30

[logging]
level = INFO
path = logs
max_size = 10MB
backup_count = 5

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

[paths]
# Normal Windows installs use %LOCALAPPDATA%\\AIEmailOrganizer via service/config.py.
# Portable paths are only used when AIO_PORTABLE=1.
data_dir = data
database_dir = database
log_dir = logs
cache_dir = cache
model_dir = models
""".format(timestamp=self.timestamp)
        
        (self.build_dir / "config.ini").write_text(config_content)
        
        env_content = """API_HOST=127.0.0.1
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
        
        (self.build_dir / ".env").write_text(env_content)
        
        (self.build_dir / "config.example.env").write_text(env_content)
        
        version_info = {
            "name": "INTEMO",
            "version": "14.0.1B",
            "build": self.timestamp,
            "platform": "windows-x64",
            "python_version": sys.version.split()[0]
        }
        
        (self.build_dir / "version.json").write_text(json.dumps(version_info, indent=2))
        
        print("    OK: Configuration files created")
        
    def create_startup_scripts(self):
        """Create startup and management scripts"""
        print("\n[10/15] Creating startup scripts...")
        
        bat_content = """@echo off
cd /d "%~dp0"
call "%~dp0open_dashboard.bat"
"""
        (self.build_dir / "start.bat").write_text(bat_content)
        
        run_content = """@echo off
cd /d "%~dp0"
call "%~dp0start_service.bat"
"""
        (self.build_dir / "run.bat").write_text(run_content)
        
        run_service_content = """@echo off
cd /d "%~dp0"
call "%~dp0start_service.bat"
"""
        (self.build_dir / "run-service.bat").write_text(run_service_content)
            
        admin_content = """@echo off
cd /d "%~dp0"
call "%~dp0admin.bat"
"""
        (self.build_dir / "admin.bat").write_text(admin_content)
        
        uninstall_content = """@echo off
cd /d "%~dp0"
call "%~dp0disable_startup.bat"
call "%~dp0stop.bat"
echo INTEMO service stopped and startup disabled.
pause
"""
        (self.build_dir / "uninstall.bat").write_text(uninstall_content)
        
        print("    OK: Startup scripts created")
        
    def init_database(self):
        """Create runtime database directory without shipping seeded data."""
        print("\n[11/15] Preparing runtime database directory...")
        database_dir = self.build_dir / "database"
        database_dir.mkdir(parents=True, exist_ok=True)
        (database_dir / ".gitkeep").write_text("", encoding="utf-8")
        (database_dir / "README_RUNTIME_DATA.txt").write_text(
            "Runtime databases are generated in the user's durable runtime directory at first launch.\n",
            encoding="utf-8",
        )
        print("    OK: Runtime database directory prepared without bundled emails.db")
        
    def create_documentation(self):
        """Create documentation files"""
        print("\n[12/15] Creating documentation...")
        
        readme = """# INTEMO - Installation Guide

## Quick Start

1. Double-click `start.bat` to launch the service
2. Open browser to http://127.0.0.1:4597
3. Access Dashboard: http://127.0.0.1:4597/dashboard

## Requirements

- Windows 10 or Windows 11
- Python 3.8+ (or use bundled EXE)

## Features

- Local AI email classification
- Gmail browser extension
- Outlook add-in
- Admin dashboard
- Auto-categorization
- Smart views
- Rules engine
- System tray integration
- Auto-start with Windows

## Directory Structure

```
AIEmailOrganizer/
â”œ── AIEmailOrganizer.exe    # Main executable
â”œ── service/                # Python service files
â”œ── dashboard/              # Admin dashboard
â”œ── extensions/            # Browser extensions
│   â”œ── gmail/             # Gmail extension
│   â””── outlook/           # Outlook add-in
â”œ── database/              # SQLite database
â”œ── logs/                  # Log files
â”œ── cache/                 # Cache directory
â”œ── models/                # AI models
â””── configs/               # Configuration files
```

## Browser Extension Setup

### Chrome/Edge
1. Open chrome://extensions
2. Enable "Developer mode"
3. Click "Load unpacked"
4. Select `extensions/gmail` folder

### Firefox
1. Open about:debugging
2. Click "Load Temporary Add-on"
3. Select any file in `extensions/gmail` folder

## Outlook Add-in Setup

1. Open Outlook
2. Go to File > Manage Add-ins
3. Click "Add a custom add-in"
4. Select `extensions/outlook/manifest.xml`

## Configuration

Edit `config.ini` or `.env` to customize:
- API port (default: 4597)
- Database location
- Auto-start behavior

## System Tray

The application minimizes to system tray:
- Left-click: Open dashboard
- Right-click: Menu options (Open, Settings, Exit)

## Auto-Start

To enable auto-start with Windows:
- Edit config.ini: auto_start = true
- Or use Windows Task Scheduler

## Support

For issues, check logs in the `logs` folder.
"""
        
        (self.build_dir / "README.md").write_text(readme, encoding='utf-8')
        
        changelog = """# Changelog

## version 14.0.1B (Current Release)

### Features
- Local AI email classification service
- Gmail browser extension (Manifest V3)
- Outlook add-in with Office.js
- Admin dashboard with dark mode
- SQLite database with WAL mode
- System tray integration
- Dynamic port management
- Security: localhost-only binding (127.0.0.1)
- CORS protection for extensions

### Components
- FastAPI-based REST API
- Uvicorn ASGI server
- Local-first architecture
- No cloud dependencies
"""
        
        (self.build_dir / "CHANGELOG.md").write_text(changelog, encoding='utf-8')
        
        print("    OK: Documentation created")
        
    def create_license(self):
        """Create license file"""
        print("\n[13/15] Creating license file...")
        
        license_content = """MIT License

Copyright (c) 2024 INTEMO

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
        
        (self.build_dir / "LICENSE").write_text(license_content, encoding='utf-8')
        print("    OK: License file created")
        
    def validate_build(self):
        """Validate the build output"""
        print("\n[14/15] Validating build...")
        
        required = [
            ("Main EXE", self.build_dir / "AIEmailOrganizer.exe"),
            ("Dashboard index", self.build_dir / "dashboard" / "index.html"),
            ("Config file", self.build_dir / "config.ini"),
            ("Runtime database dir", self.build_dir / "database"),
            ("Start script", self.build_dir / "start.bat"),
            ("Gmail manifest", self.build_dir / "extensions" / "gmail" / "manifest.json"),
            ("Outlook manifest", self.build_dir / "extensions" / "outlook" / "manifest.xml"),
            ("README", self.build_dir / "README.md"),
        ]
        
        errors = 0
        for name, path in required:
            if path.exists():
                print(f"    OK: {name}")
            else:
                print(f"    MISSING: {name} ({path})")
                errors += 1
                
        if errors == 0:
            print("\n    All validation checks passed!")
            return True
        else:
            print(f"\n    WARNING: {errors} validation checks failed")
            return False
            
    def print_summary(self):
        """Print build summary"""
        print("\n[15/15] Build Summary")
        print("=" * 60)
        
        total_size = 0
        file_count = 0
        
        for f in self.build_dir.rglob("*"):
            if f.is_file():
                total_size += f.stat().st_size
                file_count += 1
                
        size_mb = total_size / 1024 / 1024
        
        print(f"Output directory: {self.build_dir}")
        print(f"Build timestamp:  {self.timestamp}")
        print(f"Total files:      {file_count}")
        print(f"Total size:       {size_mb:.2f} MB")
        
        print("\nTo run:")
        print("  1. Double-click start.bat")
        print("  2. Or run: AIEmailOrganizer.exe")
        
        print("\nAccess:")
        print("  - API:       http://127.0.0.1:4597")
        print("  - Dashboard: http://127.0.0.1:4597/dashboard")
        print("  - Admin:     http://127.0.0.1:4597/admin")
        
        print("=" * 60)
        
    def build(self):
        """Execute full build process"""
        print("=" * 60)
        print("  INTEMO - COMPLETE BUILD SYSTEM")
        print("=" * 60)
        
        self.clean()
        self.run_python_build()
        self.build_with_pyinstaller()
        self.copy_exe_to_package()
        self.copy_service_files()
        self.copy_dashboard()
        self.copy_extensions()
        self.copy_runtime_dirs()
        self.create_config_files()
        self.create_startup_scripts()
        self.init_database()
        self.create_documentation()
        self.create_license()
        self.validate_build()
        self.print_summary()
        
        print("\nBUILD COMPLETE!")
        return True


if __name__ == "__main__":
    project_root = Path(__file__).parent.parent
    builder = FullBuildSystem(str(project_root))
    builder.build()

