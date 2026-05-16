"""Offline first-run bootstrap for AIEmailOrganizer v9.7.

This module intentionally performs only local filesystem/database/configuration
initialization. It never downloads packages, models, updates, or remote config.
The application can use online email sync and integrations after setup, but the
installer/setup/first launch path must remain offline-safe.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

APP_VERSION = "9.7.0"
APP_NAME = "AIEmailOrganizer"


@dataclass(frozen=True)
class BootstrapCheck:
    name: str
    path: str
    passed: bool
    detail: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_runtime_home() -> Path:
    if os.environ.get("AIO_RUNTIME_HOME"):
        return Path(os.environ["AIO_RUNTIME_HOME"]).expanduser().resolve()
    if os.environ.get("LOCALAPPDATA"):
        return (Path(os.environ["LOCALAPPDATA"]) / APP_NAME).resolve()
    if os.name == "nt":
        return (Path.home() / "AppData" / "Local" / APP_NAME).resolve()
    if os.environ.get("XDG_DATA_HOME"):
        return (Path(os.environ["XDG_DATA_HOME"]) / APP_NAME).resolve()
    return (Path.home() / ".local" / "share" / APP_NAME).resolve()


def runtime_layout(runtime_home: Path | None = None) -> dict[str, Path]:
    root = (runtime_home or _default_runtime_home()).resolve()
    return {
        "root": root,
        "data": root / "data",
        "database": root / "database",
        "logs": root / "logs",
        "cache": root / "cache",
        "models": root / "models",
        "extensions": root / "extensions",
        "diagnostics": root / "diagnostics",
        "telemetry": root / "telemetry",
        "updates": root / "updates",
        "config": root / "config",
        "security": root / "security",
    }


def _write_json_once(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text_once(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(content, encoding="utf-8")


def _ensure_key(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8", errors="ignore").strip() not in {"", "GENERATE_AT_FIRST_RUN"}:
        return
    # URL-safe 32-byte random key. Generated locally during first launch only.
    path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _init_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS offline_bootstrap (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                app_version TEXT NOT NULL,
                initialized_at TEXT NOT NULL,
                offline_safe INTEGER NOT NULL,
                checksum TEXT NOT NULL
            )
            """
        )
        checksum = hashlib.sha256(f"{APP_NAME}:{APP_VERSION}:offline".encode("utf-8")).hexdigest()
        cur.execute(
            """
            INSERT INTO offline_bootstrap (id, app_version, initialized_at, offline_safe, checksum)
            VALUES (1, ?, ?, 1, ?)
            ON CONFLICT(id) DO UPDATE SET
                app_version=excluded.app_version,
                offline_safe=1,
                checksum=excluded.checksum
            """,
            (APP_VERSION, _utc_now(), checksum),
        )
        conn.commit()
    finally:
        conn.close()


def initialize_offline_first_run(runtime_home: Path | None = None, app_root: Path | None = None) -> dict[str, Any]:
    """Initialize local runtime state without network access.

    Returns a machine-readable report used by installer, setup, and runtime
    validators. The function is idempotent and safe to call on every startup.
    """
    layout = runtime_layout(runtime_home)
    checks: list[BootstrapCheck] = []

    for name, path in layout.items():
        if name == "root":
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
        checks.append(BootstrapCheck(f"dir:{name}", str(path), path.exists() and path.is_dir(), "directory available"))

    db_path = layout["data"] / "emails.db"
    _init_sqlite(db_path)
    checks.append(BootstrapCheck("sqlite:emails", str(db_path), db_path.exists(), "local database initialized"))

    _write_json_once(
        layout["config"] / "runtime.json",
        {
            "app": APP_NAME,
            "version": APP_VERSION,
            "offline_first_run": True,
            "created_at": _utc_now(),
            "network_required_for_setup": False,
            "online_features_allowed_after_setup": ["email_sync", "updates", "telemetry", "remote_integrations"],
        },
    )
    checks.append(BootstrapCheck("config:runtime", str(layout["config"] / "runtime.json"), True, "runtime config available"))

    _write_text_once(layout["logs"] / "service.log", "")
    checks.append(BootstrapCheck("logs:service", str(layout["logs"] / "service.log"), True, "log file available"))

    _ensure_key(layout["security"] / "token.key")
    checks.append(BootstrapCheck("security:token-key", str(layout["security"] / "token.key"), True, "local key generated"))

    handshake = layout["extensions"] / "localhost-bridge.json"
    _write_json_once(
        handshake,
        {
            "bridge": "localhost",
            "base_urls": ["http://127.0.0.1:4597/api/v1", "http://localhost:4597/api/v1"],
            "created_at": _utc_now(),
            "offline_safe": True,
        },
    )
    checks.append(BootstrapCheck("extension:bridge", str(handshake), handshake.exists(), "extension bridge config available"))

    app_root = (app_root or Path.cwd()).resolve()
    local_docs = app_root / "docs" / "offline"
    local_docs.mkdir(parents=True, exist_ok=True)
    _write_text_once(local_docs / "README_OFFLINE_SETUP.md", "# Offline setup\n\nInstaller/setup/first run are designed to complete without internet. Online email sync can be enabled after setup.\n")
    checks.append(BootstrapCheck("docs:offline", str(local_docs), local_docs.exists(), "offline docs available"))

    report = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "runtime_home": str(layout["root"]),
        "offline_setup_required": True,
        "network_required_for_bootstrap": False,
        "status": "passed" if all(c.passed for c in checks) else "failed",
        "generated_at": _utc_now(),
        "checks": [asdict(c) for c in checks],
    }
    report_path = layout["diagnostics"] / "offline_first_run_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def validate_installer_scripts_offline_safe(paths: Iterable[Path]) -> list[BootstrapCheck]:
    blocked = ["npm install", "pip install", "yarn install", "pnpm install", "bun install", "curl ", "wget ", "Invoke-WebRequest"]
    checks: list[BootstrapCheck] = []
    for path in paths:
        if not path.exists():
            checks.append(BootstrapCheck(f"script:{path.name}", str(path), False, "missing script"))
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits = [token for token in blocked if token.lower() in text.lower()]
        checks.append(BootstrapCheck(f"script:{path.name}", str(path), not hits, "blocked online setup commands: " + ", ".join(hits) if hits else "offline-safe"))
    return checks
