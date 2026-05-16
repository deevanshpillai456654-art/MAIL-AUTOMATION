"""Workflow CRUD API router."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from .db import get_db, tx
from .models import (
    WorkflowCreate, WorkflowDefinition, WorkflowStatus, WorkflowUpdate,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _row_to_workflow(row) -> WorkflowDefinition:
    import json as _json
    d = dict(row)
    return WorkflowDefinition(
        id=d["id"],
        name=d["name"],
        description=d.get("description"),
        tenant_id=d["tenant_id"],
        version=d.get("version", 1),
        status=WorkflowStatus(d.get("status", "draft")),
        nodes=_json.loads(d.get("nodes_json") or "[]"),
        connections=_json.loads(d.get("connections_json") or "[]"),
        variables=_json.loads(d.get("variables_json") or "{}"),
        tags=_json.loads(d.get("tags_json") or "[]"),
        created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.utcnow(),
        updated_at=datetime.fromisoformat(d["updated_at"]) if d.get("updated_at") else datetime.utcnow(),
        created_by=d.get("created_by"),
    )


@router.get("/", response_model=List[WorkflowDefinition])
async def list_workflows(
    tenant_id: str = Query(...),
    status: Optional[WorkflowStatus] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM workflows WHERE tenant_id=? AND status=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (tenant_id, status.value, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM workflows WHERE tenant_id=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (tenant_id, limit, offset),
        ).fetchall()
    return [_row_to_workflow(r) for r in rows]


@router.post("/", response_model=WorkflowDefinition, status_code=201)
async def create_workflow(payload: WorkflowCreate, tenant_id: str = Query(...)):
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with tx() as conn:
        conn.execute(
            """INSERT INTO workflows
               (id,name,description,tenant_id,version,status,nodes_json,connections_json,variables_json,tags_json,created_at,updated_at)
               VALUES (?,?,?,?,1,'draft',?,?,?,?,?,?)""",
            (
                wf_id, payload.name, payload.description, tenant_id,
                json.dumps([n.model_dump() for n in payload.nodes]),
                json.dumps([c.model_dump() for c in payload.connections]),
                json.dumps(payload.variables),
                json.dumps(payload.tags),
                now, now,
            ),
        )
    row = get_db().execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    return _row_to_workflow(row)


@router.get("/{wf_id}", response_model=WorkflowDefinition)
async def get_workflow(wf_id: str, tenant_id: str = Query(...)):
    row = get_db().execute(
        "SELECT * FROM workflows WHERE id=? AND tenant_id=?", (wf_id, tenant_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Workflow not found")
    return _row_to_workflow(row)


@router.put("/{wf_id}", response_model=WorkflowDefinition)
async def update_workflow(wf_id: str, payload: WorkflowUpdate, tenant_id: str = Query(...)):
    row = get_db().execute(
        "SELECT * FROM workflows WHERE id=? AND tenant_id=?", (wf_id, tenant_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Workflow not found")

    updates: dict = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.description is not None:
        updates["description"] = payload.description
    if payload.status is not None:
        updates["status"] = payload.status.value
    if payload.nodes is not None:
        updates["nodes_json"] = json.dumps([n.model_dump() for n in payload.nodes])
    if payload.connections is not None:
        updates["connections_json"] = json.dumps([c.model_dump() for c in payload.connections])
    if payload.variables is not None:
        updates["variables_json"] = json.dumps(payload.variables)
    if payload.tags is not None:
        updates["tags_json"] = json.dumps(payload.tags)
    updates["updated_at"] = datetime.utcnow().isoformat()

    set_clause = ", ".join(f"{k}=?" for k in updates)
    with tx() as conn:
        conn.execute(
            f"UPDATE workflows SET {set_clause} WHERE id=? AND tenant_id=?",
            (*updates.values(), wf_id, tenant_id),
        )
    row = get_db().execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    return _row_to_workflow(row)


@router.delete("/{wf_id}", status_code=204)
async def delete_workflow(wf_id: str, tenant_id: str = Query(...)):
    with tx() as conn:
        conn.execute(
            "DELETE FROM workflows WHERE id=? AND tenant_id=?", (wf_id, tenant_id)
        )


@router.post("/{wf_id}/activate", response_model=WorkflowDefinition)
async def activate_workflow(wf_id: str, tenant_id: str = Query(...)):
    with tx() as conn:
        conn.execute(
            "UPDATE workflows SET status='active', updated_at=? WHERE id=? AND tenant_id=?",
            (datetime.utcnow().isoformat(), wf_id, tenant_id),
        )
    row = get_db().execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Workflow not found")
    return _row_to_workflow(row)
