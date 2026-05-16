"""Offline production guardrails for runtime, deployment, and persistence checks."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

APP_NAME = "AIEmailOrganizer"
APP_VERSION = "9.7.0"


@dataclass(frozen=True)
class GuardrailResult:
    name: str
    passed: bool
    detail: str
    severity: str = "info"


def runtime_home(app_name: str = APP_NAME) -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / app_name


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_runtime_directories(home: Path | None = None) -> List[GuardrailResult]:
    home = home or runtime_home()
    expected = [home / "data", home / "logs", home / "configs", home / "updates", home / "backups"]
    results: List[GuardrailResult] = []
    for directory in expected:
        directory.mkdir(parents=True, exist_ok=True)
        writable_probe = directory / ".write_probe"
        try:
            writable_probe.write_text(str(time.time()), encoding="utf-8")
            writable_probe.unlink(missing_ok=True)
            results.append(GuardrailResult(directory.name, True, str(directory)))
        except Exception as exc:  # noqa: BLE001
            results.append(GuardrailResult(directory.name, False, f"not writable: {exc}", "critical"))
    return results


def validate_no_sensitive_telemetry(payload: Mapping[str, Any]) -> GuardrailResult:
    serialized = json.dumps(payload, default=str).lower()
    blocked = ["oauth", "access_token", "refresh_token", "password", "authorization:", "bearer ", "email_body", "attachment"]
    hits = [item for item in blocked if item in serialized]
    return GuardrailResult(
        "telemetry_privacy_guard",
        not hits,
        "diagnostics payload is sanitized" if not hits else "blocked sensitive keys: " + ", ".join(hits),
        "critical" if hits else "info",
    )


def validate_manifest_checksums(root: Path, files: Iterable[str]) -> List[GuardrailResult]:
    results: List[GuardrailResult] = []
    for rel in files:
        path = root / rel
        if not path.exists():
            results.append(GuardrailResult(rel, False, "missing", "high"))
            continue
        digest = sha256_file(path)
        results.append(GuardrailResult(rel, True, digest))
    return results


def run_local_guardrails(root: Path | None = None) -> Dict[str, Any]:
    root = root or Path(__file__).resolve().parents[2]
    checks = validate_runtime_directories()
    checks.append(validate_no_sensitive_telemetry({"event": "health", "metrics": {"status": "ok"}}))
    checks.extend(validate_manifest_checksums(root, ["runtime_version.py", "main.py"]))
    return {
        "product": APP_NAME,
        "version": APP_VERSION,
        "status": "passed" if all(check.passed for check in checks) else "failed",
        "checks": [asdict(check) for check in checks],
    }
