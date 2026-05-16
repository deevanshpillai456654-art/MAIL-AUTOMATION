import os
import sys
import json
import sqlite3
import socket
import subprocess
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

APP_VERSION = "9.7.0"


class HealthValidator:
    def __init__(self, app_name="AIEmailOrganizer"):
        self.app_name = app_name
        self.install_path = self._get_install_path()
        self.runtime_home = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or self.install_path,
            self.app_name,
        )
        self.config_path = os.path.join(self.runtime_home, "configs")
        self.db_path = os.path.join(self.runtime_home, "data")
        self.log_path = os.path.join(self.runtime_home, "logs")
        self.health_report_path = os.path.join(self.runtime_home, "health_report.json")
        self.log_file = os.path.join(self.log_path, "health_validator.log")

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

    def run_all_checks(self) -> Dict:
        self.log("Starting comprehensive health check...")
        report = {
            "timestamp": datetime.now().isoformat(),
            "version": APP_VERSION,
            "install_path": self.install_path,
            "runtime_home": self.runtime_home,
            "checks": {},
            "summary": {
                "passed": 0,
                "failed": 0,
                "warnings": 0
            }
        }

        checks = [
            ("pre_update", self.check_pre_update_health),
            ("database", self.check_database_integrity),
            ("configuration", self.check_configuration),
            ("dependencies", self.check_dependencies),
            ("ports", self.check_port_availability),
            ("startup", self.check_startup),
            ("files", self.check_required_files),
            ("permissions", self.check_permissions),
        ]

        for name, check_func in checks:
            try:
                result = check_func()
                report["checks"][name] = result
                if result["status"] == "pass":
                    report["summary"]["passed"] += 1
                elif result["status"] == "fail":
                    report["summary"]["failed"] += 1
                else:
                    report["summary"]["warnings"] += 1
            except Exception as e:
                self.log(f"Check {name} crashed: {e}", "ERROR")
                report["checks"][name] = {"status": "error", "message": str(e)}
                report["summary"]["failed"] += 1

        with open(self.health_report_path, "w") as f:
            json.dump(report, f, indent=2)

        self.log(f"Health check complete: {report['summary']['passed']} passed, {report['summary']['failed']} failed, {report['summary']['warnings']} warnings")
        return report

    def check_pre_update_health(self) -> Dict:
        self.log("Running pre-update health check...")
        result = {"status": "pass", "checks": {}}

        free_space = self._check_disk_space()
        result["checks"]["disk_space"] = free_space

        memory = self._check_memory()
        result["checks"]["memory"] = memory

        if free_space["status"] == "fail" or memory["status"] == "fail":
            result["status"] = "fail"
        elif free_space["status"] == "warning" or memory["status"] == "warning":
            result["status"] = "warning"

        return result

    def _check_disk_space(self) -> Dict:
        try:
            import shutil
            usage = shutil.disk_usage(self.install_path)
            free_gb = usage.free / (1024**3)
            if free_gb < 1:
                return {"status": "fail", "free_gb": round(free_gb, 2), "message": "Less than 1GB free"}
            elif free_gb < 5:
                return {"status": "warning", "free_gb": round(free_gb, 2), "message": "Less than 5GB free"}
            return {"status": "pass", "free_gb": round(free_gb, 2), "message": "Sufficient space"}
        except Exception as e:
            return {"status": "warning", "message": str(e)}

    def _check_memory(self) -> Dict:
        try:
            import psutil
            mem = psutil.virtual_memory()
            if mem.percent > 95:
                return {"status": "fail", "percent": mem.percent, "message": "Critical memory usage"}
            elif mem.percent > 85:
                return {"status": "warning", "percent": mem.percent, "message": "High memory usage"}
            return {"status": "pass", "percent": mem.percent, "message": "Memory OK"}
        except ImportError:
            return {"status": "pass", "message": "psutil not available, skipping"}
        except Exception as e:
            return {"status": "warning", "message": str(e)}

    def check_database_integrity(self) -> Dict:
        self.log("Checking database integrity...")
        result = {"status": "pass", "checks": {}}

        db_file = os.path.join(self.db_path, "emails.db")
        if not os.path.exists(db_file):
            return {"status": "warning", "checks": {}, "message": "Database file not found"}

        try:
            conn = sqlite3.connect(db_file)
            cursor = conn.cursor()

            cursor.execute("PRAGMA integrity_check")
            integrity = cursor.fetchone()
            result["checks"]["integrity"] = {"status": "pass" if integrity[0] == "ok" else "fail", "result": integrity[0]}

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            result["checks"]["tables"] = {"status": "pass", "count": len(tables), "tables": [t[0] for t in tables]}

            for table in tables:
                table_name = table[0]
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    count = cursor.fetchone()[0]
                    result["checks"][f"table_{table_name}"] = {"status": "pass", "rows": count}
                except Exception as e:
                    result["checks"][f"table_{table_name}"] = {"status": "warning", "error": str(e)}

            conn.close()

        except Exception as e:
            result["status"] = "fail"
            result["error"] = str(e)

        return result

    def check_configuration(self) -> Dict:
        self.log("Checking configuration...")
        result = {"status": "pass", "checks": {}}

        config_files = ["app_config.json", "database_config.json", "security_config.json"]

        for config_file in config_files:
            config_path = os.path.join(self.config_path, config_file)
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r") as f:
                        config = json.load(f)
                    result["checks"][config_file] = {"status": "pass", "valid": True}
                except json.JSONDecodeError as e:
                    result["checks"][config_file] = {"status": "fail", "error": str(e)}
                    result["status"] = "fail"
                except Exception as e:
                    result["checks"][config_file] = {"status": "warning", "error": str(e)}
            else:
                result["checks"][config_file] = {"status": "warning", "message": "Not found"}

        main_config = os.path.join(self.config_path, "app_config.json")
        if os.path.exists(main_config):
            try:
                with open(main_config, "r") as f:
                    config = json.load(f)

                required_fields = ["app_name", "version", "port"]
                for field in required_fields:
                    if field not in config:
                        result["checks"]["required_fields"] = {"status": "warning", "missing": field}
                        result["status"] = "warning"
            except Exception as e:
                result["status"] = "fail"
                result["error"] = str(e)

        return result

    def check_dependencies(self) -> Dict:
        self.log("Checking dependencies...")
        result = {"status": "pass", "checks": {}}

        required_packages = ["flask", "sqlalchemy", "requests", "numpy"]
        missing = []
        outdated = []

        requirements_file = os.path.join(self.install_path, "requirements.txt")
        if os.path.exists(requirements_file):
            try:
                with open(requirements_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            pkg = line.split("==")[0].split(">=")[0].split("<=")[0]
                            try:
                                __import__(pkg)
                                result["checks"][pkg] = {"status": "pass", "installed": True}
                            except ImportError:
                                result["checks"][pkg] = {"status": "fail", "installed": False}
                                missing.append(pkg)
            except Exception as e:
                result["checks"]["requirements"] = {"status": "warning", "error": str(e)}

        if missing:
            result["status"] = "fail"
            result["missing_packages"] = missing

        return result

    def check_port_availability(self) -> Dict:
        self.log("Checking port availability...")
        result = {"status": "pass", "checks": {}}

        config_file = os.path.join(self.config_path, "app_config.json")
        port = 5000

        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    config = json.load(f)
                    port = config.get("port", 5000)
            except Exception:
                pass

        result["checks"]["port"] = {"port": port}

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            is_used = sock.connect_ex(("localhost", port)) == 0
            sock.close()

            if is_used:
                result["checks"]["port"]["status"] = "warning"
                result["checks"]["port"]["message"] = f"Port {port} is in use"
            else:
                result["checks"]["port"]["status"] = "pass"
                result["checks"]["port"]["message"] = f"Port {port} is available"
        except Exception as e:
            result["checks"]["port"]["status"] = "warning"
            result["checks"]["port"]["error"] = str(e)

        return result

    def check_startup(self) -> Dict:
        self.log("Checking startup capability...")
        result = {"status": "pass", "checks": {}}

        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"Software\\Microsoft\\Windows\\CurrentVersion\\Run", 0, winreg.KEY_READ)
            try:
                value, _ = winreg.QueryValueEx(key, self.app_name)
                result["checks"]["auto_start"] = {"status": "pass", "enabled": True, "value": value}
            except FileNotFoundError:
                result["checks"]["auto_start"] = {"status": "pass", "enabled": False}
            winreg.CloseKey(key)
        except Exception as e:
            result["checks"]["auto_start"] = {"status": "warning", "error": str(e)}

        main_py = os.path.join(self.install_path, "main.py")
        result["checks"]["main_file"] = {"status": "pass" if os.path.exists(main_py) else "fail", "path": main_py}

        return result

    def check_required_files(self) -> Dict:
        self.log("Checking required files...")
        result = {"status": "pass", "checks": {}}

        required_files = [
            "main.py",
            "requirements.txt",
            "configs/app_config.json"
        ]

        required_dirs = [
            "backend",
            "configs",
            "logs",
            "data"
        ]

        for f in required_files:
            path = os.path.join(self.install_path, f)
            if os.path.exists(path):
                result["checks"][f] = {"status": "pass", "exists": True}
            else:
                result["checks"][f] = {"status": "fail", "exists": False}
                result["status"] = "fail"

        for d in required_dirs:
            path = os.path.join(self.install_path, d)
            if os.path.isdir(path):
                result["checks"][f"dir_{d}"] = {"status": "pass", "exists": True}
            else:
                result["checks"][f"dir_{d}"] = {"status": "fail", "exists": False}
                result["status"] = "fail"

        return result

    def check_permissions(self) -> Dict:
        self.log("Checking file permissions...")
        result = {"status": "pass", "checks": {}}

        test_dirs = [self.config_path, self.log_path, self.db_path]

        for test_dir in test_dirs:
            if os.path.exists(test_dir):
                test_file = os.path.join(test_dir, ".test_write")
                try:
                    with open(test_file, "w") as f:
                        f.write("test")
                    os.remove(test_file)
                    result["checks"][os.path.basename(test_dir)] = {"status": "pass", "writable": True}
                except Exception as e:
                    result["checks"][os.path.basename(test_dir)] = {"status": "warning", "writable": False, "error": str(e)}
            else:
                result["checks"][os.path.basename(test_dir)] = {"status": "warning", "exists": False}

        return result

    def generate_report(self) -> str:
        report = self.run_all_checks()
        lines = []
        lines.append("=" * 60)
        lines.append(f"AI Email Organizer - Health Report")
        lines.append(f"Generated: {report['timestamp']}")
        lines.append("=" * 60)
        lines.append(f"\nSummary: {report['summary']['passed']} passed, {report['summary']['failed']} failed, {report['summary']['warnings']} warnings\n")

        for check_name, check_result in report["checks"].items():
            status = check_result.get("status", "unknown")
            lines.append(f"[{status.upper()}] {check_name}")
            if status != "pass":
                for key, value in check_result.items():
                    if key != "status":
                        lines.append(f"    {key}: {value}")
            lines.append("")

        return "\n".join(lines)


def main():
    validator = HealthValidator()

    if len(sys.argv) > 1 and sys.argv[1] == "--report":
        print(validator.generate_report())
    else:
        result = validator.run_all_checks()
        print(f"\nHealth Check Complete")
        print(f"Passed: {result['summary']['passed']}")
        print(f"Failed: {result['summary']['failed']}")
        print(f"Warnings: {result['summary']['warnings']}")
        print(f"\nReport saved to: {validator.health_report_path}")


if __name__ == "__main__":
    main()