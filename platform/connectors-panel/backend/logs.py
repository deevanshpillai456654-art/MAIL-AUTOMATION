"""
Logs router — connector log management and real-time streaming.
Prefix: /logs
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from .db import get_panel_db
from .models import APIResponse, ConnectorLog, LogLevel
from ..shared.utils import utc_now_str

router = APIRouter(prefix="/logs", tags=["logs"])

# In-memory WebSocket log subscribers: {subscription_id: WebSocket}
_log_subscribers: dict[str, WebSocket] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_log(row: dict[str, Any]) -> ConnectorLog:
    meta_raw = row.get("metadata_json", "{}")
    if isinstance(meta_raw, str):
        try:
            meta = json.loads(meta_raw)
        except Exception:
            meta = {}
    else:
        meta = meta_raw or {}

    return ConnectorLog(
        log_id=row["id"],
        connector_id=row["connector_id"],
        tenant_id=row["tenant_id"],
        level=LogLevel(row["level"]),
        message=row["message"],
        metadata=meta,
        timestamp=datetime.fromisoformat(row["timestamp"]),
    )


async def _broadcast_log(log: ConnectorLog) -> None:
    """Broadcast a new log entry to all WebSocket subscribers."""
    if not _log_subscribers:
        return
    message = json.dumps({
        "log_id": log.log_id,
        "connector_id": log.connector_id,
        "tenant_id": log.tenant_id,
        "level": log.level.value,
        "message": log.message,
        "metadata": log.metadata,
        "timestamp": log.timestamp.isoformat(),
    })
    dead: list[str] = []
    for sub_id, ws in list(_log_subscribers.items()):
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(sub_id)
    for sub_id in dead:
        _log_subscribers.pop(sub_id, None)


# ---------------------------------------------------------------------------
# Public helper for other modules
# ---------------------------------------------------------------------------

def write_log(
    connector_id: str,
    tenant_id: str,
    level: str,
    message: str,
    metadata: Optional[dict] = None,
) -> str:
    """Write a log entry to the database. Returns the log_id."""
    db = get_panel_db()
    log_id = f"log_{uuid.uuid4().hex}"
    now = utc_now_str()
    db.execute(
        """
        INSERT INTO connector_logs (id, connector_id, tenant_id, level, message, metadata_json, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (log_id, connector_id, tenant_id, level.upper(), message, json.dumps(metadata or {}), now),
    )
    return log_id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ConnectorLog], summary="List connector logs with filtering")
async def list_logs(
    tenant_id: str = Query(...),
    connector_id: Optional[str] = Query(None),
    level: Optional[str] = Query(None, description="INFO, WARN, ERROR, DEBUG"),
    since: Optional[datetime] = Query(None, description="Filter logs after this datetime (ISO 8601)"),
    until: Optional[datetime] = Query(None, description="Filter logs before this datetime (ISO 8601)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    db = get_panel_db()
    sql = "SELECT * FROM connector_logs WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]

    if connector_id:
        sql += " AND connector_id = ?"
        params.append(connector_id)
    if level:
        sql += " AND level = ?"
        params.append(level.upper())
    if since:
        sql += " AND timestamp >= ?"
        params.append(since.isoformat())
    if until:
        sql += " AND timestamp <= ?"
        params.append(until.isoformat())

    sql += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.fetch_all(sql, params)
    return [_row_to_log(r) for r in rows]


@router.get("/summary", summary="Get log summary by level and connector")
async def logs_summary(tenant_id: str = Query(...)):
    db = get_panel_db()

    # Count by level
    level_rows = db.fetch_all(
        "SELECT level, COUNT(*) AS count FROM connector_logs WHERE tenant_id = ? GROUP BY level",
        (tenant_id,),
    )
    by_level = {r["level"]: r["count"] for r in level_rows}

    # Count by connector
    connector_rows = db.fetch_all(
        """
        SELECT connector_id, level, COUNT(*) AS count
        FROM connector_logs WHERE tenant_id = ?
        GROUP BY connector_id, level
        """,
        (tenant_id,),
    )
    by_connector: dict[str, dict[str, int]] = {}
    for r in connector_rows:
        cid = r["connector_id"]
        if cid not in by_connector:
            by_connector[cid] = {}
        by_connector[cid][r["level"]] = r["count"]

    return {
        "tenant_id": tenant_id,
        "by_level": by_level,
        "by_connector": by_connector,
    }


@router.get("/{log_id}", response_model=ConnectorLog, summary="Get specific log entry")
async def get_log(log_id: str):
    db = get_panel_db()
    row = db.fetch_one("SELECT * FROM connector_logs WHERE id = ?", (log_id,))
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Log entry '{log_id}' not found")
    return _row_to_log(row)


@router.delete("", response_model=APIResponse, summary="Clear logs for tenant")
async def clear_logs(
    tenant_id: str = Query(...),
    connector_id: Optional[str] = Query(None),
    before: Optional[datetime] = Query(None, description="Delete logs before this datetime"),
):
    db = get_panel_db()
    sql = "DELETE FROM connector_logs WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]

    if connector_id:
        sql += " AND connector_id = ?"
        params.append(connector_id)
    if before:
        sql += " AND timestamp < ?"
        params.append(before.isoformat())

    cursor = db.execute(sql, params)
    return APIResponse(message=f"Deleted {cursor.rowcount} log entries")


@router.websocket("/stream")
async def stream_logs(websocket: WebSocket, tenant_id: Optional[str] = Query(None)):
    """
    WebSocket endpoint for real-time log streaming.

    Connect and receive JSON log entries as they are written.
    Optionally filter by tenant_id query param.
    """
    await websocket.accept()
    sub_id = str(uuid.uuid4())
    _log_subscribers[sub_id] = websocket

    try:
        await websocket.send_json({
            "type": "connected",
            "subscription_id": sub_id,
            "message": "Connected to log stream",
        })

        # Keep the connection alive; the client can send a ping or just hold
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat"})
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        _log_subscribers.pop(sub_id, None)
