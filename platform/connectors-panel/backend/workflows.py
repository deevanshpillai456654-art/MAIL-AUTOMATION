"""
Workflows router — workflow builder, execution engine, rule management.
Prefix: /workflows
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from ..shared.utils import utc_now_str

router = APIRouter(prefix="/workflows", tags=["workflows"])

TRIGGER_TYPES = ["manual", "event", "schedule", "webhook", "condition"]
STEP_TYPES = ["action", "condition", "delay", "notification", "api_call", "transform", "approval"]


def _int(v):
    try: return int(v) if v is not None else 0
    except: return 0


# ---------------------------------------------------------------------------
# Workflow Definitions
# ---------------------------------------------------------------------------

@router.get("", summary="List workflow definitions")
async def list_workflows(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["tenant_id = ?"]
    params: list = [tenant_id]
    if status:
        conditions.append("status = ?"); params.append(status)
    where = " AND ".join(conditions)
    rows = db.fetch_all(
        f"SELECT * FROM workflow_definitions WHERE {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",  # nosec B608
        params + [limit, offset],
    )
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM workflow_definitions WHERE {where}", params)  # nosec B608
    return {"workflows": rows, "total": _int(total["c"] if total else 0)}


@router.post("", summary="Create workflow", status_code=status.HTTP_201_CREATED)
async def create_workflow(body: dict[str, Any], tenant_id: str = Query(...)):
    db = get_panel_db()
    wid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO workflow_definitions (id,tenant_id,name,description,trigger_type,trigger_config,steps_json,status,run_count,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (wid, tenant_id, body["name"], body.get("description"),
         body.get("trigger_type","manual"), body.get("trigger_config","{}"),
         body.get("steps_json","[]"), body.get("status","draft"), 0, now, now),
    )
    return db.fetch_one("SELECT * FROM workflow_definitions WHERE id=?", (wid,))


@router.get("/summary", summary="Workflow engine summary")
async def workflow_summary(tenant_id: str = Query(...)):
    db = get_panel_db()
    defs = db.fetch_one("SELECT COUNT(*) AS c FROM workflow_definitions WHERE tenant_id=?", (tenant_id,))
    active = db.fetch_one("SELECT COUNT(*) AS c FROM workflow_definitions WHERE tenant_id=? AND status='active'", (tenant_id,))
    execs = db.fetch_one("SELECT COUNT(*) AS c FROM workflow_executions WHERE tenant_id=?", (tenant_id,))
    running = db.fetch_one("SELECT COUNT(*) AS c FROM workflow_executions WHERE tenant_id=? AND status='running'", (tenant_id,))
    failed = db.fetch_one("SELECT COUNT(*) AS c FROM workflow_executions WHERE tenant_id=? AND status='failed'", (tenant_id,))
    return {
        "total_workflows": _int(defs["c"] if defs else 0),
        "active_workflows": _int(active["c"] if active else 0),
        "total_executions": _int(execs["c"] if execs else 0),
        "running": _int(running["c"] if running else 0),
        "failed": _int(failed["c"] if failed else 0),
        "trigger_types": TRIGGER_TYPES,
        "step_types": STEP_TYPES,
    }


@router.get("/{workflow_id}", summary="Get workflow detail")
async def get_workflow(workflow_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    row = db.fetch_one("SELECT * FROM workflow_definitions WHERE id=? AND tenant_id=?", (workflow_id, tenant_id))
    if not row:
        raise HTTPException(status_code=404, detail="Workflow not found")
    execs = db.fetch_all(
        "SELECT id,status,current_step,started_at,completed_at,error FROM workflow_executions WHERE workflow_id=? ORDER BY started_at DESC LIMIT 10",
        (workflow_id,),
    )
    row["recent_executions"] = execs
    return row


@router.patch("/{workflow_id}", summary="Update workflow")
async def update_workflow(workflow_id: str, body: dict[str, Any], tenant_id: str = Query(...)):
    db = get_panel_db()
    existing = db.fetch_one("SELECT id FROM workflow_definitions WHERE id=? AND tenant_id=?", (workflow_id, tenant_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Workflow not found")
    now = utc_now_str()
    allowed = {"name","description","trigger_type","trigger_config","steps_json","status"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        db.execute(f"UPDATE workflow_definitions SET {', '.join(f'{k}=?' for k in updates)}, updated_at=? WHERE id=? AND tenant_id=?", list(updates.values()) + [now, workflow_id, tenant_id])  # nosec B608
    return {"ok": True}


@router.delete("/{workflow_id}", summary="Delete workflow")
async def delete_workflow(workflow_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    db.execute("DELETE FROM workflow_definitions WHERE id=? AND tenant_id=?", (workflow_id, tenant_id))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Workflow Executions
# ---------------------------------------------------------------------------

@router.post("/{workflow_id}/run", summary="Trigger workflow execution")
async def run_workflow(workflow_id: str, body: dict[str, Any], tenant_id: str = Query(...)):
    db = get_panel_db()
    wf = db.fetch_one("SELECT * FROM workflow_definitions WHERE id=? AND tenant_id=?", (workflow_id, tenant_id))
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    eid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO workflow_executions (id,workflow_id,tenant_id,trigger_event,status,current_step,steps_result,started_at) VALUES (?,?,?,?,?,?,?,?)",
        (eid, workflow_id, wf["tenant_id"], body.get("event","{}"), "running", 0, "[]", now),
    )
    db.execute("UPDATE workflow_definitions SET run_count=run_count+1, last_run=?, updated_at=? WHERE id=?", (now, now, workflow_id))
    # Simulate immediate completion for manual triggers (real async workers would process)
    db.execute("UPDATE workflow_executions SET status='completed', completed_at=? WHERE id=?", (now, eid))
    return {"ok": True, "execution_id": eid, "status": "completed"}


@router.get("/{workflow_id}/executions", summary="Get workflow execution history")
async def list_executions(
    workflow_id: str,
    tenant_id: str = Query(...),
    limit: int = Query(20, le=100),
):
    db = get_panel_db()
    rows = db.fetch_all(
        "SELECT * FROM workflow_executions WHERE workflow_id=? AND tenant_id=? ORDER BY started_at DESC LIMIT ?",
        (workflow_id, tenant_id, limit),
    )
    return {"executions": rows, "total": len(rows)}


@router.get("/executions/all", summary="All recent executions")
async def all_executions(tenant_id: str = Query(...), limit: int = Query(50, le=200)):
    db = get_panel_db()
    rows = db.fetch_all(
        "SELECT e.*, w.name AS workflow_name FROM workflow_executions e LEFT JOIN workflow_definitions w ON e.workflow_id=w.id WHERE e.tenant_id=? ORDER BY e.started_at DESC LIMIT ?",
        (tenant_id, limit),
    )
    return {"executions": rows, "total": len(rows)}
