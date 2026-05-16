"""Security validation and red-team support endpoints.

These endpoints expose sanitized policy/status information and recent audit
findings. They intentionally do not expose secrets, tokens, request bodies, or
provider credentials.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Query

from backend import config
from backend.security.audit import recent_security_events
from backend.security.request_signing import RequestSigner

router = APIRouter(prefix="/security", tags=["security"])


def _enabled(value: str) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def _installer_firewall_task_available() -> bool:
    installer = Path(__file__).resolve().parents[2] / "scripts" / "installer.iss"
    try:
        text = installer.read_text(encoding="utf-8")
    except OSError:
        return False
    return "INTEMO Local Dashboard" in text and "advfirewall firewall add rule" in text


def local_runtime_hardening_status() -> Dict[str, Any]:
    bind_host = str(getattr(config, "API_HOST", "127.0.0.1") or "127.0.0.1")
    port = int(getattr(config, "API_PORT", 4597) or 4597)
    allow_external = _enabled(os.environ.get("ALLOW_EXTERNAL_BIND", ""))
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    local_only = bind_host in local_hosts and not allow_external
    windows = platform.system().lower() == "windows"
    firewall_confirmed = _enabled(os.environ.get("INTEMO_FIREWALL_RULE_CONFIRMED", ""))
    installer_task = _installer_firewall_task_available()
    setup_command = (
        f'netsh advfirewall firewall add rule name="INTEMO Local Dashboard" '
        f"dir=in action=allow protocol=TCP localport={port} enable=yes profile=any"
    )
    firewall_state = (
        "confirmed" if firewall_confirmed
        else "setup_available" if installer_task
        else "not_required" if not windows
        else "manual_review"
    )
    firewall_ready = firewall_state in {"confirmed", "setup_available", "not_required"}
    return {
        "status": "passed" if local_only and firewall_ready else "review_required",
        "local_only": {
            "passed": local_only,
            "bind_host": bind_host,
            "allow_external_bind": allow_external,
            "remediation": "Bind the desktop runtime to 127.0.0.1 and unset ALLOW_EXTERNAL_BIND.",
        },
        "firewall": {
            "status": firewall_state,
            "platform": platform.system() or "unknown",
            "port": port,
            "installer_task_available": installer_task,
            "confirmed": firewall_confirmed,
            "setup_command": setup_command,
            "remediation": "Use the installer firewall task or run the setup command from an elevated Windows terminal.",
        },
        "checks": [
            {"name": "Loopback bind", "passed": local_only, "detail": f"API_HOST={bind_host}"},
            {"name": "External bind disabled", "passed": not allow_external, "detail": f"ALLOW_EXTERNAL_BIND={allow_external}"},
            {"name": "Windows Firewall setup flow", "passed": firewall_ready, "detail": firewall_state},
        ],
    }


@router.get("/status")
async def security_status() -> Dict[str, Any]:
    env = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "local")).lower()
    return {
        "status": "hardened",
        "environment": env,
        "request_signing": {
            "supported": True,
            "enforced": _enabled(os.environ.get("REQUIRE_REQUEST_SIGNATURES", "")),
            "secret_configured": bool(os.environ.get("REQUEST_SIGNING_SECRET", "")),
            "headers": ["X-AIEmail-Timestamp", "X-AIEmail-Nonce", "X-AIEmail-Signature"],
        },
        "redaction": {"enabled": True, "telemetry_redacted": True, "audit_redacted": True},
        "ssrf_protection": {"enabled": True, "private_ip_blocking": not _enabled(os.environ.get("ALLOW_PRIVATE_WEBHOOKS", ""))},
        "frontend_authority": "none",
        "provider_secret_storage": "encrypted_backend_only",
        "local_runtime": local_runtime_hardening_status(),
    }


@router.get("/local-runtime")
async def security_local_runtime() -> Dict[str, Any]:
    return local_runtime_hardening_status()


@router.get("/audit/recent")
async def recent_audit_events(limit: int = Query(default=50, ge=1, le=500)) -> Dict[str, Any]:
    events = recent_security_events(limit)
    return {"events": events, "count": len(events)}


@router.get("/attack-surface")
async def attack_surface() -> Dict[str, List[str]]:
    return {
        "backend": [
            "REST API /api and /api/v1",
            "OAuth callback handlers",
            "mailbox sync orchestration",
            "webhook outbound delivery",
            "frontend telemetry ingestion",
            "production readiness and metrics endpoints",
        ],
        "frontend": ["served dashboard", "Gmail extension", "Outlook add-in", "Electron wrapper"],
        "realtime": ["websocket client/server", "SSE event stream", "replay/ACK governance"],
        "infrastructure": ["Docker", "Kubernetes manifests", "PostgreSQL", "Redis", "Prometheus/Grafana"],
        "controls": [
            "CSP/security headers",
            "request size limits",
            "origin validation",
            "HMAC request signing support",
            "SSRF-blocked webhooks",
            "redacted telemetry/audit logging",
        ],
    }


@router.get("/request-signing/example")
async def request_signing_example() -> Dict[str, Any]:
    body = b'{"example":true}'
    return {
        "canonical_format": "METHOD\\nPATH\\nUNIX_TIMESTAMP\\nNONCE\\nSHA256_BODY_HEX",
        "sample_body_sha256": RequestSigner.body_hash(body),
        "headers": {
            "X-AIEmail-Timestamp": "<unix seconds>",
            "X-AIEmail-Nonce": "<unique random nonce>",
            "X-AIEmail-Signature": "hex(hmac_sha256(secret, canonical_format))",
        },
    }


__all__ = ["router", "local_runtime_hardening_status"]
