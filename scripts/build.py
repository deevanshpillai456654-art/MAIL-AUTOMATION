#!/usr/bin/env python3
"""
INTEMO - Build System
Creates production-ready installation package
"""

import os
import sys
import shutil
import json
import sqlite3
from pathlib import Path
from datetime import datetime


class BuildSystem:
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.build_dir = self.project_root / "build" / "output" / "windows" / "x64" / "AIEmailOrganizer"
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
    def clean(self):
        """Clean previous build"""
        print("\n[1/12] Cleaning previous build...")
        if self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        self.build_dir.mkdir(parents=True, exist_ok=True)
        print("    OK: Build directory ready")
        
    def create_structure(self):
        """Create directory structure"""
        print("\n[2/12] Creating directory structure...")
        dirs = [
            "service", "dashboard", "extensions/gmail", "extensions/outlook",
            "data", "logs", "cache", "models", "recovery", "backups", "updates"
        ]
        for d in dirs:
            (self.build_dir / d).mkdir(parents=True, exist_ok=True)
        print(f"    OK: {len(dirs)} directories created")
        
    def copy_service(self):
        """Copy Python service files"""
        print("\n[3/12] Copying local service...")
        src = self.project_root / "backend"
        dst = self.build_dir / "service"
        
        # Copy all Python files
        for item in src.rglob("*"):
            if item.is_file() and item.suffix == ".py":
                rel = item.relative_to(src)
                dest_file = dst / rel
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest_file)
        
        # Copy requirements
        if (src / "requirements.txt").exists():
            shutil.copy2(src / "requirements.txt", dst / "requirements.txt")
            
        # Copy config
        if (src / "config.py").exists():
            shutil.copy2(src / "config.py", dst / "config.py")
            
        # Copy run.py
        if (src / "run.py").exists():
            shutil.copy2(src / "run.py", dst / "run.py")
            
        print("    OK: Service files copied")
        
    def copy_dashboard(self):
        """Copy dashboard files"""
        print("\n[4/12] Copying dashboard...")
        src = self.project_root / "backend" / "dashboard"
        dst = self.build_dir / "dashboard"
        
        if src.exists():
            for item in src.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(src)
                    dest_file = dst / rel
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_file)
            print(f"    OK: Dashboard copied ({len(list(dst.rglob('*')))} files)")
        else:
            print("    WARNING: Dashboard not found")
            
    def copy_extensions(self):
        """Copy browser extensions"""
        print("\n[5/12] Packaging extensions...")

        # Outlook add-in
        outlook_src = self.project_root / "outlook-addin"
        outlook_dst = self.build_dir / "extensions" / "outlook"
        if outlook_src.exists():
            for item in outlook_src.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(outlook_src)
                    dest_file = outlook_dst / rel
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_file)
            print("    OK: Outlook add-in packaged")
        else:
            print("    WARNING: Outlook add-in not found")
            
    def create_config(self):
        """Create configuration files"""
        print("\n[6/12] Creating configuration files...")
        
        # Main config
        config = """# INTEMO - Production Configuration
# Generated: {timestamp}

[api]
host = 127.0.0.1
port = 4597
workers = 1

[database]
# Default Windows runtime data is %LOCALAPPDATA%/AIEmailOrganizer/data folder (emails.db).
# This portable fallback is only used when AIO_PORTABLE=1.
path = %LOCALAPPDATA%/AIEmailOrganizer/data folder (emails.db)
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
""".format(timestamp=self.timestamp)
        
        (self.build_dir / "config.ini").write_text(config)
        
        # Environment file
        env_config = """# INTEMO - Environment Variables
API_HOST=127.0.0.1
API_PORT=4597
# Leave DATA_DIR/LOG_DIR/MODEL_DIR unset for normal Windows installs.
# The app resolves durable paths under %LOCALAPPDATA%\\AIEmailOrganizer.
AIO_DATA_DIR=
AIO_LOG_DIR=
AIO_CACHE_DIR=
AIO_MODEL_DIR=
AIO_DATABASE_DIR=
AUTO_START=true
MINIMIZE_TO_TRAY=true
ENABLE_NOTIFICATIONS=true
AUTO_UPDATE=true
"""
        (self.build_dir / ".env").write_text(env_config)
        
        # Version file
        version_info = {
            "name": "INTEMO",
            "version": "14.0.1B",
            "build": self.timestamp,
            "platform": "windows-x64"
        }
        (self.build_dir / "version.json").write_text(json.dumps(version_info, indent=2))
        
        print("    OK: Configuration files created")
        
    def create_startup_scripts(self):
        """Create startup scripts"""
        print("\n[7/12] Creating startup scripts...")
        
        # Windows launchers delegate to the maintained root scripts. This prevents
        # future builds from reintroducing install-folder data paths or main.py-only startup.
        bat_script = """@echo off
cd /d "%~dp0"
call "%~dp0open_dashboard.bat"
"""
        (self.build_dir / "start.bat").write_text(bat_script)
        
        service_script = """@echo off
cd /d "%~dp0"
call "%~dp0start_service.bat"
"""
        (self.build_dir / "run.bat").write_text(service_script)
        
        quick_script = """@echo off
cd /d "%~dp0"
call "%~dp0start_service.bat"
"""
        (self.build_dir / "quick-start.bat").write_text(quick_script)
        
        uninstall_script = """@echo off
cd /d "%~dp0"
call "%~dp0disable_startup.bat"
call "%~dp0stop.bat"
echo INTEMO service stopped and startup disabled.
pause
"""
        (self.build_dir / "uninstall.bat").write_text(uninstall_script)
        
        print("    OK: Startup scripts created")
        
    def init_database(self):
        """Create runtime data directory without shipping a seeded SQLite database.

        Runtime databases are generated under the durable user runtime home at
        first launch. This prevents install-folder or package cleanup from
        deleting connected accounts after restart.
        """
        print("\n[8/12] Preparing runtime data directory...")
        data_dir = self.build_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / ".gitkeep").write_text("", encoding="utf-8")
        (data_dir / "README_RUNTIME_DATA.txt").write_text(
            "Runtime databases are generated in the user's durable runtime directory at first launch.\n",
            encoding="utf-8",
        )
        print("    OK: Runtime data directory prepared without bundled emails.db")
        
    def create_docs(self):
        """Create documentation"""
        print("\n[9/12] Creating documentation...")
        
        readme = """# INTEMO - Installation Guide

## Quick Start

1. Double-click `start.bat` to launch the service
2. Open browser to http://127.0.0.1:4597
3. Access Dashboard: http://127.0.0.1:4597/dashboard

## Requirements

- Windows 10 or Windows 11
- Python 3.8+ (included in package)

## Features

- Local AI email classification
- Gmail browser extension
- Outlook add-in
- Admin dashboard
- Auto-categorization
- Smart views
- Rules engine

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

Edit `config.ini` to customize:
- API port
- Database location
- Auto-start behavior

## Support

For issues, check logs in the `logs` folder.
"""
        
        (self.build_dir / "README.md").write_text(readme)
        print("    OK: Documentation created")
        
    def validate(self):
        """Validate build"""
        print("\n[10/12] Validating build...")
        
        checks = [
            ("Service main.py", self.build_dir / "service" / "main.py"),
            ("Dashboard index.html", self.build_dir / "dashboard" / "index.html"),
            ("Config file", self.build_dir / "config.ini"),
            ("Runtime data dir", self.build_dir / "data"),
            ("Start script", self.build_dir / "start.bat"),
            ("Gmail manifest", self.build_dir / "extensions" / "gmail" / "manifest.json"),
            ("Outlook manifest", self.build_dir / "extensions" / "outlook" / "manifest.xml"),
        ]
        
        errors = 0
        for name, path in checks:
            if path.exists():
                print(f"    OK: {name}")
            else:
                print(f"    ERROR: {name} not found")
                errors += 1
                
        return errors == 0
        
    def create_info(self):
        """Create build info"""
        print("\n[11/12] Creating build metadata...")
        
        # File count
        file_count = len(list(self.build_dir.rglob("*")) if self.build_dir.exists() else [])
        
        info = {
            "build_time": self.timestamp,
            "files_count": file_count,
            "components": {
                "service": "backend",
                "dashboard": "dashboard",
                "outlook_addin": "outlook-addin"
            },
            "paths": {
                "data": "data",
                "logs": "logs",
                "cache": "cache",
                "models": "models"
            }
        }
        
        (self.build_dir / "build-info.json").write_text(json.dumps(info, indent=2))
        print("    OK: Build metadata created")
        
    def summary(self):
        """Print build summary"""
        print("\n[12/12] Build Summary")
        print("=" * 50)
        print(f"Output directory: {self.build_dir}")
        print(f"Build timestamp: {self.timestamp}")
        
        size = sum(f.stat().st_size for f in self.build_dir.rglob("*") if f.is_file()) / 1024 / 1024
        print(f"Total size: {size:.2f} MB")
        
        print("\nTo run:")
        print("  1. Double-click start.bat")
        print("  2. Or run: python service/main.py")
        print("\nAccess:")
        _port = os.environ.get("API_PORT", "4597")
        print(f"  - API: http://127.0.0.1:{_port}")
        print(f"  - Dashboard: http://127.0.0.1:{_port}/dashboard")
        print(f"  - Admin: http://127.0.0.1:{_port}/admin")
        print("=" * 50)
        
    def build(self):
        """Execute full build"""
        print("=" * 60)
        print("   INTEMO - BUILD SYSTEM")
        print("=" * 60)
        
        self.clean()
        self.create_structure()
        self.copy_service()
        self.copy_dashboard()
        self.copy_extensions()
        self.create_config()
        self.create_startup_scripts()
        self.init_database()
        self.create_docs()
        self.validate()
        self.create_info()
        self.summary()
        
        print("\nBUILD COMPLETE!")


if __name__ == "__main__":
    project_root = Path(__file__).parent.parent
    builder = BuildSystem(str(project_root))
    builder.build()

