"""Frontend runtime telemetry and client policy endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from backend.core.runtime_control import get_runtime_control
from backend.security.redaction import redact

router = APIRouter(prefix="/frontend", tags=["frontend-runtime"])

_MAX_EVENTS = 100
_TELEMETRY_BUFFER: List[Dict[str, Any]] = []


class FrontendTelemetryEvent(BaseModel):
    id: str = Field(default="", max_length=120)
    type: str = Field(..., max_length=120)
    severity: Literal["debug", "info", "warning", "error", "critical"] = "info"
    timestamp: Optional[str] = Field(default=None, max_length=80)
    client_id: Optional[str] = Field(default=None, max_length=160)
    path: Optional[str] = Field(default=None, max_length=300)
    payload: Dict[str, Any] = Field(default_factory=dict)


class FrontendTelemetryPayload(BaseModel):
    client_id: str = Field(default="anonymous", max_length=160)
    events: List[FrontendTelemetryEvent] = Field(default_factory=list, max_length=50)


@router.post("/telemetry")
async def capture_frontend_telemetry(payload: FrontendTelemetryPayload, request: Request):
    request_id = request.headers.get("x-frontend-request-id", "")[:120]
    accepted = 0
    now = datetime.now(timezone.utc).isoformat()
    for event in payload.events[:50]:
        item = redact(event.model_dump())
        item["received_at"] = now
        item["request_id"] = request_id
        item["remote"] = request.client.host if request.client else "unknown"
        _TELEMETRY_BUFFER.append(item)
        accepted += 1
    if len(_TELEMETRY_BUFFER) > _MAX_EVENTS:
        del _TELEMETRY_BUFFER[: len(_TELEMETRY_BUFFER) - _MAX_EVENTS]
    return {"status": "accepted", "accepted": accepted, "stored": len(_TELEMETRY_BUFFER)}


@router.get("/telemetry/recent")
async def get_recent_frontend_telemetry(limit: int = 25):
    limit = max(1, min(limit, _MAX_EVENTS))
    return {"events": _TELEMETRY_BUFFER[-limit:], "count": len(_TELEMETRY_BUFFER)}


@router.get("/runtime-policy")
async def get_frontend_runtime_policy():
    runtime = get_runtime_control()
    return {
        "authority": "backend",
        "runtime": runtime.snapshot(),
        "plaintext_tokens_allowed": False,
        "provider_passwords_allowed": False,
        "mailbox_authority_in_frontend": False,
        "replay_dedupe_required": True,
        "websocket_ack_required": True,
        "account_scoped_rendering_required": True,
        "allowed_local_origins": ["http://127.0.0.1:4597", "http://localhost:4597"],
    }


@router.get("/clients/runtime-policy")
async def get_client_runtime_policy():
    runtime = get_runtime_control()
    frontend = runtime.frontend_flags()
    return {
        "zero_trust": True,
        "client_authority": "render_only",
        "runtime_profile": runtime.profile,
        "ai_mode": runtime.ai_mode,
        "rendering_budget": {
            "minimal_animations": frontend["minimal_animations"],
            "deferred_rendering": frontend["deferred_rendering"],
            "virtualize_lists": frontend["virtualize_lists"],
            "max_visible_rows": 100 if runtime.low_resource else 250 if runtime.profile == "lite" else 500,
            "poll_interval_seconds": runtime.limits["poll_interval_seconds"],
        },
        "plaintext_tokens_allowed": False,
        "provider_passwords_allowed": False,
        "mailbox_authority_on_client": False,
        "signed_messages_required": True,
        "replay_dedupe_required": True,
        "account_scoped_rendering_required": True,
        "supported_clients": [
            "chrome", "edge", "firefox", "brave", "opera", "safari",
            "electron", "pwa", "outlook_addin", "android", "ios"
        ],
    }

@router.get("/clients/platforms")
async def get_client_platforms():
    return {
        "browser_extensions": ["chrome", "edge", "firefox", "brave", "opera", "safari"],
        "desktop": ["electron", "pwa"],
        "mobile_foundations": ["android", "ios"],
        "office": ["outlook_addin"],
        "native_build_evidence_required": ["android", "ios", "safari", "electron_signed_updates"],
    }
