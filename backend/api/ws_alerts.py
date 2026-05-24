"""
Real-Time Threat Alert WebSocket
==================================
Provides a WebSocket endpoint that pushes live threat notifications to
connected clients (browser dashboard, desktop app, extensions).

Endpoint:  GET /api/v1/ws/alerts

Message format (server → client):
{
  "type": "threat_alert" | "scam_detected" | "lookalike_detected" |
          "heartbeat" | "connection_ack" | "stats_update",
  "severity": "low" | "medium" | "high" | "critical",
  "payload": { ... event-specific data ... },
  "timestamp": "<ISO-8601>"
}

Client → Server:
{
  "type": "subscribe" | "ping" | "set_filter",
  "filter": { "min_severity": "high", ... }
}
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from backend.auth.local_auth import require_local_auth_or_localhost

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["websocket-alerts"], dependencies=[Depends(require_local_auth_or_localhost)])


# ---------------------------------------------------------------------------
# Alert severity ordering
# ---------------------------------------------------------------------------

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _severity_from_score(score: int) -> str:
    if score <= 20:
        return "low"
    if score <= 55:
        return "medium"
    if score <= 80:
        return "high"
    return "critical"


# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------

class ThreatAlertManager:
    """
    Manages all active WebSocket connections and broadcasts threat events.
    Thread-safe for use with asyncio.
    """

    def __init__(self) -> None:
        # session_id → WebSocket
        self._connections: Dict[str, WebSocket] = {}
        # session_id → filter config
        self._filters: Dict[str, Dict] = {}
        # Queue of pending alerts to broadcast
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._broadcast_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        logger.info("ThreatAlertManager started")

    async def stop(self) -> None:
        self._running = False
        if self._broadcast_task:
            self._broadcast_task.cancel()

    async def connect(self, websocket: WebSocket) -> str:
        await websocket.accept()
        session_id = str(uuid.uuid4())
        self._connections[session_id] = websocket
        self._filters[session_id] = {"min_severity": "low"}

        # Send connection acknowledgement
        await self._send_to(session_id, {
            "type": "connection_ack",
            "severity": "low",
            "payload": {
                "session_id": session_id,
                "message": "Connected to INTEMO Threat Alert Stream",
                "active_connections": len(self._connections),
            },
            "timestamp": _now_iso(),
        })
        logger.info("WS alert connection: %s (total: %d)", session_id, len(self._connections))
        return session_id

    async def disconnect(self, session_id: str) -> None:
        self._connections.pop(session_id, None)
        self._filters.pop(session_id, None)
        logger.info("WS alert disconnected: %s (remaining: %d)", session_id, len(self._connections))

    async def handle_client_message(self, session_id: str, raw: str) -> None:
        try:
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await self._send_to(session_id, {
                    "type": "heartbeat",
                    "severity": "low",
                    "payload": {"pong": True},
                    "timestamp": _now_iso(),
                })

            elif msg_type == "set_filter":
                f = msg.get("filter", {})
                if "min_severity" in f and f["min_severity"] in _SEVERITY_ORDER:
                    self._filters[session_id]["min_severity"] = f["min_severity"]
                await self._send_to(session_id, {
                    "type": "filter_ack",
                    "severity": "low",
                    "payload": {"filter": self._filters[session_id]},
                    "timestamp": _now_iso(),
                })

        except Exception as exc:
            logger.debug("WS message parse error from %s: %s", session_id, exc)

    async def broadcast(self, event: Dict[str, Any]) -> None:
        """Enqueue an event for broadcast to all matching subscribers."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Alert queue full — dropping event")

    async def _broadcast_loop(self) -> None:
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=30.0)
                await self._dispatch(event)
            except asyncio.TimeoutError:
                # Send heartbeat to keep connections alive
                await self._heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Broadcast loop error: %s", exc)

    async def _dispatch(self, event: Dict[str, Any]) -> None:
        event_severity = event.get("severity", "low")
        event_level = _SEVERITY_ORDER.get(event_severity, 0)
        dead_sessions: Set[str] = set()

        for session_id, ws in list(self._connections.items()):
            f = self._filters.get(session_id, {})
            min_level = _SEVERITY_ORDER.get(f.get("min_severity", "low"), 0)
            if event_level >= min_level:
                try:
                    await ws.send_json(event)
                except Exception:
                    dead_sessions.add(session_id)

        for sid in dead_sessions:
            await self.disconnect(sid)

    async def _heartbeat(self) -> None:
        if not self._connections:
            return
        msg = {
            "type": "heartbeat",
            "severity": "low",
            "payload": {
                "active_connections": len(self._connections),
                "server_time": _now_iso(),
            },
            "timestamp": _now_iso(),
        }
        dead: Set[str] = set()
        for sid, ws in list(self._connections.items()):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(sid)
        for sid in dead:
            await self.disconnect(sid)

    async def _send_to(self, session_id: str, event: Dict) -> None:
        ws = self._connections.get(session_id)
        if ws:
            try:
                await ws.send_json(event)
            except Exception as exc:
                logger.debug("Send to %s failed: %s", session_id, exc)
                await self.disconnect(session_id)

    @property
    def connected_count(self) -> int:
        return len(self._connections)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ---------------------------------------------------------------------------
# Module-level singleton — shared across the app
# ---------------------------------------------------------------------------

alert_manager = ThreatAlertManager()


# ---------------------------------------------------------------------------
# Public alert emission functions (called by classifier / API routes)
# ---------------------------------------------------------------------------

async def emit_scam_detected(
    email_id: str,
    sender_email: str,
    subject: str,
    confidence: float,
    reasons: list,
    category: str = "Scam",
) -> None:
    score = int(confidence * 100)
    severity = _severity_from_score(score)
    payload = {
        "email_id": email_id,
        "sender_email": sender_email,
        "subject": subject,
        "category": category,
        "confidence": confidence,
        "confidence_score": score,
        "reasons": reasons,
    }
    await alert_manager.broadcast({
        "type": "scam_detected",
        "severity": severity,
        "payload": payload,
        "timestamp": _now_iso(),
    })
    try:
        from backend.api.event_bus import emit as _emit
        asyncio.create_task(_emit(
            "threat.detected",
            source="scam_classifier",
            payload=payload,
            severity=severity,
        ))
    except Exception:
        pass


async def emit_lookalike_detected(
    detected_domain: str,
    impersonated_brand: str,
    confidence_score: int,
    threat_type: str,
    reasons: list,
    sender_email: str = "",
    subject: str = "",
) -> None:
    severity = _severity_from_score(confidence_score)
    payload = {
        "detected_domain": detected_domain,
        "impersonated_brand": impersonated_brand,
        "confidence_score": confidence_score,
        "threat_type": threat_type,
        "reasons": reasons,
        "sender_email": sender_email,
        "subject": subject,
        "warning": (
            f"This email appears to impersonate {impersonated_brand} "
            f"using a deceptive domain variation: '{detected_domain}'"
        ),
    }
    await alert_manager.broadcast({
        "type": "lookalike_detected",
        "severity": severity,
        "payload": payload,
        "timestamp": _now_iso(),
    })
    try:
        from backend.api.event_bus import emit as _emit
        asyncio.create_task(_emit(
            "threat.detected",
            source="lookalike_detector",
            payload=payload,
            severity=severity,
        ))
    except Exception:
        pass


async def emit_stats_update(stats: Dict[str, Any]) -> None:
    await alert_manager.broadcast({
        "type": "stats_update",
        "severity": "low",
        "payload": stats,
        "timestamp": _now_iso(),
    })


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/alerts")
async def websocket_threat_alerts(websocket: WebSocket) -> None:
    """
    WebSocket endpoint for real-time threat alerts.
    Connect from the browser:
        const ws = new WebSocket('ws://localhost:4597/api/v1/ws/alerts');
    """
    # Ensure the broadcast loop is running
    if not alert_manager._running:
        await alert_manager.start()

    session_id = await alert_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            await alert_manager.handle_client_message(session_id, raw)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WS session %s error: %s", session_id, exc)
    finally:
        await alert_manager.disconnect(session_id)


# ---------------------------------------------------------------------------
# REST endpoint to check live connection status
# ---------------------------------------------------------------------------

@router.get("/alerts/status")
async def ws_alert_status() -> Dict:
    return {
        "ok": True,
        "active_connections": alert_manager.connected_count,
        "queue_size": alert_manager._queue.qsize(),
        "running": alert_manager._running,
    }
