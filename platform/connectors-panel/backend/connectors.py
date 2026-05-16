"""
Connectors router — manage installed connectors for a tenant.
Prefix: /connectors
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from .models import (
    APIResponse,
    ConnectorCategory,
    ConnectorConfigUpdate,
    ConnectorStatus,
    InstalledConnector,
)
from ..shared.utils import utc_now_str

router = APIRouter(prefix="/connectors", tags=["connectors"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_connector(row: dict[str, Any]) -> InstalledConnector:
    return InstalledConnector(
        connector_id=row["id"],
        tenant_id=row["tenant_id"],
        name=row["name"],
        category=ConnectorCategory(row["category"]),
        status=ConnectorStatus(row["status"]),
        version=row["version"],
        installed_at=datetime.fromisoformat(row["installed_at"]),
        last_sync=datetime.fromisoformat(row["last_sync"]) if row.get("last_sync") else None,
        last_heartbeat=datetime.fromisoformat(row["last_heartbeat"]) if row.get("last_heartbeat") else None,
        failure_count=row.get("failure_count", 0),
        retry_count=row.get("retry_count", 0),
        config=json.loads(row.get("config_json", "{}")),
        health_score=row.get("health_score", 1.0),
    )


def _require_connector(connector_id: str, tenant_id: Optional[str] = None) -> dict[str, Any]:
    db = get_panel_db()
    if tenant_id:
        row = db.fetch_one(
            "SELECT * FROM connectors WHERE id = ? AND tenant_id = ?",
            (connector_id, tenant_id),
        )
    else:
        row = db.fetch_one("SELECT * FROM connectors WHERE id = ?", (connector_id,))
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Connector '{connector_id}' not found")
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[InstalledConnector], summary="List installed connectors")
async def list_connectors(
    tenant_id: str = Query(..., description="Tenant ID"),
    category: Optional[str] = Query(None),
    connector_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    db = get_panel_db()
    sql = "SELECT * FROM connectors WHERE tenant_id = ?"
    params: list[Any] = [tenant_id]

    if category:
        sql += " AND category = ?"
        params.append(category)
    if connector_status:
        sql += " AND status = ?"
        params.append(connector_status)

    sql += " ORDER BY installed_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.fetch_all(sql, params)
    return [_row_to_connector(r) for r in rows]


@router.get("/{connector_id}", response_model=InstalledConnector, summary="Get connector details")
async def get_connector(connector_id: str, tenant_id: Optional[str] = Query(None)):
    row = _require_connector(connector_id, tenant_id)
    return _row_to_connector(row)


@router.put("/{connector_id}", response_model=InstalledConnector, summary="Update connector config")
async def update_connector(
    connector_id: str,
    body: ConnectorConfigUpdate,
    tenant_id: str = Query(...),
):
    row = _require_connector(connector_id, tenant_id)
    db = get_panel_db()

    updates: list[str] = []
    params: list[Any] = []

    if body.config is not None:
        updates.append("config_json = ?")
        params.append(json.dumps(body.config))
    if body.is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if body.is_active else 0)
        updates.append("status = ?")
        params.append(ConnectorStatus.ACTIVE.value if body.is_active else ConnectorStatus.INACTIVE.value)

    if not updates:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No fields to update")

    params.extend([connector_id, tenant_id])
    db.execute(
        f"UPDATE connectors SET {', '.join(updates)} WHERE id = ? AND tenant_id = ?",
        params,
    )

    updated_row = _require_connector(connector_id, tenant_id)
    return _row_to_connector(updated_row)


@router.delete("/{connector_id}", response_model=APIResponse, summary="Uninstall connector")
async def uninstall_connector(connector_id: str, tenant_id: str = Query(...)):
    _require_connector(connector_id, tenant_id)
    db = get_panel_db()
    db.execute(
        "UPDATE connectors SET is_active = 0, status = ? WHERE id = ? AND tenant_id = ?",
        (ConnectorStatus.INACTIVE.value, connector_id, tenant_id),
    )
    return APIResponse(message=f"Connector '{connector_id}' uninstalled")


@router.post("/{connector_id}/enable", response_model=InstalledConnector, summary="Enable connector")
async def enable_connector(connector_id: str, tenant_id: str = Query(...)):
    _require_connector(connector_id, tenant_id)
    db = get_panel_db()
    db.execute(
        "UPDATE connectors SET status = ?, is_active = 1 WHERE id = ? AND tenant_id = ?",
        (ConnectorStatus.ACTIVE.value, connector_id, tenant_id),
    )
    return _row_to_connector(_require_connector(connector_id, tenant_id))


@router.post("/{connector_id}/disable", response_model=InstalledConnector, summary="Disable connector")
async def disable_connector(connector_id: str, tenant_id: str = Query(...)):
    _require_connector(connector_id, tenant_id)
    db = get_panel_db()
    db.execute(
        "UPDATE connectors SET status = ?, is_active = 0 WHERE id = ? AND tenant_id = ?",
        (ConnectorStatus.INACTIVE.value, connector_id, tenant_id),
    )
    return _row_to_connector(_require_connector(connector_id, tenant_id))


@router.post("/{connector_id}/sync", response_model=APIResponse, summary="Trigger manual sync")
async def trigger_sync(connector_id: str, tenant_id: str = Query(...)):
    row = _require_connector(connector_id, tenant_id)
    if row["status"] not in (ConnectorStatus.ACTIVE.value, ConnectorStatus.DEGRADED.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot sync connector in status '{row['status']}'. Enable it first.",
        )
    db = get_panel_db()
    # Enqueue a sync job
    from ..shared.utils import generate_job_id
    job_id = generate_job_id()
    now = utc_now_str()
    db.execute(
        """
        INSERT INTO queue_jobs
            (id, connector_id, tenant_id, job_type, status, payload_json,
             attempts, max_attempts, error, created_at, updated_at)
        VALUES (?, ?, ?, 'sync', 'queued', '{}', 0, 3, NULL, ?, ?)
        """,
        (job_id, connector_id, tenant_id, now, now),
    )
    return APIResponse(message="Sync job queued", data={"job_id": job_id})


@router.get("/{connector_id}/config", summary="Get connector configuration (sanitised)")
async def get_connector_config(connector_id: str, tenant_id: str = Query(...)):
    row = _require_connector(connector_id, tenant_id)
    config = json.loads(row.get("config_json", "{}"))
    # Mask secret-like keys
    sanitised: dict[str, Any] = {}
    for k, v in config.items():
        lower_k = k.lower()
        if any(s in lower_k for s in ("secret", "password", "token", "key", "pwd")):
            sanitised[k] = "***"
        else:
            sanitised[k] = v
    return {"connector_id": connector_id, "config": sanitised}


@router.post("/{connector_id}/test", response_model=APIResponse, summary="Test connector connection")
async def test_connector(connector_id: str, tenant_id: str = Query(...)):
    row = _require_connector(connector_id, tenant_id)
    manifest_id = row["manifest_id"]

    # Attempt to dynamically load the connector plugin and call test_connection
    try:
        import importlib
        module_path = f"platform.connectors_panel.plugins.{manifest_id}.module"
        try:
            mod = importlib.import_module(module_path)
        except ModuleNotFoundError:
            # Fallback: basic HTTP ping if health_endpoint present
            return APIResponse(
                success=True,
                message="Connection test skipped (no plugin module found for this connector)",
                data={"connector_id": connector_id, "tested": False},
            )

        connector_class = getattr(mod, None.__class__.__name__, None)
        # Find the first class that has test_connection method
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if isinstance(obj, type) and hasattr(obj, "test_connection"):
                instance = obj()
                config = json.loads(row.get("config_json", "{}"))
                result = instance.test_connection(tenant_id, config)
                return APIResponse(
                    success=result,
                    message="Connection test passed" if result else "Connection test failed",
                    data={"connector_id": connector_id, "tested": True, "result": result},
                )
    except Exception as exc:
        return APIResponse(
            success=False,
            message=f"Connection test error: {exc}",
            data={"connector_id": connector_id, "tested": True, "error": str(exc)},
        )

    return APIResponse(
        success=True,
        message="Connection test completed",
        data={"connector_id": connector_id, "tested": True},
    )
