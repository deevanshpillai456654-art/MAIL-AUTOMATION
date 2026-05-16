"""Execution tracking API router."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from .db import get_db, tx
from .models import (
    ExecutionCreate, ExecutionStatus, WorkflowExecution,
)

router = APIRouter(prefix="/executions", tags=["executions"])


def _row_to_execution(row) -> WorkflowExecution:
    d = dict(row)
    steps_raw = get_db().execute(
        "SELECT * FROM execution_steps WHERE execution_id=? ORDER BY rowid",
        (d["id"],),
    ).fetchall()
    from .models import ExecutionStep, NodeType
    steps = []
    for s in steps_raw:
        sd = dict(s)
        steps.append(ExecutionStep(
            id=sd["id"],
            execution_id=sd["execution_id"],
            node_id=sd["node_id"],
            node_type=NodeType(sd["node_type"]),
            status=ExecutionStatus(sd.get("status", "pending")),
            input_data=json.loads(sd.get("input_data_json") or "{}"),
            output_data=json.loads(sd.get("output_data_json") or "{}"),
            error=sd.get("error"),
            started_at=datetime.fromisoformat(sd["started_at"]) if sd.get("started_at") else None,
            completed_at=datetime.fromisoformat(sd["completed_at"]) if sd.get("completed_at") else None,
            duration_ms=sd.get("duration_ms"),
            retry_count=sd.get("retry_count", 0),
        ))

    return WorkflowExecution(
        id=d["id"],
        workflow_id=d["workflow_id"],
        workflow_name=d.get("workflow_name", ""),
        tenant_id=d["tenant_id"],
        status=ExecutionStatus(d.get("status", "pending")),
        trigger_data=json.loads(d.get("trigger_data_json") or "{}"),
        context=json.loads(d.get("context_json") or "{}"),
        steps=steps,
        current_node_id=d.get("current_node_id"),
        error=d.get("error"),
        started_at=datetime.fromisoformat(d["started_at"]) if d.get("started_at") else None,
        completed_at=datetime.fromisoformat(d["completed_at"]) if d.get("completed_at") else None,
        duration_ms=d.get("duration_ms"),
        triggered_by=d.get("triggered_by"),
    )


@router.get("/", response_model=List[WorkflowExecution])
async def list_executions(
    tenant_id: str = Query(...),
    workflow_id: Optional[str] = None,
    status: Optional[ExecutionStatus] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    conn = get_db()
    base = "SELECT * FROM executions WHERE tenant_id=?"
    params: list = [tenant_id]
    if workflow_id:
        base += " AND workflow_id=?"
        params.append(workflow_id)
    if status:
        base += " AND status=?"
        params.append(status.value)
    base += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = conn.execute(base, params).fetchall()
    return [_row_to_execution(r) for r in rows]


@router.post("/", response_model=WorkflowExecution, status_code=201)
async def trigger_execution(
    payload: ExecutionCreate,
    tenant_id: str = Query(...),
    background_tasks: BackgroundTasks = None,
):
    conn = get_db()
    wf_row = conn.execute(
        "SELECT * FROM workflows WHERE id=? AND tenant_id=?",
        (payload.workflow_id, tenant_id),
    ).fetchone()
    if not wf_row:
        raise HTTPException(404, "Workflow not found")

    exec_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with tx() as c:
        c.execute(
            """INSERT INTO executions
               (id,workflow_id,workflow_name,tenant_id,status,trigger_data_json,context_json,started_at,triggered_by)
               VALUES (?,?,?,?,'pending',?,?,?,?)""",
            (
                exec_id, payload.workflow_id, dict(wf_row)["name"], tenant_id,
                json.dumps(payload.trigger_data), "{}", now,
                payload.triggered_by,
            ),
        )

    if background_tasks:
        background_tasks.add_task(_run_workflow_bg, exec_id, tenant_id)

    row = get_db().execute("SELECT * FROM executions WHERE id=?", (exec_id,)).fetchone()
    return _row_to_execution(row)


@router.get("/{exec_id}", response_model=WorkflowExecution)
async def get_execution(exec_id: str, tenant_id: str = Query(...)):
    row = get_db().execute(
        "SELECT * FROM executions WHERE id=? AND tenant_id=?", (exec_id, tenant_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Execution not found")
    return _row_to_execution(row)


@router.post("/{exec_id}/cancel", response_model=WorkflowExecution)
async def cancel_execution(exec_id: str, tenant_id: str = Query(...)):
    with tx() as conn:
        conn.execute(
            "UPDATE executions SET status='cancelled', completed_at=? WHERE id=? AND tenant_id=?",
            (datetime.utcnow().isoformat(), exec_id, tenant_id),
        )
    row = get_db().execute("SELECT * FROM executions WHERE id=?", (exec_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Execution not found")
    return _row_to_execution(row)


async def _run_workflow_bg(exec_id: str, tenant_id: str) -> None:
    """Fire-and-forget background execution hook."""
    try:
        from ..engine.executor import WorkflowExecutor
        executor = WorkflowExecutor()
        await executor.resume_execution(exec_id, tenant_id)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Execution %s failed: %s", exec_id, exc)
        with tx() as conn:
            conn.execute(
                "UPDATE executions SET status='failed', error=?, completed_at=? WHERE id=?",
                (str(exc), datetime.utcnow().isoformat(), exec_id),
            )
