"""
Backup and restore functionality for AI Email Organizer
"""

import json
import logging
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List

_log = logging.getLogger(__name__)


class BackupManager:
    def __init__(self, data_dir: str = None, backup_dir: str = None):
        if data_dir is None:
            data_dir = Path(__file__).parent.parent / "data"
        if backup_dir is None:
            backup_dir = Path(__file__).parent.parent / "data" / "backups"

        self.data_dir = Path(data_dir)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, name: str = None) -> str:
        if name is None:
            name = datetime.now().strftime("%Y%m%d_%H%M%S")

        backup_path = self.backup_dir / f"backup_{name}.zip"

        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            if self.data_dir.exists():
                for file in self.data_dir.rglob("*"):
                    if file.is_file() and "backups" not in str(file):
                        arcname = file.relative_to(self.data_dir)
                        zipf.write(file, arcname)

        backup_info = {
            "name": name,
            "created_at": datetime.now().isoformat(),
            "size_bytes": os.path.getsize(backup_path),
            "files": self._get_file_list()
        }

        info_path = self.backup_dir / f"backup_{name}.json"
        with open(info_path, "w") as f:
            json.dump(backup_info, f, indent=2)

        return str(backup_path)

    def restore_backup(self, backup_name: str) -> bool:
        backup_path = self.backup_dir / f"backup_{backup_name}.zip"

        if not backup_path.exists():
            return False

        temp_dir = self.backup_dir / "temp_restore"
        temp_dir.mkdir(exist_ok=True)

        try:
            with zipfile.ZipFile(backup_path, "r") as zipf:
                zipf.extractall(temp_dir)

            for item in temp_dir.rglob("*"):
                if item.is_file():
                    dest = self.data_dir / item.relative_to(temp_dir)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest)

            shutil.rmtree(temp_dir)
            return True

        except Exception as e:
            _log.error("Restore error: %s", e)
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            return False

    def list_backups(self) -> List[Dict]:
        backups = []

        for info_file in self.backup_dir.glob("backup_*.json"):
            try:
                with open(info_file, "r") as f:
                    backups.append(json.load(f))
            except Exception as exc:
                _log.warning("Skipping invalid backup manifest %s: %s", info_file, exc)

        return sorted(backups, key=lambda x: x.get("created_at", ""), reverse=True)

    def delete_backup(self, backup_name: str) -> bool:
        backup_zip = self.backup_dir / f"backup_{backup_name}.zip"
        backup_info = self.backup_dir / f"backup_{backup_name}.json"

        deleted = False
        if backup_zip.exists():
            backup_zip.unlink()
            deleted = True
        if backup_info.exists():
            backup_info.unlink()
            deleted = True

        return deleted

    def _get_file_list(self) -> List[str]:
        files = []
        if self.data_dir.exists():
            for file in self.data_dir.rglob("*"):
                if file.is_file() and "backups" not in str(file):
                    files.append(str(file.relative_to(self.data_dir)))
        return files

    def export_config(self, export_path: str) -> bool:
        config_data = {}

        config_file = Path(__file__).parent.parent / "config.py"
        if config_file.exists():
            with open(config_file, "r") as f:
                config_data["config_py"] = f.read()

        rules_file = self.data_dir / "rules.json"
        if rules_file.exists():
            with open(rules_file, "r") as f:
                config_data["rules"] = json.load(f)

        with open(export_path, "w") as f:
            json.dump(config_data, f, indent=2)

        return True

    def import_config(self, import_path: str) -> bool:
        try:
            with open(import_path, "r") as f:
                config_data = json.load(f)

            if "rules" in config_data:
                rules_file = self.data_dir / "rules.json"
                with open(rules_file, "w") as f:
                    json.dump(config_data["rules"], f, indent=2)

            return True
        except Exception as e:
            _log.error("Import error: %s", e)
            return False


backup_manager = BackupManager()


def auto_backup():
    """Create automatic backup"""
    return backup_manager.create_backup()


def get_backup_list() -> List[Dict]:
    return backup_manager.list_backups()
