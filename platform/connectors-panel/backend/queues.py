"""
Queues router — manage queue jobs and dead-letter queue.
Prefix: /queues
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from .models import (
    APIResponse,
    JobStatus,
    QueueJob,
    QueueJobCreateRequest,
    QueueStats,
)
from ..shared.utils import generate_job_id, utc_now_str

router = APIRouter(prefix="/queues", tags=["queues"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_job(row: dict[str, Any]) -> QueueJob:
    payload_raw = row.get("payload_json", "{}")
    if isinstance(payload_raw, str):
        try:
            payload = json.loads(payload_raw)
        except Exception:
            payload = {}
    else:
        payload = payload_raw or {}

    return QueueJob(
        job_id=row["id"],
        connector_id=row["connector_id"],
        tenant_id=row["tenant_id"],
        job_type=row["job_type"],
        status=JobStatus(row["status"]),
        payload=payload,
        attempts=row.get("attempts", 0),
        max_attempts=row.get("max_attempts", 3),
        error=row.get("error"),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _require_job(job_id: str) -> dict[str, Any]:
    db = get_panel_db()
    row = db.fetch_one("SELECT * FROM queue_jobs WHERE id = ?", (job_id,))
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found")
    return row


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=list[QueueStats], summary="Get queue stats")
async def get_queue_stats(tenant_id: Optional[str] = Query(None)):
    db = get_panel_db()

    if tenant_id:
        tenant_ids = [tenant_id]
    else:
        rows = db.fetch_all("SELECT DISTINCT tenant_id FROM queue_jobs", ())
        tenant_ids = [r["tenant_id"] for r in rows]

    stats: list[QueueStats] = []
    for tid in tenant_ids:
        row = db.fetch_one(
            """
            SELECT
                SUM(CASE WHEN status = 'queued' THEN 1 ELSE 0 END)      AS queued,
                SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END)  AS processing,
                SUM(CASE WHEN status = 'dead' THEN 1 ELSE 0 END)        AS dead_letters,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END)   AS total_processed,
                MAX(CASE WHEN status = 'completed' THEN updated_at END)  AS last_processed_at
            FROM queue_jobs WHERE tenant_id = ?
            """,
            (tid,),
        )
        stats.append(
            QueueStats(
                tenant_id=tid,
                queued=row["queued"] or 0,
                processing=row["processing"] or 0,
                dead_letters=row["dead_letters"] or 0,
                total_processed=row["total_processed"] or 0,
                last_processed_at=datetime.fromisoformat(row["last_processed_at"])
                if row.get("last_processed_at")
                else None,
            )
        )
    return stats


@router.get("/jobs", response_model=list[QueueJob], summary="List queue jobs")
async def list_jobs(
    tenant_id: Optional[str] = Query(None),
    connector_id: Optional[str] = Query(None),
    job_status: Optional[str] = Query(None, alias="status"),
    job_type: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    db = get_panel_db()
    sql = "SELECT * FROM queue_jobs WHERE 1=1"
    params: list[Any] = []

    if tenant_id:
        sql += " AND tenant_id = ?"
        params.append(tenant_id)
    if connector_id:
        sql += " AND connector_id = ?"
        params.append(connector_id)
    if job_status:
        sql += " AND status = ?"
        params.append(job_status)
    if job_type:
        sql += " AND job_type = ?"
        params.append(job_type)

    sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db.fetch_all(sql, params)
    return [_row_to_job(r) for r in rows]


@router.get("/dead-letters", response_model=list[QueueJob], summary="List dead-letter queue items")
async def list_dead_letters(
    tenant_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    db = get_panel_db()
    sql = "SELECT * FROM queue_jobs WHERE status = 'dead'"
    params: list[Any] = []
    if tenant_id:
        sql += " AND tenant_id = ?"
        params.append(tenant_id)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    rows = db.fetch_all(sql, params)
    return [_row_to_job(r) for r in rows]


@router.post("/dead-letters/{job_id}/retry", response_model=QueueJob, summary="Retry dead-letter item")
async def retry_dead_letter(job_id: str, tenant_id: str = Query(...)):
    row = _require_job(job_id)
    if row["status"] != JobStatus.DEAD.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_id}' is not in dead-letter queue (status: {row['status']})",
        )
    if row["tenant_id"] != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")

    db = get_panel_db()
    now = utc_now_str()
    db.execute(
        "UPDATE queue_jobs SET status = 'queued', attempts = 0, error = NULL, updated_at = ? WHERE id = ?",
        (now, job_id),
    )
    return _row_to_job(_require_job(job_id))


@router.delete("/dead-letters", response_model=APIResponse, summary="Clear dead-letter queue for tenant")
async def clear_dead_letters(tenant_id: str = Query(...)):
    db = get_panel_db()
    cursor = db.execute(
        "DELETE FROM queue_jobs WHERE status = 'dead' AND tenant_id = ?",
        (tenant_id,),
    )
    return APIResponse(message=f"Cleared {cursor.rowcount} dead-letter jobs for tenant '{tenant_id}'")


@router.get("/jobs/{job_id}", response_model=QueueJob, summary="Get job details")
async def get_job(job_id: str):
    return _row_to_job(_require_job(job_id))


@router.post("/jobs/{job_id}/retry", response_model=QueueJob, summary="Retry a failed job")
async def retry_job(job_id: str):
    row = _require_job(job_id)
    if row["status"] not in (JobStatus.FAILED.value, JobStatus.DEAD.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job '{job_id}' is not in a retryable state (status: {row['status']})",
        )
    db = get_panel_db()
    now = utc_now_str()
    db.execute(
        "UPDATE queue_jobs SET status = 'queued', error = NULL, updated_at = ? WHERE id = ?",
        (now, job_id),
    )
    return _row_to_job(_require_job(job_id))


@router.delete("/jobs/{job_id}", response_model=APIResponse, summary="Cancel/delete a job")
async def cancel_job(job_id: str):
    row = _require_job(job_id)
    if row["status"] == JobStatus.PROCESSING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel a job that is currently processing",
        )
    db = get_panel_db()
    now = utc_now_str()
    db.execute(
        "UPDATE queue_jobs SET status = 'cancelled', updated_at = ? WHERE id = ?",
        (now, job_id),
    )
    return APIResponse(message=f"Job '{job_id}' cancelled")


@router.post(
    "/jobs",
    response_model=QueueJob,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new queue job (admin/testing)",
)
async def create_job(body: QueueJobCreateRequest):
    db = get_panel_db()
    job_id = generate_job_id()
    now = utc_now_str()

    db.execute(
        """
        INSERT INTO queue_jobs
            (id, connector_id, tenant_id, job_type, status, payload_json,
             attempts, max_attempts, error, created_at, updated_at)
        VALUES (?, ?, ?, ?, 'queued', ?, 0, ?, NULL, ?, ?)
        """,
        (
            job_id,
            body.connector_id,
            body.tenant_id,
            body.job_type,
            json.dumps(body.payload),
            body.max_attempts,
            now,
            now,
        ),
    )

    return QueueJob(
        job_id=job_id,
        connector_id=body.connector_id,
        tenant_id=body.tenant_id,
        job_type=body.job_type,
        status=JobStatus.QUEUED,
        payload=body.payload,
        attempts=0,
        max_attempts=body.max_attempts,
        created_at=datetime.fromisoformat(now),
        updated_at=datetime.fromisoformat(now),
    )
