"""
Events router — event management, publishing, and real-time subscriptions.
Prefix: /events

Also exposes the EventBus class for internal use.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from .db import get_panel_db
from .models import (
    APIResponse,
    EventPublishRequest,
    EventRecord,
)
from ..shared.constants import SUPPORTED_EVENT_TYPES
from ..shared.event_bus import EventBus, get_event_bus
from ..shared.utils import generate_event_id, utc_now_str

router = APIRouter(prefix="/events", tags=["events"])

# In-memory WebSocket subscribers: {subscription_id: (WebSocket, set[event_types])}
_event_ws_subscribers: dict[str, tuple[WebSocket, Optional[set[str]]]] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_event(row: dict[str, Any]) -> EventRecord:
    payload_raw = row.get("payload_json", "{}")
    if isinstance(payload_raw, str):
        try:
            payload = json.loads(payload_raw)
        except Exception:
            payload = {}
    else:
        payload = payload_raw or {}

    processed_raw = row.get("processed_by_json", "[]")
    if isinstance(processed_raw, str):
        try:
            processed_by = json.loads(processed_raw)
        except Exception:
            processed_by = []
    else:
        processed_by = processed_raw or []

    return EventRecord(
        event_id=row["id"],
        event_type=row["event_type"],
        source_connector_id=row["source_connector_id"],
        tenant_id=row["tenant_id"],
        payload=payload,
        published_at=datetime.fromisoformat(row["published_at"]),
        processed_by=processed_by,
    )


async def _broadcast_event(event: EventRecord) -> None:
    """Broadcast an event to WebSocket subscribers."""
    if not _event_ws_subscribers:
        return
    message = json.dumps({
        "event_id": event.event_id,
        "event_type": event.event_type,
        "source_connector_id": event.source_connector_id,
        "tenant_id": event.tenant_id,
        "payload": event.payload,
        "published_at": event.published_at.isoformat(),
    })
    dead: list[str] = []
    for sub_id, (ws, event_filter) in list(_event_ws_subscribers.items()):
        if event_filter and event.event_type not in event_filter:
            continue
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(sub_id)
    for sub_id in dead:
        _event_ws_subscribers.pop(sub_id, None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[EventRecord], summary="List events with filtering")
async def list_events(
    tenant_id: str = Query(...),
    event_type: Optional[str] = Query(None),
    source_connector: Optional[str] = Query(None),
    since: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    db = get_panel_db()
    sql = "SELECT * FROM events WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]

    if event_type:
        sql += " AND event_type = ?"
        params.append(event_type)
    if source_connector:
        sql += " AND source_connector_id = ?"
        params.append(source_connector)
    if since:
        sql += " AND published_at >= ?"
        params.append(since.isoformat())

    sql += " ORDER BY published_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.fetch_all(sql, params)
    return [_row_to_event(r) for r in rows]


@router.get("/types", summary="List available event types")
async def list_event_types():
    """Return all supported event types, grouped by category."""
    grouped: dict[str, list[str]] = {}
    for et in SUPPORTED_EVENT_TYPES:
        prefix = et.split(".")[0]
        grouped.setdefault(prefix, []).append(et)
    return {
        "event_types": SUPPORTED_EVENT_TYPES,
        "by_category": grouped,
        "total": len(SUPPORTED_EVENT_TYPES),
    }


@router.post("/publish", response_model=EventRecord, status_code=status.HTTP_201_CREATED, summary="Publish an event (admin)")
async def publish_event(body: EventPublishRequest):
    bus = get_event_bus()
    event_id = await bus.publish(
        body.event_type,
        body.source_connector_id,
        body.tenant_id,
        body.payload,
    )

    # Retrieve persisted event
    db = get_panel_db()
    row = db.fetch_one("SELECT * FROM events WHERE id = ?", (event_id,))
    if not row:
        # Build from request data if persistence failed
        now = utc_now_str()
        return EventRecord(
            event_id=event_id,
            event_type=body.event_type,
            source_connector_id=body.source_connector_id,
            tenant_id=body.tenant_id,
            payload=body.payload,
            published_at=datetime.fromisoformat(now),
            processed_by=[],
        )

    event = _row_to_event(row)
    await _broadcast_event(event)
    return event


@router.get("/subscriptions", summary="List event subscriptions per connector")
async def list_subscriptions():
    bus = get_event_bus()
    stats = bus.get_stats()
    return {
        "subscriptions": stats["subscriptions"],
        "total_subscribers": stats["total_subscribers"],
        "event_type_subscriptions": stats["event_type_subscriptions"],
    }


@router.websocket("/subscribe")
async def subscribe_events(
    websocket: WebSocket,
    tenant_id: Optional[str] = Query(None),
    event_types: Optional[str] = Query(None, description="Comma-separated list of event types to subscribe to"),
):
    """
    WebSocket endpoint for real-time event streaming.

    Connect and optionally filter by:
    - tenant_id query param
    - event_types comma-separated list (e.g. ?event_types=invoice.created,order.updated)

    Messages are JSON EventRecord objects.
    """
    await websocket.accept()
    sub_id = str(uuid.uuid4())

    filter_set: Optional[set[str]] = None
    if event_types:
        filter_set = {et.strip() for et in event_types.split(",") if et.strip()}

    _event_ws_subscribers[sub_id] = (websocket, filter_set)

    try:
        await websocket.send_json({
            "type": "subscribed",
            "subscription_id": sub_id,
            "tenant_id": tenant_id,
            "event_types": list(filter_set) if filter_set else "ALL",
        })

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
                else:
                    # Allow client to update their subscription filters
                    try:
                        msg = json.loads(data)
                        if msg.get("action") == "filter" and "event_types" in msg:
                            new_types = msg["event_types"]
                            if isinstance(new_types, list) and new_types:
                                filter_set = set(new_types)
                                _event_ws_subscribers[sub_id] = (websocket, filter_set)
                                await websocket.send_json({"type": "filter_updated", "event_types": list(filter_set)})
                    except Exception:
                        pass
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "heartbeat"})
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        _event_ws_subscribers.pop(sub_id, None)
