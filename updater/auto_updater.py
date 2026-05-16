import os
import sys
import json
import time
import hashlib
import shutil
import subprocess
import threading
import urllib.request
import urllib.error
import ssl
import base64
import zipfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Callable

# Ed25519 public key for update manifest signing (raw 32-byte public key, base64-encoded).
# Set this to your production signing key before shipping.
# Generate: python -c "from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey; import base64; k=Ed25519PrivateKey.generate(); print(base64.b64encode(k.public_key().public_bytes_raw()).decode())"
_UPDATE_SIGNING_PUBKEY_B64: Optional[str] = None  # Must be set before production use


class UpdateProgress:
    def __init__(self):
        self.total_bytes = 0
        self.downloaded_bytes = 0
        self.current_file = ""
        self.status = "idle"
        self.percentage = 0
        self.speed = 0

    def update(self, downloaded: int, total: int, filename: str):
        self.downloaded_bytes = downloaded
        self.total_bytes = total
        self.current_file = filename
        if total > 0:
            self.percentage = int((downloaded / total) * 100)
        if time.time() > getattr(self, 'last_time', time.time()):
            self.speed = downloaded - getattr(self, 'last_bytes', 0)
            self.last_time = time.time()
            self.last_bytes = downloaded


class AutoUpdater:
    def __init__(self, app_name="AIEmailOrganizer", update_url=None):
        self.app_name = app_name
        self.update_url = update_url or "https://updates.example.com/aieo"
        self.install_path = self._get_install_path()
        self.runtime_home = self._get_runtime_home()
        self.version_file = os.path.join(self.runtime_home, "version.json")
        self.update_temp = os.path.join(self.runtime_home, "updates", "temp")
        self.backup_path = os.path.join(self.runtime_home, "backups")
        self.log_file = os.path.join(self.runtime_home, "logs", "updater.log")
        self.current_version = self._load_version()
        self.progress = UpdateProgress()
        self._callbacks = {}
        os.makedirs(self.update_temp, exist_ok=True)

    def _get_install_path(self):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"Software\\{self.app_name}", 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, "InstallPath")
            winreg.CloseKey(key)
            return value
        except Exception:
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _get_runtime_home(self):
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return os.path.join(base, self.app_name)
        if os.name == "nt":
            return os.path.join(os.path.expanduser("~"), "AppData", "Local", self.app_name)
        return os.path.join(os.environ.get("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share")), self.app_name)

    def _load_version(self):
        if os.path.exists(self.version_file):
            try:
                with open(self.version_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"version": "9.7.0", "build": 1}

    def _save_version(self, version_info):
        with open(self.version_file, "w") as f:
            json.dump(version_info, f, indent=2)

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

    def check_for_updates(self) -> Optional[Dict]:
        self.log("Checking for updates...")
        try:
            version_info = self._load_version()
            current = version_info.get("version", "9.7.0")

            manifest_url = f"{self.update_url}/manifest.json"
            try:
                req = urllib.request.Request(manifest_url)
                req.add_header('User-Agent', f'{self.app_name}/9.7.0')
                with urllib.request.urlopen(req, timeout=10, context=self._make_ssl_context()) as response:
                    remote_info = json.loads(response.read().decode())
            except Exception as exc:
                self.log(f"Update manifest unavailable: {exc}; continuing without network update", "WARNING")
                return None

            if not self._validate_manifest(remote_info):
                self.log("Update manifest failed validation", "ERROR")
                return None

            if not self._verify_manifest_signature(remote_info):
                self.log("Update manifest signature check failed", "ERROR")
                return None

            if self._compare_versions(remote_info.get("version", "9.7.0"), current) > 0:
                self.log(f"Update available: {remote_info['version']} (current: {current})")
                return remote_info
            else:
                self.log("No updates available")
                return None
        except Exception as e:
            self.log(f"Update check failed: {e}", "ERROR")
            return None

    def _compare_versions(self, v1: str, v2: str) -> int:
        parts1 = [int(x) for x in v1.split('.')]
        parts2 = [int(x) for x in v2.split('.')]
        for i in range(max(len(parts1), len(parts2))):
            p1 = parts1[i] if i < len(parts1) else 0
            p2 = parts2[i] if i < len(parts2) else 0
            if p1 > p2:
                return 1
            elif p1 < p2:
                return -1
        return 0

    def _validate_manifest(self, remote_info: Dict) -> bool:
        if not isinstance(remote_info, dict):
            return False
        version = str(remote_info.get("version", ""))
        if not version or version.startswith(("0.", "1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.")):
            return False
        files = remote_info.get("files", [])
        if not isinstance(files, list):
            return False
        for item in files:
            if not isinstance(item, dict):
                return False
            name = str(item.get("name", ""))
            sha256 = str(item.get("sha256", ""))
            if not name or ".." in name or name.startswith(("/", "\\")):
                return False
            if len(sha256) != 64 or any(c not in "0123456789abcdefABCDEF" for c in sha256):
                return False
        return True

    def download_update(self, update_info: Dict, progress_callback: Optional[Callable] = None) -> bool:
        self.log("Downloading update...")
        self.progress.status = "downloading"

        if progress_callback:
            self._callbacks['progress'] = progress_callback

        try:
            files = update_info.get("files", [])
            downloaded_files = []

            for file_info in files:
                filename = file_info["name"]
                self.log(f"Downloading: {filename}")
                self.progress.current_file = filename
                self.progress.total_bytes = file_info.get("size", 0)

                file_path = os.path.join(self.update_temp, filename)
                try:
                    file_url = f"{self.update_url}/files/{filename}"
                    req = urllib.request.Request(file_url)
                    req.add_header('User-Agent', f'{self.app_name}/9.7.0')

                    with urllib.request.urlopen(req, timeout=30, context=self._make_ssl_context()) as response:
                        total_size = int(response.headers.get('Content-Length', 0))
                        self.progress.total_bytes = total_size

                        with open(file_path, "wb") as f:
                            downloaded = 0
                            while True:
                                chunk = response.read(8192)
                                if not chunk:
                                    break
                                f.write(chunk)
                                downloaded += len(chunk)
                                self.progress.update(downloaded, total_size, filename)
                                if self._callbacks.get('progress'):
                                    self._callbacks['progress'](self.progress)

                    expected_sha = str(file_info.get("sha256", ""))
                    actual_sha = self._sha256_file(file_path)
                    if expected_sha and actual_sha.lower() != expected_sha.lower():
                        self.log(f"Checksum mismatch for {filename}", "ERROR")
                        return False
                    downloaded_files.append(file_path)
                    self.log(f"Downloaded: {filename}")

                except Exception as e:
                    self.log(f"Failed to download {filename}: {e}", "ERROR")
                    return False

            self._notify_progress("Download complete")
            self.progress.status = "ready"
            return True

        except Exception as e:
            self.log(f"Download failed: {e}", "ERROR")
            self.progress.status = "failed"
            return False

    def set_update_ready_callback(self, fn: Callable) -> None:
        """Register a callback fired when a downloaded update is ready to install.
        The callback receives the update_info dict.  The user must then call
        apply_update(user_consent=True) to proceed."""
        self._callbacks['update_ready'] = fn

    def _make_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx

    def _verify_manifest_signature(self, manifest: Dict) -> bool:
        """Verify Ed25519 signature over manifest contents."""
        if not _UPDATE_SIGNING_PUBKEY_B64:
            self.log("Update signing key not configured — signature check skipped", "WARNING")
            return True
        sig_b64 = manifest.get("signature")
        if not sig_b64:
            self.log("Manifest missing 'signature' field — refusing update", "ERROR")
            return False
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
            pub_bytes = base64.b64decode(_UPDATE_SIGNING_PUBKEY_B64)
            pubkey = Ed25519PublicKey.from_public_bytes(pub_bytes)
            unsigned = {k: v for k, v in manifest.items() if k != "signature"}
            msg = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
            pubkey.verify(base64.b64decode(sig_b64), msg)
            return True
        except Exception as exc:
            self.log(f"Manifest signature invalid: {exc}", "ERROR")
            return False

    def _notify_progress(self, message: str):
        if self._callbacks.get('progress'):
            self._callbacks['progress'](self.progress)

    def _sha256_file(self, file_path: str) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def apply_update(self, user_consent: bool = False) -> bool:
        if not user_consent:
            self.log("Update requires user consent", "WARNING")
            return False

        self.log("Applying update...")
        self.progress.status = "applying"

        try:
            self._create_backup()

            self._stop_services()

            files = os.listdir(self.update_temp)
            for filename in files:
                src = os.path.join(self.update_temp, filename)
                dst = os.path.join(self.install_path, filename)

                if filename.endswith(".zip"):
                    self._extract_update(src)
                else:
                    if os.path.exists(dst):
                        shutil.copy2(dst, os.path.join(self.backup_path, filename))
                    shutil.copy2(src, dst)

            self._update_version_info()

            self._start_services()

            self._cleanup_temp()

            self.progress.status = "complete"
            self.log("Update applied successfully")
            return True

        except Exception as e:
            self.log(f"Update application failed: {e}", "ERROR")
            self._rollback()
            return False

    def _create_backup(self):
        self.log("Creating backup...")
        backup_dir = os.path.join(self.backup_path, datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(backup_dir, exist_ok=True)

        for item in ["configs", "backend", "main.py"]:
            src = os.path.join(self.install_path, item)
            if os.path.exists(src):
                dst = os.path.join(backup_dir, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

        self.log(f"Backup created: {backup_dir}")

    def _stop_services(self):
        self.log("Stopping services...")
        try:
            subprocess.run(["taskkill", "/F", "/IM", "AIEmailOrganizer.exe"], capture_output=True)
            time.sleep(2)
        except Exception as e:
            self.log(f"Could not stop services: {e}", "WARNING")

    def _start_services(self):
        self.log("Starting services...")
        try:
            main_py = os.path.join(self.install_path, "main.py")
            if os.path.exists(main_py):
                subprocess.Popen([sys.executable, main_py, "--background"])
        except Exception as e:
            self.log(f"Could not start services: {e}", "WARNING")

    def _extract_update(self, zip_path):
        self.log(f"Extracting: {zip_path}")
        install_root = Path(self.install_path).resolve()
        with zipfile.ZipFile(zip_path, 'r') as zf:
            for member in zf.namelist():
                dest = (install_root / member).resolve()
                # Zip slip guard: reject any path that escapes install_root
                if not str(dest).startswith(str(install_root) + os.sep) and dest != install_root:
                    raise ValueError(f"Zip slip blocked — unsafe member path: {member}")
            zf.extractall(self.install_path)

    def _update_version_info(self):
        version_info = self._load_version()
        version_info["last_updated"] = datetime.now().isoformat()
        self._save_version(version_info)

    def _rollback(self):
        self.log("Rolling back...")
        try:
            backups = sorted([d for d in os.listdir(self.backup_path) if os.path.isdir(os.path.join(self.backup_path, d))])
            if backups:
                latest_backup = os.path.join(self.backup_path, backups[-1])
                for item in os.listdir(latest_backup):
                    src = os.path.join(latest_backup, item)
                    dst = os.path.join(self.install_path, item)
                    if os.path.isdir(src):
                        if os.path.exists(dst):
                            shutil.rmtree(dst)
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                self.log("Rollback completed")
        except Exception as e:
            self.log(f"Rollback failed: {e}", "CRITICAL")

    def _cleanup_temp(self):
        try:
            shutil.rmtree(self.update_temp)
            os.makedirs(self.update_temp, exist_ok=True)
        except Exception as e:
            self.log(f"Cleanup failed: {e}", "WARNING")

    def schedule_update(self, delay_seconds: int = 3600):
        self.log(f"Scheduling update in {delay_seconds} seconds")
        def delayed_update():
            time.sleep(delay_seconds)
            self._perform_scheduled_update()

        thread = threading.Thread(target=delayed_update, daemon=True)
        thread.start()

    def _perform_scheduled_update(self):
        self.log("Performing scheduled update check")
        update_info = self.check_for_updates()
        if not update_info:
            return
        if self.download_update(update_info):
            # Never apply silently — notify the UI and let the user decide
            cb = self._callbacks.get('update_ready')
            if cb:
                try:
                    cb(update_info)
                except Exception as exc:
                    self.log(f"Update-ready callback raised: {exc}", "WARNING")
            else:
                self.log(
                    f"Update {update_info.get('version')} downloaded and ready. "
                    "Register an 'update_ready' callback to prompt the user.",
                    "WARNING",
                )


def main():
    updater = AutoUpdater()

    print(f"Current version: {updater.current_version.get('version', 'unknown')}")

    update_info = updater.check_for_updates()
    if update_info:
        print(f"\nUpdate available: {update_info.get('version')}")
        print(f"Release notes: {update_info.get('release_notes', 'N/A')}")

        response = input("\nDownload and install update? (y/n): ")
        if response.lower() == 'y':
            if updater.download_update(update_info):
                if updater.apply_update(user_consent=True):
                    print("Update completed successfully!")
                else:
                    print("Update failed. Rollback was attempted.")
    else:
        print("No updates available")


if __name__ == "__main__":
    main()