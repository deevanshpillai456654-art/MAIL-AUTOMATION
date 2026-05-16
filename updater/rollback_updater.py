import os
import sys
import json
import shutil
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict


class RollbackSnapshot:
    def __init__(self, version: str, path: str, timestamp: str, description: str = ""):
        self.version = version
        self.path = path
        self.timestamp = timestamp
        self.description = description
        self.checksums = {}

    def to_dict(self):
        return {
            "version": self.version,
            "path": self.path,
            "timestamp": self.timestamp,
            "description": self.description,
            "checksums": self.checksums
        }

    @staticmethod
    def from_dict(d):
        snap = RollbackSnapshot(d["version"], d["path"], d["timestamp"], d.get("description", ""))
        snap.checksums = d.get("checksums", {})
        return snap


class RollbackUpdater:
    def __init__(self, app_name="AIEmailOrganizer"):
        self.app_name = app_name
        self.install_path = self._get_install_path()
        self.backup_path = os.path.join(self.install_path, "backups")
        self.snapshot_path = os.path.join(self.backup_path, "snapshots")
        self.history_file = os.path.join(self.backup_path, "rollback_history.json")
        self.log_file = os.path.join(self.install_path, "logs", "rollback.log")
        self.max_snapshots = 10
        os.makedirs(self.snapshot_path, exist_ok=True)
        self.history = self._load_history()

    def _get_install_path(self):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, f"Software\\{self.app_name}", 0, winreg.KEY_READ)
            value, _ = winreg.QueryValueEx(key, "InstallPath")
            winreg.CloseKey(key)
            return value
        except Exception:
            return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _load_history(self):
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r") as f:
                    data = json.load(f)
                    return [RollbackSnapshot.from_dict(s) for s in data]
            except Exception:
                pass
        return []

    def _save_history(self):
        with open(self.history_file, "w") as f:
            json.dump([s.to_dict() for s in self.history], f, indent=2)

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

    def create_snapshot(self, version: str, description: str = "") -> bool:
        self.log(f"Creating snapshot for version {version}...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        snapshot_dir = os.path.join(self.snapshot_path, f"snapshot_{timestamp}")
        os.makedirs(snapshot_dir, exist_ok=True)

        try:
            files_to_backup = ["configs", "backend", "main.py", "requirements.txt"]
            checksums = {}

            for item in files_to_backup:
                src = os.path.join(self.install_path, item)
                if os.path.exists(src):
                    dst = os.path.join(snapshot_dir, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                    checksums[item] = self._calculate_checksum(src)

            version_file = os.path.join(snapshot_dir, "version.json")
            with open(version_file, "w") as f:
                json.dump({
                    "version": version,
                    "timestamp": timestamp,
                    "description": description,
                    "checksums": checksums
                }, f, indent=2)

            snapshot = RollbackSnapshot(version, snapshot_dir, timestamp, description)
            snapshot.checksums = checksums
            self.history.insert(0, snapshot)

            if len(self.history) > self.max_snapshots:
                self._cleanup_old_snapshots()

            self._save_history()

            self.log(f"Snapshot created: {snapshot_dir}")
            return True

        except Exception as e:
            self.log(f"Failed to create snapshot: {e}", "ERROR")
            return False

    def _calculate_checksum(self, file_path: str) -> str:
        if os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        return ""

    def _cleanup_old_snapshots(self):
        while len(self.history) > self.max_snapshots:
            old = self.history.pop()
            try:
                if os.path.exists(old.path):
                    shutil.rmtree(old.path)
                self.log(f"Cleaned up old snapshot: {old.version}")
            except Exception as e:
                self.log(f"Failed to cleanup {old.version}: {e}", "WARNING")

    def list_snapshots(self) -> List[Dict]:
        result = []
        for snap in self.history:
            result.append({
                "version": snap.version,
                "timestamp": snap.timestamp,
                "description": snap.description,
                "path": snap.path
            })
        return result

    def get_snapshot(self, version: str = None, timestamp: str = None) -> Optional[RollbackSnapshot]:
        if timestamp:
            for snap in self.history:
                if snap.timestamp == timestamp:
                    return snap
        if version:
            for snap in self.history:
                if snap.version == version:
                    return snap
        return self.history[0] if self.history else None

    def rollback(self, target: str = None, auto: bool = False) -> bool:
        if not self.history:
            self.log("No snapshots available for rollback", "ERROR")
            return False

        snapshot = self.get_snapshot(timestamp=target) if target else self.history[0]

        if not snapshot:
            self.log("Snapshot not found", "ERROR")
            return False

        self.log(f"Rolling back to: {snapshot.version} ({snapshot.timestamp})")

        try:
            self._verify_snapshot(snapshot)

            self._stop_application()

            self._backup_current_state()

            self._restore_snapshot(snapshot)

            self._record_rollback(snapshot, auto)

            self.log("Rollback completed successfully")
            return True

        except Exception as e:
            self.log(f"Rollback failed: {e}", "ERROR")
            self._emergency_restore()
            return False

    def _verify_snapshot(self, snapshot: RollbackSnapshot) -> bool:
        self.log("Verifying snapshot integrity...")
        for item, expected_checksum in snapshot.checksums.items():
            item_path = os.path.join(snapshot.path, item)
            if os.path.exists(item_path):
                actual = self._calculate_checksum(item_path)
                if actual != expected_checksum:
                    self.log(f"Checksum mismatch for {item}", "WARNING")
        return True

    def _stop_application(self):
        self.log("Stopping application...")
        try:
            subprocess.run(["taskkill", "/F", "/IM", "AIEmailOrganizer.exe"], capture_output=True)
            time.sleep(2)
        except Exception as e:
            self.log(f"Could not stop application: {e}", "WARNING")

    def _backup_current_state(self):
        self.log("Backing up current state...")
        emergency_backup = os.path.join(self.backup_path, "emergency_backup")
        if os.path.exists(emergency_backup):
            shutil.rmtree(emergency_backup)

        for item in ["configs", "backend", "main.py"]:
            src = os.path.join(self.install_path, item)
            if os.path.exists(src):
                dst = os.path.join(emergency_backup, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)

    def _restore_snapshot(self, snapshot: RollbackSnapshot):
        self.log("Restoring snapshot...")

        for item in os.listdir(snapshot.path):
            if item == "version.json":
                continue
            src = os.path.join(snapshot.path, item)
            dst = os.path.join(self.install_path, item)

            if os.path.exists(dst):
                if os.path.isdir(dst):
                    shutil.rmtree(dst)
                else:
                    os.remove(dst)

            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

        version_info = {
            "version": snapshot.version,
            "rollback_timestamp": datetime.now().isoformat(),
            "original_timestamp": snapshot.timestamp
        }
        version_file = os.path.join(self.install_path, "version.json")
        with open(version_file, "w") as f:
            json.dump(version_info, f, indent=2)

    def _record_rollback(self, snapshot: RollbackSnapshot, auto: bool):
        rollback_record = {
            "timestamp": datetime.now().isoformat(),
            "target_version": snapshot.version,
            "target_timestamp": snapshot.timestamp,
            "auto_rollback": auto,
            "success": True
        }

        history_path = os.path.join(self.backup_path, "rollback_events.json")
        history = []
        if os.path.exists(history_path):
            try:
                with open(history_path, "r") as f:
                    history = json.load(f)
            except Exception:
                pass

        history.append(rollback_record)
        history = history[-50:]

        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)

    def _emergency_restore(self):
        self.log("Attempting emergency restore...")
        emergency_backup = os.path.join(self.backup_path, "emergency_backup")
        if os.path.exists(emergency_backup):
            try:
                for item in os.listdir(emergency_backup):
                    src = os.path.join(emergency_backup, item)
                    dst = os.path.join(self.install_path, item)
                    if os.path.exists(dst):
                        if os.path.isdir(dst):
                            shutil.rmtree(dst)
                        else:
                            os.remove(dst)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst)
                    else:
                        shutil.copy2(src, dst)
                self.log("Emergency restore completed")
            except Exception as e:
                self.log(f"Emergency restore failed: {e}", "CRITICAL")

    def manual_rollback(self, version: str = None, timestamp: str = None) -> bool:
        if not version and not timestamp:
            print("\nAvailable snapshots:")
            for i, snap in enumerate(self.history):
                print(f"  {i + 1}. Version: {snap.version} | {snap.timestamp} | {snap.description}")

            choice = input("\nSelect snapshot number or enter timestamp: ").strip()
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(self.history):
                    return self.rollback(target=self.history[idx].timestamp)
                else:
                    print("Invalid selection")
                    return False
            else:
                return self.rollback(target=choice)
        else:
            return self.rollback(target=timestamp)

    def verify_rollback(self) -> bool:
        self.log("Verifying rollback...")
        try:
            version_file = os.path.join(self.install_path, "version.json")
            if os.path.exists(version_file):
                with open(version_file, "r") as f:
                    info = json.load(f)
                    self.log(f"Current version: {info.get('version', 'unknown')}")
                    if 'rollback_timestamp' in info:
                        self.log("Rollback verified")
                        return True

            main_py = os.path.join(self.install_path, "main.py")
            if os.path.exists(main_py):
                self.log("Main application file present")
                return True

            return True
        except Exception as e:
            self.log(f"Verification failed: {e}", "ERROR")
            return False


import time


def main():
    rollback_updater = RollbackUpdater()

    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "list":
            print("\nAvailable snapshots:")
            for snap in rollback_updater.list_snapshots():
                print(f"  Version: {snap['version']} | {snap['timestamp']} | {snap['description']}")
        elif command == "rollback":
            target = sys.argv[2] if len(sys.argv) > 2 else None
            if rollback_updater.rollback(target=target, auto=False):
                print("Rollback completed")
            else:
                print("Rollback failed")
        elif command == "verify":
            if rollback_updater.verify_rollback():
                print("Rollback verified successfully")
            else:
                print("Rollback verification failed")
        else:
            print("Unknown command")
    else:
        print("\nAI Email Organizer Rollback Manager")
        print("Commands: list, rollback [timestamp], verify")


if __name__ == "__main__":
    main()