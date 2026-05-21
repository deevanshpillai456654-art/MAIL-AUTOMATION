"""
Operational Event Bus
=====================
Persistent, replayable event bus — the connective tissue of the AI-native
operational platform.

Architecture:
  - SQLite WAL event store  (persistent, queryable, replayable)
  - Async pub/sub with in-process subscriber callbacks
  - WebSocket broadcast to live dashboard clients
  - Dead-letter queue for failed deliveries
  - Correlation ID propagation for distributed trace reconstruction
  - Event replay from any point in time

Event schema (server → client):
  {
    "id":             "<uuid>",
    "type":           "workflow.executed | email.classified | threat.detected | ...",
    "source":         "workflow_engine | threat_intel | agent.* | ...",
    "severity":       "low | medium | high | critical",
    "correlation_id": "<uuid>",
    "payload":        { ... event-specific data ... },
    "metadata":       { ... optional tags ... },
    "created_at":     "<ISO-8601>"
  }

Endpoints:
  POST /events/publish      — publish an operational event
  GET  /events/history      — query event history
  GET  /events/stats        — event bus statistics
  GET  /events/types        — registered event type catalogue
  POST /events/replay       — replay historical events to WS subscribers
  WS   /events/stream       — real-time WebSocket event stream
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Generator, List, Optional, Set

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth, request_has_valid_local_auth
from backend.config import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/events", tags=["event-bus"])

_DB_PATH = str(Path(DATA_DIR) / "event_bus.db")

# ── Event type catalogue ───────────────────────────────────────────────────────

EVENT_TYPES: Dict[str, str] = {
    # Workflow lifecycle
    "workflow.created":           "A workflow was created from a template or custom definition",
    "workflow.activated":         "A workflow was activated and will auto-trigger",
    "workflow.deactivated":       "A workflow was deactivated",
    "workflow.executed":          "A workflow execution completed (success or failure)",
    "workflow.step.completed":    "A single workflow step completed",
    "workflow.failed":            "A workflow execution failed after all retries",
    "workflow.recovered":         "A failed workflow auto-recovered via compensation",
    # Email operations
    "email.received":             "New email ingested into the platform",
    "email.classified":           "Email AI classification completed",
    "email.quarantined":          "Email quarantined by security workflow",
    "email.processed":            "Email fully processed by all active workflows",
    "email.forwarded":            "Email forwarded via automation rule",
    # Threat & security
    "threat.detected":            "Threat detected by intelligence engine",
    "threat.escalated":           "Threat escalated to security team",
    "threat.dismissed":           "Threat alert dismissed by operator",
    "threat.pattern_found":       "Repeated threat pattern detected from same source",
    # Agent operations
    "agent.started":              "Autonomous operational agent started",
    "agent.action":               "Agent performed an autonomous operational action",
    "agent.insight":              "Agent generated an operational intelligence insight",
    "agent.anomaly":              "Agent detected an operational anomaly",
    "agent.recovery":             "Agent initiated a self-healing recovery sequence",
    "agent.stopped":              "Operational agent stopped",
    # System health
    "system.health_check":        "Periodic system health check completed",
    "system.circuit_open":        "Circuit breaker opened — downstream is failing",
    "system.circuit_closed":      "Circuit breaker closed — downstream recovered",
    "system.degraded":            "A system component entered degraded state",
    "system.recovered":           "A degraded component recovered",
    "system.sla_breach":          "An SLA threshold was breached",
    # Intelligence events
    "intelligence.insight":       "Operational intelligence insight generated",
    "intelligence.anomaly":       "Intelligence engine detected an anomaly",
    "intelligence.prediction":    "Predictive analytics result generated",
    "intelligence.recommendation":"AI recommended an operational improvement",
    # Connector & OCR
    "connector.event":            "Connector emitted an operational event",
    "connector.health_changed":   "Connector health status changed",
    "ocr.completed":              "OCR scan completed and fields extracted",
}

_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


# ── DB bootstrap ───────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS operational_events (
            id             TEXT PRIMARY KEY,
            type           TEXT NOT NULL,
            source         TEXT NOT NULL,
            severity       TEXT DEFAULT 'low',
            tenant_id      TEXT DEFAULT 'default',
            correlation_id TEXT,
            payload        TEXT DEFAULT '{}',
            metadata       TEXT DEFAULT '{}',
            created_at     TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_oe_type     ON operational_events(type);
        CREATE INDEX IF NOT EXISTS idx_oe_created  ON operational_events(created_at);
        CREATE INDEX IF NOT EXISTS idx_oe_severity ON operational_events(severity);
        CREATE INDEX IF NOT EXISTS idx_oe_source   ON operational_events(source);
        CREATE TABLE IF NOT EXISTS dead_letter (
            id          TEXT PRIMARY KEY,
            event_id    TEXT NOT NULL,
            reason      TEXT,
            attempts    INTEGER DEFAULT 1,
            created_at  TEXT NOT NULL
        );
    """)
    con.commit()
    return con


@contextmanager
def _conn() -> Generator:
    con = _db()
    try:
        yield con
    finally:
        con.close()


# ── Core event bus ─────────────────────────────────────────────────────────────

class OperationalEventBus:
    """
    Persistent, replayable event bus.

    All events are written to SQLite first (durable), then fanned out to:
      1. In-process async subscriber callbacks (agents, intelligence engine)
      2. Live WebSocket dashboard clients (operational timeline)
    """

    def __init__(self) -> None:
        self._ws_connections: Dict[str, tuple[WebSocket, Dict]] = {}
        self._subscribers: Dict[str, List[Callable]] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=5000)
        self._dispatch_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("OperationalEventBus started")

    async def stop(self) -> None:
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()

    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Register an in-process callback. Use '*' to receive all events."""
        self._subscribers.setdefault(event_type, []).append(callback)

    async def publish(
        self,
        event_type: str,
        source: str,
        payload: Dict[str, Any],
        severity: str = "low",
        tenant_id: str = "default",
        correlation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist and broadcast an operational event. Returns the event ID."""
        if not self._running:
            await self.start()

        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        corr = correlation_id or str(uuid.uuid4())
        event: Dict[str, Any] = {
            "id":             event_id,
            "type":           event_type,
            "source":         source,
            "severity":       severity,
            "tenant_id":      tenant_id,
            "correlation_id": corr,
            "payload":        payload,
            "metadata":       metadata or {},
            "created_at":     now,
        }

        # Durable write first
        try:
            with _conn() as con:
                con.execute(
                    """INSERT INTO operational_events
                       (id, type, source, severity, tenant_id, correlation_id,
                        payload, metadata, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        event_id, event_type, source, severity, tenant_id, corr,
                        json.dumps(payload), json.dumps(metadata or {}), now,
                    ),
                )
                con.commit()
        except Exception as exc:
            logger.error("Event persist failed: %s", exc)

        # Fan-out asynchronously
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("Event bus queue full — dropping broadcast for %s", event_id)

        return event_id

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=25.0)
                await self._dispatch_event(event)
            except asyncio.TimeoutError:
                await self._ws_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Event bus dispatch error: %s", exc)

    async def _dispatch_event(self, event: Dict[str, Any]) -> None:
        # 1. In-process subscribers
        for pattern in (event["type"], "*"):
            for cb in list(self._subscribers.get(pattern, [])):
                try:
                    if asyncio.iscoroutinefunction(cb):
                        asyncio.create_task(cb(event))
                    else:
                        cb(event)
                except Exception as exc:
                    logger.debug("Subscriber callback error: %s", exc)

        # 2. WebSocket broadcast
        event_level = _SEVERITY_ORDER.get(event.get("severity", "low"), 0)
        dead: Set[str] = set()

        for sid, (ws, filt) in list(self._ws_connections.items()):
            min_level = _SEVERITY_ORDER.get(filt.get("min_severity", "low"), 0)
            allowed = filt.get("event_types", [])
            if allowed and event["type"] not in allowed:
                continue
            if event_level < min_level:
                continue
            try:
                await ws.send_json({"event": event})
            except Exception:
                dead.add(sid)

        for sid in dead:
            self._ws_connections.pop(sid, None)

    async def _ws_heartbeat(self) -> None:
        if not self._ws_connections:
            return
        msg = {"event": {"type": "heartbeat", "created_at": datetime.now(timezone.utc).isoformat()}}
        dead: Set[str] = set()
        for sid, (ws, _) in list(self._ws_connections.items()):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.add(sid)
        for sid in dead:
            self._ws_connections.pop(sid, None)

    # ── WebSocket connection management ────────────────────────────────────────

    async def ws_connect(self, websocket: WebSocket, filt: Dict) -> str:
        await websocket.accept()
        sid = str(uuid.uuid4())
        self._ws_connections[sid] = (websocket, filt)
        await websocket.send_json({
            "event": {
                "type":       "connection_ack",
                "source":     "event_bus",
                "session_id": sid,
                "message":    "Connected to INTEMO Operational Event Bus",
                "active_connections": len(self._ws_connections),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        })
        logger.info("Event stream WS connected: %s", sid)
        return sid

    async def ws_disconnect(self, sid: str) -> None:
        self._ws_connections.pop(sid, None)
        logger.info("Event stream WS disconnected: %s", sid)

    # ── History & replay ───────────────────────────────────────────────────────

    def get_history(
        self,
        limit: int = 100,
        event_types: Optional[List[str]] = None,
        severity: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses, params = [], []
        if event_types:
            placeholders = ",".join("?" * len(event_types))
            clauses.append(f"type IN ({placeholders})")
            params.extend(event_types)
        if severity:
            clauses.append("severity = ?")
            params.append(severity)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if since:
            clauses.append("created_at >= ?")
            params.append(since)
        if until:
            clauses.append("created_at <= ?")
            params.append(until)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(min(limit, 1000))

        with _conn() as con:
            rows = con.execute(
                f"SELECT * FROM operational_events {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            for k in ("payload", "metadata"):
                if isinstance(d.get(k), str):
                    try:
                        d[k] = json.loads(d[k])
                    except Exception:
                        pass
            result.append(d)
        return result

    def get_stats(self) -> Dict[str, Any]:
        with _conn() as con:
            total     = con.execute("SELECT COUNT(*) FROM operational_events").fetchone()[0]
            last_hour = con.execute(
                "SELECT COUNT(*) FROM operational_events WHERE created_at >= datetime('now', '-1 hour')"
            ).fetchone()[0]
            last_24h  = con.execute(
                "SELECT COUNT(*) FROM operational_events WHERE created_at >= datetime('now', '-24 hours')"
            ).fetchone()[0]
            by_type = {
                r[0]: r[1] for r in con.execute(
                    "SELECT type, COUNT(*) FROM operational_events GROUP BY type ORDER BY COUNT(*) DESC LIMIT 20"
                ).fetchall()
            }
            by_severity = {
                r[0]: r[1] for r in con.execute(
                    "SELECT severity, COUNT(*) FROM operational_events GROUP BY severity"
                ).fetchall()
            }
        return {
            "total_events":          total,
            "last_hour":             last_hour,
            "last_24h":              last_24h,
            "active_ws_connections": len(self._ws_connections),
            "queue_size":            self._queue.qsize(),
            "running":               self._running,
            "by_type":               by_type,
            "by_severity":           by_severity,
        }

    async def replay(
        self,
        since: str,
        event_types: Optional[List[str]] = None,
        until: Optional[str] = None,
    ) -> int:
        events = self.get_history(
            limit=1000, event_types=event_types, since=since, until=until
        )
        events.reverse()  # chronological replay
        for event in events:
            await self._dispatch_event(event)
        return len(events)


# ── Module singleton ───────────────────────────────────────────────────────────

_bus = OperationalEventBus()


def get_event_bus() -> OperationalEventBus:
    return _bus


async def emit(
    event_type: str,
    source: str,
    payload: Dict[str, Any],
    severity: str = "low",
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """Convenience function for all platform modules to emit events."""
    return await _bus.publish(
        event_type=event_type,
        source=source,
        payload=payload,
        severity=severity,
        correlation_id=correlation_id,
        metadata=metadata or {},
    )


def emit_sync(
    event_type: str,
    source: str,
    payload: Dict[str, Any],
    severity: str = "low",
) -> None:
    """
    Fire-and-forget event emission from synchronous code.
    Submits to the running asyncio event loop if one exists; silently drops otherwise.
    """
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    emit(event_type, source, payload, severity),
                    loop=loop,
                )
            )
    except Exception:
        pass


# ── Pydantic models ────────────────────────────────────────────────────────────

class PublishRequest(BaseModel):
    type:           str
    source:         str
    payload:        Dict[str, Any] = {}
    severity:       str = "low"
    correlation_id: Optional[str] = None
    metadata:       Dict[str, Any] = {}


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/publish", summary="Publish an operational event to the bus")
async def publish_event(body: PublishRequest, _auth=Depends(require_local_auth)):
    if body.type not in EVENT_TYPES and not body.type.startswith("custom."):
        pass  # allow unknown types but log them
    event_id = await emit(
        event_type=body.type,
        source=body.source,
        payload=body.payload,
        severity=body.severity,
        correlation_id=body.correlation_id,
        metadata=body.metadata,
    )
    return {"ok": True, "event_id": event_id}


@router.get("/history", summary="Query operational event history")
async def event_history(
    limit:    int            = Query(100, ge=1, le=1000),
    types:    Optional[str]  = Query(None, description="Comma-separated event types"),
    severity: Optional[str]  = Query(None),
    source:   Optional[str]  = Query(None),
    since:    Optional[str]  = Query(None, description="ISO-8601 lower bound"),
    until:    Optional[str]  = Query(None, description="ISO-8601 upper bound"),
    _auth=Depends(require_local_auth),
):
    event_types = [t.strip() for t in types.split(",")] if types else None
    events = _bus.get_history(
        limit=limit,
        event_types=event_types,
        severity=severity,
        source=source,
        since=since,
        until=until,
    )
    return {"events": events, "count": len(events)}


@router.get("/stats", summary="Event bus statistics and throughput")
async def event_stats(_auth=Depends(require_local_auth)):
    return _bus.get_stats()


@router.get("/types", summary="Registered event type catalogue")
async def event_type_catalogue(_auth=Depends(require_local_auth)):
    return {
        "types": [{"type": k, "description": v} for k, v in EVENT_TYPES.items()],
        "total": len(EVENT_TYPES),
    }


@router.post("/replay", summary="Replay historical events to live WebSocket subscribers")
async def replay_events(
    since:  str           = Query(..., description="ISO-8601 start of replay window"),
    until:  Optional[str] = Query(None),
    types:  Optional[str] = Query(None),
    _auth=Depends(require_local_auth),
):
    event_types = [t.strip() for t in types.split(",")] if types else None
    count = await _bus.replay(since, event_types=event_types, until=until)
    return {"ok": True, "replayed": count}


@router.websocket("/stream")
async def event_stream(websocket: WebSocket):
    """
    Real-time WebSocket operational event stream.

    Connect:
        const ws = new WebSocket('ws://localhost:4597/api/v1/events/stream');

    Optional query params:
        ?min_severity=high
        ?types=workflow.executed,threat.detected

    Client → server messages:
        {"type": "set_filter", "filter": {"min_severity": "high", "event_types": [...]}}
        {"type": "ping"}
    """
    # BaseHTTPMiddleware (LocalAPIAuthMiddleware) intercepts only "http" scope connections,
    # not "websocket" scope — auth must be enforced here before accepting the handshake.
    if not request_has_valid_local_auth(websocket):
        await websocket.close(code=4001)
        return

    if not _bus._running:
        await _bus.start()

    params = dict(websocket.query_params)
    filt: Dict[str, Any] = {}
    if "min_severity" in params:
        filt["min_severity"] = params["min_severity"]
    if "types" in params:
        filt["event_types"] = [t.strip() for t in params["types"].split(",")]

    sid = await _bus.ws_connect(websocket, filt)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "set_filter":
                    new_filt = msg.get("filter", {})
                    ws, _ = _bus._ws_connections.get(sid, (None, {}))
                    if ws:
                        _bus._ws_connections[sid] = (ws, new_filt)
                elif msg.get("type") == "ping":
                    await websocket.send_json({
                        "event": {
                            "type":       "pong",
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                    })
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Event stream WS %s error: %s", sid, exc)
    finally:
        await _bus.ws_disconnect(sid)
