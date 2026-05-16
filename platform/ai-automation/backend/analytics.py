"""Analytics and statistics API router."""
from __future__ import annotations

from datetime import datetime
from typing import List

from fastapi import APIRouter, Query

from .db import get_db
from .models import PlatformStats, WorkflowAnalytics

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/stats", response_model=PlatformStats)
async def platform_stats(tenant_id: str = Query(...)):
    conn = get_db()
    total_wf = conn.execute("SELECT COUNT(*) FROM workflows WHERE tenant_id=?", (tenant_id,)).fetchone()[0]
    active_wf = conn.execute("SELECT COUNT(*) FROM workflows WHERE tenant_id=? AND status='active'", (tenant_id,)).fetchone()[0]
    total_exec = conn.execute("SELECT COUNT(*) FROM executions WHERE tenant_id=?", (tenant_id,)).fetchone()[0]
    running_exec = conn.execute("SELECT COUNT(*) FROM executions WHERE tenant_id=? AND status='running'", (tenant_id,)).fetchone()[0]
    pending_approvals = conn.execute("SELECT COUNT(*) FROM approval_requests WHERE tenant_id=? AND status='pending'", (tenant_id,)).fetchone()[0]
    ai_today = conn.execute(
        "SELECT COUNT(*) FROM ai_requests_log WHERE tenant_id=? AND created_at >= date('now')",
        (tenant_id,),
    ).fetchone()[0]
    ocr_today = conn.execute(
        "SELECT COUNT(*) FROM ocr_results WHERE tenant_id=? AND created_at >= date('now')",
        (tenant_id,),
    ).fetchone()[0]

    return PlatformStats(
        total_workflows=total_wf,
        active_workflows=active_wf,
        total_executions=total_exec,
        running_executions=running_exec,
        pending_approvals=pending_approvals,
        ai_requests_today=ai_today,
        ocr_documents_today=ocr_today,
        tenant_id=tenant_id,
    )


@router.get("/workflows", response_model=List[WorkflowAnalytics])
async def workflow_analytics(tenant_id: str = Query(...), limit: int = Query(20, le=100)):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name FROM workflows WHERE tenant_id=? LIMIT ?", (tenant_id, limit)
    ).fetchall()

    result = []
    for r in rows:
        wf_id, wf_name = r["id"], r["name"]
        stats = conn.execute(
            """SELECT
               COUNT(*) as total,
               SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as successful,
               SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
               SUM(CASE WHEN status='waiting_approval' THEN 1 ELSE 0 END) as pending_approvals,
               AVG(duration_ms) as avg_duration,
               MAX(started_at) as last_executed
               FROM executions WHERE workflow_id=? AND tenant_id=?""",
            (wf_id, tenant_id),
        ).fetchone()
        s = dict(stats)
        total = s["total"] or 0
        successful = s["successful"] or 0
        result.append(WorkflowAnalytics(
            workflow_id=wf_id,
            workflow_name=wf_name,
            tenant_id=tenant_id,
            total_executions=total,
            successful=successful,
            failed=s["failed"] or 0,
            pending_approvals=s["pending_approvals"] or 0,
            avg_duration_ms=s["avg_duration"] or 0.0,
            success_rate=(successful / total * 100) if total else 0.0,
            last_executed=datetime.fromisoformat(s["last_executed"]) if s.get("last_executed") else None,
        ))
    return result


@router.get("/executions/timeline")
async def execution_timeline(tenant_id: str = Query(...), days: int = 7):
    conn = get_db()
    rows = conn.execute(
        """SELECT date(started_at) as date,
           COUNT(*) as total,
           SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
           SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed
           FROM executions WHERE tenant_id=? AND started_at >= datetime('now', ? || ' days')
           GROUP BY date(started_at) ORDER BY date""",
        (tenant_id, f"-{days}"),
    ).fetchall()
    return [dict(r) for r in rows]
