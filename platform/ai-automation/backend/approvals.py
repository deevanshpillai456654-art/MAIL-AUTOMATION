"""Approval request management API router."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from .db import get_db, tx
from .models import ApprovalDecision, ApprovalRequest, ApprovalStatus, RiskLevel

router = APIRouter(prefix="/approvals", tags=["approvals"])


def _row_to_approval(row) -> ApprovalRequest:
    d = dict(row)
    return ApprovalRequest(
        id=d["id"],
        execution_id=d.get("execution_id", ""),
        workflow_id=d.get("workflow_id", ""),
        tenant_id=d["tenant_id"],
        title=d["title"],
        description=d.get("description", ""),
        risk_level=RiskLevel(d.get("risk_level", "low")),
        data=json.loads(d.get("data_json") or "{}"),
        assignee=d.get("assignee"),
        assignee_group=d.get("assignee_group"),
        status=ApprovalStatus(d.get("status", "pending")),
        decision=d.get("decision"),
        decision_notes=d.get("decision_notes"),
        decided_by=d.get("decided_by"),
        expires_at=datetime.fromisoformat(d["expires_at"]) if d.get("expires_at") else None,
        escalate_after_minutes=d.get("escalate_after_minutes"),
        created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.utcnow(),
        decided_at=datetime.fromisoformat(d["decided_at"]) if d.get("decided_at") else None,
    )


@router.get("/", response_model=List[ApprovalRequest])
async def list_approvals(
    tenant_id: str = Query(...),
    status: Optional[ApprovalStatus] = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
):
    conn = get_db()
    base = "SELECT * FROM approval_requests WHERE tenant_id=?"
    params: list = [tenant_id]
    if status:
        base += " AND status=?"
        params.append(status.value)
    base += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = conn.execute(base, params).fetchall()
    return [_row_to_approval(r) for r in rows]


@router.post("/", response_model=ApprovalRequest, status_code=201)
async def create_approval(payload: ApprovalRequest, tenant_id: str = Query(...)):
    req_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    with tx() as conn:
        conn.execute(
            """INSERT INTO approval_requests
               (id,execution_id,workflow_id,tenant_id,title,description,risk_level,
                data_json,assignee,assignee_group,status,expires_at,escalate_after_minutes,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                req_id, payload.execution_id, payload.workflow_id, tenant_id,
                payload.title, payload.description, payload.risk_level.value,
                json.dumps(payload.data), payload.assignee, payload.assignee_group,
                "pending",
                payload.expires_at.isoformat() if payload.expires_at else None,
                payload.escalate_after_minutes, now,
            ),
        )
    row = get_db().execute("SELECT * FROM approval_requests WHERE id=?", (req_id,)).fetchone()
    return _row_to_approval(row)


@router.get("/{req_id}", response_model=ApprovalRequest)
async def get_approval(req_id: str, tenant_id: str = Query(...)):
    row = get_db().execute(
        "SELECT * FROM approval_requests WHERE id=? AND tenant_id=?", (req_id, tenant_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Approval not found")
    return _row_to_approval(row)


@router.post("/{req_id}/decide", response_model=ApprovalRequest)
async def decide_approval(req_id: str, decision: ApprovalDecision, tenant_id: str = Query(...)):
    row = get_db().execute(
        "SELECT * FROM approval_requests WHERE id=? AND tenant_id=?", (req_id, tenant_id)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Approval not found")
    if dict(row)["status"] != "pending":
        raise HTTPException(409, "Approval already decided")

    now = datetime.utcnow().isoformat()
    with tx() as conn:
        conn.execute(
            """UPDATE approval_requests SET status=?, decision=?, decision_notes=?,
               decided_by=?, decided_at=? WHERE id=?""",
            (
                decision.status.value, decision.status.value,
                decision.notes, decision.decided_by, now, req_id,
            ),
        )

    # Resume the blocked execution if approved/rejected
    updated = get_db().execute("SELECT * FROM approval_requests WHERE id=?", (req_id,)).fetchone()
    result = _row_to_approval(updated)
    _notify_execution_of_decision(result)
    return result


def _notify_execution_of_decision(approval: ApprovalRequest) -> None:
    """Notify the workflow execution engine of the approval decision."""
    try:
        execution_id = approval.execution_id
        if not execution_id:
            return
        with tx() as conn:
            # Resume execution by updating its status from waiting_approval
            conn.execute(
                "UPDATE executions SET status='running' WHERE id=? AND status='waiting_approval'",
                (execution_id,),
            )
            # Store the decision in context
            row = get_db().execute(
                "SELECT context_json FROM executions WHERE id=?", (execution_id,)
            ).fetchone()
            if row:
                context = json.loads(row["context_json"] or "{}")
                context[f"approval_{approval.id}"] = {
                    "status": approval.status.value,
                    "decided_by": approval.decided_by,
                    "notes": approval.decision_notes,
                }
                conn.execute(
                    "UPDATE executions SET context_json=? WHERE id=?",
                    (json.dumps(context), execution_id),
                )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Failed to notify execution: %s", exc)
