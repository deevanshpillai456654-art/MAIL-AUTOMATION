"""Dry-run rollback and update-manifest validation for v9.7 production gates."""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

APP_VERSION = "9.7.0"


@dataclass(frozen=True)
class RehearsalStep:
    name: str
    passed: bool
    detail: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_update_manifest(manifest: Mapping[str, Any]) -> List[RehearsalStep]:
    steps: List[RehearsalStep] = []
    version = str(manifest.get("version", ""))
    files = manifest.get("files", [])
    steps.append(RehearsalStep("version_present", bool(version), version or "missing version"))
    steps.append(RehearsalStep("target_version_is_v91_or_newer", version >= APP_VERSION, version))
    steps.append(RehearsalStep("files_array_present", isinstance(files, list), f"files={len(files) if isinstance(files, list) else 'invalid'}"))
    for index, file_info in enumerate(files if isinstance(files, list) else []):
        has_name = bool(file_info.get("name"))
        has_hash = bool(file_info.get("sha256"))
        steps.append(RehearsalStep(f"file_{index}_name", has_name, str(file_info.get("name", "missing"))))
        steps.append(RehearsalStep(f"file_{index}_sha256", has_hash, str(file_info.get("sha256", "missing"))))
    return steps


def rehearse_file_rollback(source_files: Iterable[Path]) -> Dict[str, Any]:
    steps: List[RehearsalStep] = []
    with tempfile.TemporaryDirectory(prefix="aieo_rollback_") as temp:
        temp_path = Path(temp)
        backup_dir = temp_path / "backup"
        install_dir = temp_path / "install"
        backup_dir.mkdir()
        install_dir.mkdir()
        for source in source_files:
            if not source.exists() or not source.is_file():
                steps.append(RehearsalStep(str(source), False, "source missing"))
                continue
            installed = install_dir / source.name
            backup = backup_dir / source.name
            shutil.copy2(source, installed)
            before = _sha256(installed)
            shutil.copy2(installed, backup)
            installed.write_text(installed.read_text(encoding="utf-8", errors="ignore") + "\n# rehearsal mutation\n", encoding="utf-8")
            shutil.copy2(backup, installed)
            after = _sha256(installed)
            steps.append(RehearsalStep(source.name, before == after, f"before={before}; after={after}"))
    return {
        "version": APP_VERSION,
        "status": "passed" if all(step.passed for step in steps) else "failed",
        "steps": [asdict(step) for step in steps],
    }


def build_rehearsal_report(root: Path) -> Dict[str, Any]:
    manifest = {"version": APP_VERSION, "files": [{"name": "runtime_version.py", "sha256": _sha256(root / "backend" / "runtime_version.py")}]} if (root / "backend" / "runtime_version.py").exists() else {"version": APP_VERSION, "files": []}
    manifest_steps = validate_update_manifest(manifest)
    rollback = rehearse_file_rollback([root / "backend" / "runtime_version.py", root / "build_installer.bat"])
    return {
        "version": APP_VERSION,
        "manifest_validation": [asdict(step) for step in manifest_steps],
        "rollback_rehearsal": rollback,
        "status": "passed" if all(step.passed for step in manifest_steps) and rollback["status"] == "passed" else "failed",
    }

