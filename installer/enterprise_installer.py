import os
import sys
import subprocess
import shutil
import winreg
import socket
import json
import hashlib
from pathlib import Path
from datetime import datetime


class EnterpriseInstaller:
    def __init__(self, install_path=None):
        self.app_name = "INTEMO"
        self.display_name = "INTEMO"
        self.app_version = "14.0.1B"
        self.install_path = install_path or os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), self.display_name)
        self.runtime_home = os.path.join(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or self.install_path, self.app_name)
        self.desktop_path = os.path.join(os.environ["USERPROFILE"], "Desktop")
        self.start_menu_path = os.path.join(os.environ["APPDATA"], "Microsoft\\Windows\\Start Menu\\Programs")
        self.backup_path = os.path.join(self.runtime_home, "backups")
        self.temp_path = os.path.join(os.environ["TEMP"], f"{self.app_name}_install")
        self.log_file = os.path.join(self.install_path, "install.log")
        self.checksums = {}

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

    def check_prerequisites(self):
        self.log("Checking prerequisites...")
        issues = []

        if sys.version_info < (3, 8):
            issues.append(f"Python 3.8+ required, found {sys.version_info.major}.{sys.version_info.minor}")

        required_modules = ["winreg", "subprocess", "json", "hashlib"]
        for module in required_modules:
            try:
                __import__(module)
            except ImportError:
                issues.append(f"Required module missing: {module}")

        disk = shutil.disk_usage(self.install_path)
        if disk.free < 500 * 1024 * 1024:
            issues.append(f"Insufficient disk space: {disk.free // (1024*1024)}MB available")

        admin = self.check_admin()
        self.log(f"Administrator privileges: {admin}")

        if issues:
            for issue in issues:
                self.log(issue, "ERROR")
            return False, issues
        return True, []

    def check_admin(self):
        try:
            return os.getuid() == 0
        except AttributeError:
            try:
                import ctypes
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False

    def create_directories(self):
        self.log("Creating directories...")
        dirs = [
            self.install_path,
            self.backup_path,
            self.temp_path,
            os.path.join(self.runtime_home, "logs"),
            os.path.join(self.runtime_home, "cache"),
            os.path.join(self.runtime_home, "models"),
            os.path.join(self.runtime_home, "data"),
            os.path.join(self.runtime_home, "database"),
        ]
        for d in dirs:
            try:
                os.makedirs(d, exist_ok=True)
                self.log(f"Created: {d}")
            except Exception as e:
                self.log(f"Failed to create {d}: {e}", "ERROR")
                return False
        return True

    def create_service_user(self):
        self.log("Creating service user...")
        username = f"{self.app_name}Service"
        try:
            result = subprocess.run(
                ["net", "user"],
                capture_output=True,
                text=True
            )
            if username in result.stdout:
                self.log(f"User {username} already exists")
                return True

            subprocess.run(
                ["net", "user", username, "ChangeMe123!@#", "/add"],
                capture_output=True
            )
            subprocess.run(
                ["net", "localgroup", "Administrators", username, "/add"],
                capture_output=True
            )
            self.log(f"Created service user: {username}")
            return True
        except Exception as e:
            self.log(f"Could not create service user: {e}", "WARNING")
            return True

    def create_registry_entries(self):
        self.log("Creating registry entries...")
        try:
            key_path = f"Software\\{self.app_name}"
            key = winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, key_path)
            winreg.SetValueEx(key, "InstallPath", 0, winreg.REG_SZ, self.install_path)
            winreg.SetValueEx(key, "Version", 0, winreg.REG_SZ, self.app_version)
            winreg.SetValueEx(key, "InstallDate", 0, winreg.REG_SZ, datetime.now().strftime("%Y-%m-%d"))
            winreg.CloseKey(key)

            key_path_user = f"Software\\{self.app_name}"
            key_user = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path_user)
            winreg.SetValueEx(key_user, "InstallPath", 0, winreg.REG_SZ, self.install_path)
            winreg.SetValueEx(key_user, "Version", 0, winreg.REG_SZ, self.app_version)
            winreg.CloseKey(key_user)

            self.log("Registry entries created")
            return True
        except Exception as e:
            self.log(f"Registry creation failed: {e}", "ERROR")
            return False

    def configure_firewall(self):
        self.log("Configuring firewall...")
        rule_name = f"{self.app_name}"
        try:
            subprocess.run(
                ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rule_name}"],
                capture_output=True
            )
            subprocess.run([
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={rule_name}",
                "dir=in",
                "action=allow",
                f"program={os.path.join(self.install_path, 'AIEmailOrganizer.exe')}",
                "enable=yes",
                "profile=any"
            ], capture_output=True)
            self.log("Firewall rule added")
            return True
        except Exception as e:
            self.log(f"Firewall configuration failed: {e}", "WARNING")
            return True

    def create_desktop_shortcut(self):
        self.log("Creating desktop shortcut...")
        try:
            import pythoncom
            from win32com.shell import shell, shellcon

            desktop = shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOP, None, 0)
            shortcut_path = os.path.join(desktop, f"{self.app_name}.lnk")

            shell_link = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink,
                None,
                pythoncom.IID_IShellLink
            )
            shell_link.SetPath(os.path.join(self.install_path, "open_dashboard.bat"))
            shell_link.SetArguments("")
            shell_link.SetDescription(self.app_name)

            persist_file = shell_link.QueryInterface(pythoncom.IID_IPersistFile)
            persist_file.Save(shortcut_path, 0)

            self.log(f"Desktop shortcut created: {shortcut_path}")
            return True
        except Exception as e:
            self.log(f"Desktop shortcut failed: {e}", "WARNING")
            return self._create_shortcut_fallback()

    def _create_shortcut_fallback(self):
        try:
            import winshell
            desktop = winshell.shortcut(self.desktop_path)
            desktop.path = os.path.join(self.install_path, "AIEmailOrganizer.exe")
            desktop.write(self.app_name + ".lnk")
            return True
        except Exception as e:
            self.log(f"Fallback shortcut failed: {e}", "WARNING")
            return True

    def create_start_menu_entry(self):
        self.log("Creating Start Menu entry...")
        try:
            start_menu_folder = os.path.join(self.start_menu_path, self.app_name)
            os.makedirs(start_menu_folder, exist_ok=True)

            shortcut_path = os.path.join(start_menu_folder, f"{self.app_name}.lnk")

            import pythoncom
            from win32com.shell import shell, shellcon

            shell_link = pythoncom.CoCreateInstance(
                shell.CLSID_ShellLink,
                None,
                pythoncom.IID_IShellLink
            )
            shell_link.SetPath(os.path.join(self.install_path, "open_dashboard.bat"))
            shell_link.SetArguments("")
            shell_link.SetDescription(self.app_name)

            persist_file = shell_link.QueryInterface(pythoncom.IID_IPersistFile)
            persist_file.Save(shortcut_path, 0)

            self.log("Start Menu entry created")
            return True
        except Exception as e:
            self.log(f"Start Menu entry failed: {e}", "WARNING")
            return True

    def register_file_association(self):
        self.log("Registering file association...")
        try:
            ext = ".aieo"
            prog_id = f"{self.app_name}.File"

            key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, ext)
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, prog_id)
            winreg.CloseKey(key)

            key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, prog_id)
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"{self.app_name} Configuration File")
            winreg.CloseKey(key)

            key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, f"{prog_id}\\DefaultIcon")
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f"{self.install_path}\\icon.ico")
            winreg.CloseKey(key)

            key = winreg.CreateKey(winreg.HKEY_CLASSES_ROOT, f"{prog_id}\\shell\\open\\command")
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{os.path.join(self.install_path, "open_dashboard.bat")}" "%1"')
            winreg.CloseKey(key)

            self.log("File association registered")
            return True
        except Exception as e:
            self.log(f"File association failed: {e}", "WARNING")
            return True

    def register_auto_start(self):
        self.log("Registering auto-start...")
        try:
            key_path = f"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
            system_root = os.environ.get("SystemRoot", r"C:\\Windows")
            wscript_path = os.path.join(system_root, "System32", "wscript.exe")
            vbs_path = os.path.join(self.install_path, "start_background.vbs")
            startup_cmd = f'"{wscript_path}" //B //Nologo "{vbs_path}"'
            winreg.SetValueEx(key, "INTEMO", 0, winreg.REG_SZ, startup_cmd)
            winreg.CloseKey(key)
            self.log("Auto-start registered")
            return True
        except Exception as e:
            self.log(f"Auto-start registration failed: {e}", "WARNING")
            return True

    def copy_application_files(self):
        self.log("Copying application files...")
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        prepared_payload = os.path.join(project_root, "dist", "AIEmailOrganizer")
        source = prepared_payload if os.path.exists(os.path.join(prepared_payload, "start_background.vbs")) else project_root
        ignored = {"dist", "build", "installers", ".git", ".pytest_cache", "__pycache__"}
        try:
            os.makedirs(self.install_path, exist_ok=True)
            for item in os.listdir(source):
                if item in ignored:
                    continue
                src = os.path.join(source, item)
                dst = os.path.join(self.install_path, item)
                if os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".pytest_cache"))
                    self.log(f"Copied folder: {item}")
                elif os.path.isfile(src):
                    shutil.copy2(src, dst)
                    self.log(f"Copied file: {item}")
            return True
        except Exception as e:
            self.log(f"File copy failed: {e}", "ERROR")
            return False

    def create_config(self):
        self.log("Creating configuration...")
        config = {
            "app_name": self.app_name,
            "version": self.app_version,
            "install_path": self.install_path,
            "port": 4597,
            "auto_update": True,
            "update_check_interval": 3600,
            "log_level": "INFO",
            "database": {
                "type": "sqlite",
                "path": os.path.join(self.runtime_home, "data", "emails.db")
            },
            "security": {
                "encrypt_data": True,
                "require_auth": True
            }
        }
        config_path = os.path.join(self.runtime_home, "config.json")
        try:
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            self.log(f"Configuration created: {config_path}")
            return True
        except Exception as e:
            self.log(f"Config creation failed: {e}", "ERROR")
            return False

    def verify_installation(self):
        self.log("Verifying installation...")
        checks = [
            os.path.exists(self.install_path),
            os.path.exists(os.path.join(self.install_path, "start_background.vbs")),
            os.path.exists(os.path.join(self.runtime_home, "data")),
            os.path.exists(os.path.join(self.runtime_home, "logs")),
        ]
        if all(checks):
            self.log("Installation verified successfully")
            return True
        self.log("Installation verification failed", "ERROR")
        return False

    def install(self):
        self.log("=" * 50)
        self.log(f"Starting {self.app_name} Enterprise Installation")
        self.log("=" * 50)

        success, issues = self.check_prerequisites()
        if not success:
            self.log("Prerequisites check failed. Please resolve the following:", "ERROR")
            for issue in issues:
                self.log(f"  - {issue}", "ERROR")
            return False

        steps = [
            ("Create Directories", self.create_directories),
            ("Copy Application Files", self.copy_application_files),
            ("Create Configuration", self.create_config),
            ("Create Service User", self.create_service_user),
            ("Create Registry Entries", self.create_registry_entries),
            ("Configure Firewall", self.configure_firewall),
            ("Create Desktop Shortcut", self.create_desktop_shortcut),
            ("Create Start Menu Entry", self.create_start_menu_entry),
            ("Register File Association", self.register_file_association),
            ("Register Auto-Start", self.register_auto_start),
            ("Verify Installation", self.verify_installation),
        ]

        for step_name, step_func in steps:
            self.log(f"Step: {step_name}")
            if not step_func():
                self.log(f"Step failed: {step_name}", "ERROR")
                return False

        self.log("=" * 50)
        self.log("Installation completed successfully!")
        self.log(f"Installation path: {self.install_path}")
        self.log("=" * 50)
        return True


def main():
    installer = EnterpriseInstaller()
    if installer.install():
        print("\nInstallation completed successfully!")
        sys.exit(0)
    else:
        print("\nInstallation failed. Check logs for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()