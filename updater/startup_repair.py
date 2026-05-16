import os
import sys
import json
import shutil
import sqlite3
import subprocess
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List


class StartupRepair:
    def __init__(self, app_name="AIEmailOrganizer"):
        self.app_name = app_name
        self.install_path = self._get_install_path()
        self.runtime_home = os.path.join(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or self.install_path, self.app_name)
        self.backup_path = os.path.join(self.runtime_home, "backups")
        self.data_path = os.path.join(self.runtime_home, "data")
        self.config_path = os.path.join(self.runtime_home, "configs")
        self.log_path = os.path.join(self.runtime_home, "logs")
        self.log_file = os.path.join(self.log_path, "startup_repair.log")
        self.repair_mode = "--safe-mode" in sys.argv or "-s" in sys.argv

    def _get_install_path(self):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"Software\\{self.app_name}", 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, "InstallPath")
            winreg.CloseKey(key)
            return value
        except Exception:
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        print(log_entry)
        try:
            os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
            with open(self.log_file, "a") as f:
                f.write(log_entry + "\n")
        except Exception:
            pass

    def repair(self) -> bool:
        self.log("=" * 50)
        self.log("Starting Startup Repair")
        self.log("=" * 50)

        if self.repair_mode:
            self.log("Running in SAFE MODE")

        repairs = [
            ("Configuration Repair", self.repair_configuration),
            ("Database Repair", self.repair_database),
            ("Missing File Recovery", self.repair_missing_files),
            ("Registry Repair", self.repair_registry),
            ("Dependency Repair", self.repair_dependencies),
        ]

        success = True
        results = []

        for name, repair_func in repairs:
            self.log(f"Running: {name}")
            try:
                result = repair_func()
                results.append((name, result))
                if not result["success"]:
                    self.log(f"{name} failed", "ERROR")
                    if not self.repair_mode:
                        success = False
            except Exception as e:
                self.log(f"{name} crashed: {e}", "ERROR")
                results.append((name, {"success": False, "error": str(e)}))
                if not self.repair_mode:
                    success = False

        self.log("=" * 50)
        if success:
            self.log("Repair completed successfully")
        else:
            self.log("Repair completed with failures")
        self.log("=" * 50)

        return success

    def repair_configuration(self) -> Dict:
        self.log("Repairing configuration...")
        result = {"success": True, "issues": []}

        default_config = {
            "app_name": self.app_name,
            "version": "9.7.0",
            "install_path": self.install_path,
            "port": 4597,
            "auto_update": True,
            "update_check_interval": 3600,
            "log_level": "INFO",
            "database": {
                "type": "sqlite",
                "path": os.path.join(self.data_path, "emails.db")
            },
            "security": {
                "encrypt_data": True,
                "require_auth": True
            },
            "ui": {
                "theme": "light",
                "language": "en"
            }
        }

        config_file = os.path.join(self.config_path, "app_config.json")

        if not os.path.exists(config_file):
            os.makedirs(self.config_path, exist_ok=True)
            with open(config_file, "w") as f:
                json.dump(default_config, f, indent=2)
            result["issues"].append("Created missing config file")
        else:
            try:
                with open(config_file, "r") as f:
                    config = json.load(f)

                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                        result["issues"].append(f"Added missing key: {key}")

                with open(config_file, "w") as f:
                    json.dump(config, f, indent=2)

            except json.JSONDecodeError as e:
                result["success"] = False
                result["error"] = f"Invalid JSON: {e}"
                backup = config_file + ".backup"
                shutil.copy2(config_file, backup)
                with open(config_file, "w") as f:
                    json.dump(default_config, f, indent=2)
                result["issues"].append("Restored from backup")

        return result

    def repair_database(self) -> Dict:
        self.log("Repairing database...")
        result = {"success": True, "issues": []}

        db_file = os.path.join(self.data_path, "emails.db")

        if not os.path.exists(db_file):
            os.makedirs(self.data_path, exist_ok=True)
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subject TEXT,
                    sender TEXT,
                    recipient TEXT,
                    date TIMESTAMP,
                    body TEXT,
                    folder TEXT DEFAULT 'inbox',
                    read INTEGER DEFAULT 0,
                    starred INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS labels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    color TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            conn.close()
            result["issues"].append("Created new database")
        else:
            try:
                conn = sqlite3.connect(db_file)
                cursor = conn.cursor()

                cursor.execute("PRAGMA integrity_check")
                integrity = cursor.fetchone()
                if integrity[0] != "ok":
                    result["issues"].append(f"Integrity check failed: {integrity[0]}")
                    cursor.execute("VACUUM")
                    result["issues"].append("Ran VACUUM")

                tables = ["emails", "labels"]
                for table in tables:
                    try:
                        cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    except sqlite3.OperationalError:
                        result["issues"].append(f"Recreating table: {table}")
                        if table == "emails":
                            cursor.execute("""
                                CREATE TABLE IF NOT EXISTS emails (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    subject TEXT, sender TEXT, recipient TEXT,
                                    date TIMESTAMP, body TEXT,
                                    folder TEXT DEFAULT 'inbox',
                                    read INTEGER DEFAULT 0, starred INTEGER DEFAULT 0,
                                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                )
                            """)
                        elif table == "labels":
                            cursor.execute("""
                                CREATE TABLE IF NOT EXISTS labels (
                                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    name TEXT UNIQUE NOT NULL, color TEXT,
                                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                                )
                            """)

                conn.commit()
                conn.close()

            except Exception as e:
                result["success"] = False
                result["error"] = str(e)

        return result

    def repair_missing_files(self) -> Dict:
        self.log("Recovering missing files...")
        result = {"success": True, "issues": []}

        required_files = {
            "main.py": self._create_main_py,
            "requirements.txt": self._create_requirements_txt,
            "backend/__init__.py": self._create_backend_init,
        }

        for file_path, create_func in required_files.items():
            full_path = os.path.join(self.install_path, file_path)
            if not os.path.exists(full_path):
                try:
                    create_func(full_path)
                    result["issues"].append(f"Created missing file: {file_path}")
                except Exception as e:
                    result["success"] = False
                    result["issues"].append(f"Failed to create {file_path}: {e}")

        return result

    def _create_main_py(self, path: str):
        content = '''#!/usr/bin/env python3
import sys
import os

def main():
    print("AI Email Organizer")
    print("Version: 9.7.0")
    print("Starting application...")

    sys.exit(0)

if __name__ == "__main__":
    main()
'''
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    def _create_requirements_txt(self, path: str):
        content = '''flask>=2.0.0
sqlalchemy>=1.4.0
requests>=2.25.0
numpy>=1.20.0
'''
        with open(path, "w") as f:
            f.write(content)

    def _create_backend_init(self, path: str):
        content = '''# AI Email Organizer Backend
'''
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(content)

    def repair_registry(self) -> Dict:
        self.log("Repairing registry...")
        result = {"success": True, "issues": []}

        try:
            import winreg

            key_path = f"Software\\{self.app_name}"
            key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, key_path)

            try:
                value, _ = winreg.QueryValueEx(key, "InstallPath")
                if value != self.install_path:
                    result["issues"].append("Fixed InstallPath")
            except FileNotFoundError:
                pass

            winreg.SetValueEx(key, "InstallPath", 0, winreg.REG_SZ, self.install_path)
            winreg.SetValueEx(key, "Version", 0, winreg.REG_SZ, "9.7.0")
            winreg.CloseKey(key)
            result["issues"].append("Registry entries restored")

        except Exception as e:
            result["success"] = False
            result["error"] = str(e)

        return result

    def repair_dependencies(self) -> Dict:
        self.log("Repairing dependencies...")
        result = {"success": True, "issues": []}

        requirements_file = os.path.join(self.install_path, "requirements.txt")
        if not os.path.exists(requirements_file):
            result["issues"].append("requirements.txt missing")
            return result

        try:
            result_subprocess = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", requirements_file, "--quiet"],
                capture_output=True,
                timeout=300
            )
            if result_subprocess.returncode == 0:
                result["issues"].append("Dependencies installed")
            else:
                result["issues"].append(f"Dependency installation warnings")
        except subprocess.TimeoutExpired:
            result["success"] = False
            result["error"] = "Installation timeout"
        except Exception as e:
            result["issues"].append(f"Check failed: {e}")

        return result

    def safe_mode_startup(self) -> bool:
        self.log("Starting in Safe Mode...")
        os.environ["SAFE_MODE"] = "1"

        config_file = os.path.join(self.config_path, "app_config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    config = json.load(f)
                config["log_level"] = "DEBUG"
                config["auto_update"] = False
                with open(config_file, "w") as f:
                    json.dump(config, f, indent=2)
            except Exception:
                pass

        return True


def main():
    repair = StartupRepair()

    if "--safe-mode" in sys.argv or "-s" in sys.argv:
        repair.safe_mode_startup()

    if repair.repair():
        print("\nRepair completed successfully!")
        sys.exit(0)
    else:
        print("\nRepair completed with issues. Check logs for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()