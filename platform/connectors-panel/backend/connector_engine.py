"""
Connector Engine Router — SDK-backed install, sync, OAuth, webhook, health.
Prefix: /engine

These endpoints expose the ConnectorRegistry and ConnectorWorker to the
frontend and to external orchestrators.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query, Request, status
from pydantic import BaseModel

from .db import get_panel_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/engine", tags=["connector-engine"])

# ---------------------------------------------------------------------------
# Lazy import helpers — avoid hard circular imports at module load time
# ---------------------------------------------------------------------------

def _registry():
    try:
        from ..connectors.sdk.registry import ConnectorRegistry
        return ConnectorRegistry.get()
    except Exception as exc:
        log.warning("ConnectorRegistry not available: %s", exc)
        return None


def _worker():
    try:
        from ..connectors.sdk.worker import get_worker
        return get_worker()
    except Exception as exc:
        log.warning("ConnectorWorker not available: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class InstallRequest(BaseModel):
    connector_id: str
    tenant_id: str
    name: str
    config: Dict[str, Any] = {}


class SyncRequest(BaseModel):
    entity: Optional[str] = None
    tenant_id: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str
    tenant_id: str
    redirect_uri: str


class ShipmentTrackRequest(BaseModel):
    tracking_number: str
    tenant_id: str


# ---------------------------------------------------------------------------
# Registry / Manifest endpoints
# ---------------------------------------------------------------------------

@router.get("/manifests", summary="List all available connector manifests")
async def list_manifests():
    reg = _registry()
    if not reg:
        return {"available": []}
    # list_manifests() already returns list of dicts
    return {"available": reg.list_manifests()}


@router.get("/manifests/{connector_id}", summary="Get a single connector manifest")
async def get_manifest(connector_id: str):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")
    m = reg.get_manifest(connector_id)
    if not m:
        raise HTTPException(status_code=404, detail=f"Connector '{connector_id}' not found")
    return m.to_dict()


# ---------------------------------------------------------------------------
# Install / Uninstall
# ---------------------------------------------------------------------------

@router.post("/install", status_code=201, summary="Install a connector")
async def install_connector(req: InstallRequest):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")
    try:
        instance_id = await reg.install(
            connector_id=req.connector_id,
            tenant_id=req.tenant_id,
            config=req.config,
            name=req.name,
        )
        return {"instance_id": instance_id, "connector_id": req.connector_id,
                "status": "installed"}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("Install failed for %s", req.connector_id)
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/instances/{instance_id}", summary="Uninstall a connector instance")
async def uninstall_connector(instance_id: str, tenant_id: str = Query(...)):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")
    try:
        await reg.uninstall(instance_id)
        return {"instance_id": instance_id, "status": "uninstalled"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

@router.post("/instances/{instance_id}/sync", summary="Trigger connector sync")
async def trigger_sync(instance_id: str, req: SyncRequest,
                        background_tasks: BackgroundTasks,
                        connector_id: Optional[str] = Query(None)):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")
    db = get_panel_db()

    row = db.fetch_one(
        "SELECT * FROM connectors WHERE id=? AND tenant_id=?",
        (instance_id, req.tenant_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")

    config = json.loads(row.get("config") or row.get("config_json") or "{}")
    # connector_id (type) may be passed as query param; fall back to name matching
    cid = connector_id
    if not cid:
        cls = reg._find_class_by_instance(instance_id)
        cid = cls.MANIFEST.id if cls else ""
    if not cid:
        raise HTTPException(status_code=400,
                            detail="Cannot determine connector type — pass ?connector_id=")

    try:
        connector = reg.instantiate(instance_id, cid, req.tenant_id, config)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Cannot instantiate: {exc}")

    async def _run():
        try:
            if req.entity:
                result = await connector.sync(req.entity)
            else:
                result = await connector.run_sync_all()
            log.info("Sync completed: instance=%s result=%s", instance_id, result)
        except Exception as exc2:
            log.exception("Sync failed: instance=%s", instance_id)
        finally:
            await connector.close()

    background_tasks.add_task(_run)
    return {"instance_id": instance_id, "entity": req.entity,
            "status": "queued", "message": "Sync started in background"}


@router.post("/instances/{instance_id}/sync-all", summary="Sync all entities")
async def sync_all(instance_id: str, tenant_id: str = Query(...),
                    background_tasks: BackgroundTasks = None):
    return await trigger_sync(instance_id,
                               SyncRequest(tenant_id=tenant_id, entity=None),
                               background_tasks)


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

@router.get("/oauth/authorize/{connector_id}",
             summary="Generate OAuth authorization URL")
async def oauth_authorize(
    connector_id: str,
    tenant_id: str = Query(...),
    instance_id: str = Query(...),
    redirect_uri: str = Query(...),
):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")
    db = get_panel_db()
    row = db.fetch_one(
        "SELECT * FROM connectors WHERE id=? AND tenant_id=?",
        (instance_id, tenant_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")

    config = json.loads(row.get("config") or row.get("config_json") or "{}")
    if not reg.get_class(connector_id):
        raise HTTPException(status_code=404,
                            detail=f"Unknown connector type: {connector_id}")
    connector = reg.instantiate(instance_id, connector_id, tenant_id, config)

    import secrets
    state = secrets.token_urlsafe(24)
    try:
        auth_url = await connector.get_auth_url(redirect_uri, state)
        return {"auth_url": auth_url, "state": state}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        await connector.close()


@router.post("/oauth/callback/{connector_id}",
              summary="Handle OAuth callback (exchange code)")
async def oauth_callback(connector_id: str, req: OAuthCallbackRequest):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")
    db = get_panel_db()

    # Find instance for this tenant + connector (name match against manifest)
    row = db.fetch_one(
        "SELECT * FROM connectors WHERE name LIKE ? AND tenant_id=?",
        (f"%{connector_id.replace('_', ' ')}%", req.tenant_id),
    )
    if not row:
        row = db.fetch_one(
            "SELECT * FROM connectors WHERE tenant_id=? AND category=? LIMIT 1",
            (req.tenant_id, connector_id),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Connector instance not found")

    instance_id = row.get("id", "")
    config = json.loads(row.get("config") or row.get("config_json") or "{}")
    connector = reg.instantiate(instance_id, connector_id,
                                 req.tenant_id, config)
    try:
        result = await connector.exchange_code(req.code, req.redirect_uri)
        return {"status": "connected", "connector_id": connector_id,
                "result": result}
    except Exception as exc:
        log.exception("OAuth callback failed for %s", connector_id)
        raise HTTPException(status_code=400, detail=str(exc))
    finally:
        await connector.close()


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

@router.post("/webhooks/{connector_id}/{tenant_id}",
              summary="Receive webhook from connector provider")
async def receive_webhook(
    connector_id: str,
    tenant_id: str,
    request: Request,
):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")

    raw_body = await request.body()
    headers = dict(request.headers)
    db = get_panel_db()

    row = db.fetch_one(
        "SELECT * FROM connectors WHERE name LIKE ? AND tenant_id=?",
        (f"%{connector_id.replace('_', ' ')}%", tenant_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Connector not found")

    instance_id = row.get("id", "")
    config = json.loads(row.get("config") or row.get("config_json") or "{}")
    connector = reg.instantiate(instance_id, connector_id, tenant_id, config)
    if not connector:
        raise HTTPException(status_code=404,
                            detail=f"Connector type '{connector_id}' not registered")

    try:
        valid = await connector.verify_webhook_signature(raw_body, headers)
        if not valid:
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        try:
            payload = await request.json()
        except Exception:
            import json as _json
            payload = _json.loads(raw_body) if raw_body else {}

        event_type = headers.get("x-event-type", headers.get("x-github-event", ""))
        await connector.handle_webhook(event_type, payload, raw_body, headers)
        return {"status": "processed"}
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("Webhook processing failed: %s/%s", connector_id, tenant_id)
        raise HTTPException(status_code=500, detail=str(exc))
    finally:
        await connector.close()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@router.get("/instances/{instance_id}/health",
             summary="Run health check for a connector instance")
async def health_check(instance_id: str, tenant_id: str = Query(...),
                        connector_id: Optional[str] = Query(None)):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")
    db = get_panel_db()

    row = db.fetch_one(
        "SELECT * FROM connectors WHERE id=? AND tenant_id=?",
        (instance_id, tenant_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")

    cid = connector_id
    if not cid:
        cls = reg._find_class_by_instance(instance_id)
        cid = cls.MANIFEST.id if cls else None
    if not cid:
        raise HTTPException(status_code=400,
                            detail="Cannot determine connector type — pass ?connector_id=")

    config = json.loads(row.get("config") or row.get("config_json") or "{}")
    connector = reg.instantiate(instance_id, cid, tenant_id, config)
    if not connector:
        raise HTTPException(status_code=404, detail=f"Connector type '{cid}' not found")
    try:
        result = await connector.health_check()
        return result
    finally:
        await connector.close()


# ---------------------------------------------------------------------------
# Worker status
# ---------------------------------------------------------------------------

@router.get("/worker/status", summary="Get connector worker status")
async def worker_status():
    w = _worker()
    if not w:
        return {"running": False, "message": "Worker not initialised"}
    return {
        "running": w.is_running(),
        "active_jobs": w.active_count(),
        "processed": w.processed_count(),
    }


@router.post("/worker/start", summary="Start the connector worker")
async def start_worker():
    w = _worker()
    if not w:
        raise HTTPException(status_code=503, detail="Worker not available")
    w.start()
    return {"status": "started"}


@router.post("/worker/stop", summary="Stop the connector worker")
async def stop_worker():
    w = _worker()
    if not w:
        raise HTTPException(status_code=503, detail="Worker not available")
    w.stop()
    return {"status": "stopped"}


# ---------------------------------------------------------------------------
# Connector-specific actions (convenience endpoints)
# ---------------------------------------------------------------------------

@router.post("/shipping/{instance_id}/track",
              summary="Track a shipment via carrier connector")
async def track_shipment(instance_id: str, req: ShipmentTrackRequest):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")
    db = get_panel_db()
    row = db.fetch_one(
        "SELECT * FROM connectors WHERE id=? AND tenant_id=?",
        (instance_id, req.tenant_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")

    cls = reg._find_class_by_instance(instance_id)
    cid = cls.MANIFEST.id if cls else ""
    config = json.loads(row.get("config") or row.get("config_json") or "{}")
    connector = reg.instantiate(instance_id, cid, req.tenant_id, config) if cid else None
    if not connector:
        raise HTTPException(status_code=400, detail="Cannot resolve connector type")
    try:
        if hasattr(connector, "track_shipment"):
            result = await connector.track_shipment(req.tracking_number)
            return result
        elif hasattr(connector, "track_by_awb"):
            result = await connector.track_by_awb(req.tracking_number)
            return result
        else:
            raise HTTPException(status_code=400,
                                detail="This connector does not support tracking")
    finally:
        await connector.close()


@router.post("/slack/{instance_id}/alert",
              summary="Send Slack alert via connector instance")
async def send_slack_alert(
    instance_id: str,
    tenant_id: str = Query(...),
    title: str = Body(...),
    message: str = Body(...),
    level: str = Body("info"),
    channel: Optional[str] = Body(None),
):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")
    db = get_panel_db()
    row = db.fetch_one(
        "SELECT * FROM connectors WHERE id=? AND tenant_id=?",
        (instance_id, tenant_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")

    config = json.loads(row.get("config") or row.get("config_json") or "{}")
    connector = reg.instantiate(instance_id, "slack_enterprise", tenant_id, config)
    try:
        result = await connector.send_alert(title, message, level, channel)
        return {"status": "sent", "result": result}
    finally:
        await connector.close()


@router.post("/teams/{instance_id}/notification",
              summary="Send Teams notification via connector instance")
async def send_teams_notification(
    instance_id: str,
    tenant_id: str = Query(...),
    title: str = Body(...),
    message: str = Body(...),
    level: str = Body("info"),
):
    reg = _registry()
    if not reg:
        raise HTTPException(status_code=503, detail="Registry not available")
    db = get_panel_db()
    row = db.fetch_one(
        "SELECT * FROM connectors WHERE id=? AND tenant_id=?",
        (instance_id, tenant_id),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Instance not found")

    config = json.loads(row.get("config") or row.get("config_json") or "{}")
    connector = reg.instantiate(instance_id, "teams", tenant_id, config)
    try:
        result = await connector.send_notification(title, message, level)
        return {"status": "sent", "result": result}
    finally:
        await connector.close()
