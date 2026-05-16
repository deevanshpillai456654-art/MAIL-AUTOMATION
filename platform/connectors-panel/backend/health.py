"""
Health router — connector and system health monitoring.
Prefix: /health
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from .models import (
    APIResponse,
    ConnectorHealth,
    ConnectorStatus,
)
from ..shared.utils import compute_health_score, utc_now_str

router = APIRouter(prefix="/health", tags=["health"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_health(connector_row: dict[str, Any], health_row: Optional[dict[str, Any]]) -> ConnectorHealth:
    checks: dict[str, Any] = {}
    latency = None
    quota_used = None
    quota_limit = None

    if health_row:
        checks_raw = health_row.get("checks_json", "{}")
        if isinstance(checks_raw, str):
            try:
                checks = json.loads(checks_raw)
            except Exception:
                checks = {}
        else:
            checks = checks_raw or {}
        latency = health_row.get("response_latency_ms")
        quota_used = health_row.get("api_quota_used")
        quota_limit = health_row.get("api_quota_limit")

    return ConnectorHealth(
        connector_id=connector_row["id"],
        tenant_id=connector_row["tenant_id"],
        status=ConnectorStatus(connector_row["status"]),
        last_heartbeat=datetime.fromisoformat(connector_row["last_heartbeat"]) if connector_row.get("last_heartbeat") else None,
        last_sync=datetime.fromisoformat(connector_row["last_sync"]) if connector_row.get("last_sync") else None,
        failure_count=connector_row.get("failure_count", 0),
        retry_count=connector_row.get("retry_count", 0),
        response_latency_ms=latency,
        api_quota_used=quota_used,
        api_quota_limit=quota_limit,
        checks=checks,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", summary="Overall system health")
async def overall_health():
    db = get_panel_db()

    # Count connectors by status
    status_rows = db.fetch_all(
        "SELECT status, COUNT(*) AS count FROM connectors WHERE is_active = 1 GROUP BY status",
        (),
    )
    by_status = {r["status"]: r["count"] for r in status_rows}
    total_connectors = sum(by_status.values())

    # Count jobs
    job_rows = db.fetch_one(
        """
        SELECT
            SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END)     AS queued,
            SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS processing,
            SUM(CASE WHEN status = 'dead' THEN 1 ELSE 0 END)       AS dead_letters,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)     AS failed
        FROM queue_jobs
        """,
        (),
    )

    # Determine overall system status — guard against NULL from SUM on empty table
    def _int(row, key):
        if not row:
            return 0
        v = row.get(key)
        return int(v) if v is not None else 0

    failed_count   = by_status.get("failed", 0)
    degraded_count = by_status.get("degraded", 0)
    dead_letters   = _int(job_rows, "dead_letters")

    if failed_count > 0 or dead_letters > 10:
        sys_status = "degraded"
    elif degraded_count > 0:
        sys_status = "warning"
    else:
        sys_status = "healthy"

    return {
        "status": sys_status,
        "timestamp": utc_now_str(),
        "connectors": {
            "total": total_connectors,
            "by_status": by_status,
        },
        "queues": {
            "queued":       _int(job_rows, "queued"),
            "processing":   _int(job_rows, "processing"),
            "dead_letters": dead_letters,
            "failed":       _int(job_rows, "failed"),
        },
        "version": "1.0.0",
    }


@router.get("/connectors", response_model=list[ConnectorHealth], summary="Health of all installed connectors")
async def all_connectors_health(tenant_id: str = Query(...)):
    db = get_panel_db()
    connectors = db.fetch_all(
        "SELECT * FROM connectors WHERE tenant_id = ? AND is_active = 1",
        (tenant_id,),
    )
    result: list[ConnectorHealth] = []
    for c in connectors:
        health_row = db.fetch_one(
            "SELECT * FROM connector_health WHERE connector_id = ? AND tenant_id = ?",
            (c["id"], tenant_id),
        )
        result.append(_row_to_health(c, health_row))
    return result


@router.get("/connectors/{connector_id}", response_model=ConnectorHealth, summary="Detailed health for one connector")
async def connector_health(connector_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    connector = db.fetch_one(
        "SELECT * FROM connectors WHERE id = ? AND tenant_id = ?",
        (connector_id, tenant_id),
    )
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Connector '{connector_id}' not found")

    health_row = db.fetch_one(
        "SELECT * FROM connector_health WHERE connector_id = ? AND tenant_id = ?",
        (connector_id, tenant_id),
    )
    return _row_to_health(connector, health_row)


@router.post(
    "/connectors/{connector_id}/heartbeat",
    response_model=APIResponse,
    summary="Update connector heartbeat",
)
async def update_heartbeat(
    connector_id: str,
    tenant_id: str = Query(...),
    latency_ms: Optional[float] = Query(None),
    quota_used: Optional[int] = Query(None),
    quota_limit: Optional[int] = Query(None),
    checks: Optional[str] = Query(None, description="JSON string of health check results"),
):
    db = get_panel_db()
    connector = db.fetch_one(
        "SELECT * FROM connectors WHERE id = ? AND tenant_id = ?",
        (connector_id, tenant_id),
    )
    if not connector:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Connector '{connector_id}' not found")

    now = utc_now_str()

    # Update last_heartbeat on connector
    db.execute(
        "UPDATE connectors SET last_heartbeat = ? WHERE id = ? AND tenant_id = ?",
        (now, connector_id, tenant_id),
    )

    # Upsert health record
    checks_json = checks or "{}"
    import uuid
    health_id = str(uuid.uuid4())
    db.execute(
        """
        INSERT INTO connector_health
            (id, connector_id, tenant_id, checks_json, response_latency_ms,
             api_quota_used, api_quota_limit, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(connector_id, tenant_id) DO UPDATE SET
            checks_json         = excluded.checks_json,
            response_latency_ms = excluded.response_latency_ms,
            api_quota_used      = excluded.api_quota_used,
            api_quota_limit     = excluded.api_quota_limit,
            updated_at          = excluded.updated_at
        """,
        (health_id, connector_id, tenant_id, checks_json, latency_ms, quota_used, quota_limit, now),
    )

    # Recalculate health score
    last_hb_age: Optional[float] = None  # just updated, so 0 age
    score = compute_health_score(
        failure_count=connector.get("failure_count", 0),
        retry_count=connector.get("retry_count", 0),
        response_latency_ms=latency_ms,
        last_heartbeat_age_seconds=0.0,
    )
    db.execute(
        "UPDATE connectors SET health_score = ? WHERE id = ? AND tenant_id = ?",
        (score, connector_id, tenant_id),
    )

    return APIResponse(
        message="Heartbeat recorded",
        data={"connector_id": connector_id, "health_score": score, "timestamp": now},
    )


@router.get("/queues", summary="Queue system health")
async def queues_health():
    db = get_panel_db()
    row = db.fetch_one(
        """
        SELECT
            COUNT(*)                                                        AS total_jobs,
            SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END)             AS queued,
            SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END)         AS processing,
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)          AS completed,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)             AS failed,
            SUM(CASE WHEN status = 'dead' THEN 1 ELSE 0 END)               AS dead_letters,
            SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END)          AS cancelled
        FROM queue_jobs
        """,
        (),
    )

    dead_letters = row.get("dead_letters", 0) or 0
    failed = row.get("failed", 0) or 0
    queue_status = "healthy"
    if dead_letters > 20 or failed > 10:
        queue_status = "critical"
    elif dead_letters > 5 or failed > 3:
        queue_status = "degraded"

    return {
        "status": queue_status,
        "total_jobs": row.get("total_jobs", 0) or 0,
        "queued": row.get("queued", 0) or 0,
        "processing": row.get("processing", 0) or 0,
        "completed": row.get("completed", 0) or 0,
        "failed": failed,
        "dead_letters": dead_letters,
        "cancelled": row.get("cancelled", 0) or 0,
        "timestamp": utc_now_str(),
    }


@router.get("/plugins", summary="Plugin system health")
async def plugins_health():
    """
    Returns health status of the platform plugin system.
    Reads from platform/runtime if available, falls back to file discovery.
    """
    plugin_statuses: list[dict] = []

    # Try runtime registry
    try:
        import importlib
        registry_mod = importlib.import_module("platform.runtime.health")
        if hasattr(registry_mod, "get_plugin_health"):
            return registry_mod.get_plugin_health()
    except Exception:
        pass

    # Fallback: discover plugins from filesystem
    from pathlib import Path
    base_dirs = [
        Path(__file__).resolve().parent.parent.parent.parent / "plugins",
        Path(__file__).resolve().parent.parent / "plugins",
    ]

    for base_dir in base_dirs:
        if not base_dir.exists():
            continue
        for manifest_file in sorted(base_dir.glob("*/plugin.json")):
            try:
                import json as _json
                raw = _json.loads(manifest_file.read_text(encoding="utf-8"))
                plugin_statuses.append({
                    "plugin_id": raw.get("name", manifest_file.parent.name),
                    "enabled": raw.get("enabled", False),
                    "version": raw.get("version", "0.0.0"),
                    "status": "running" if raw.get("enabled") else "stopped",
                })
            except Exception:
                continue

    overall = "healthy" if all(p["enabled"] for p in plugin_statuses) else "warning"

    return {
        "status": overall,
        "total": len(plugin_statuses),
        "plugins": plugin_statuses,
        "timestamp": utc_now_str(),
    }
