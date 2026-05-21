"""
Workflow Scheduler
==================
Executes scheduled workflows (trigger_type='schedule') according to their
cron expressions. Runs a check every 60 seconds and fires any workflow whose
cron expression matches the current UTC minute.

Cron format: minute hour day month weekday
  Supports: exact value (5), wildcard (*), step (*/15), range (1-5)

Endpoints:
  GET  /workflow-scheduler/status   — scheduler status + upcoming runs
  POST /workflow-scheduler/trigger  — force an immediate schedule evaluation
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR
from backend.core.runtime_control import get_runtime_control

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflow-scheduler", tags=["workflow-scheduler"])

_WORKFLOWS_DB = str(Path(DATA_DIR) / "workflows.db")


# ── Minimal cron evaluator ────────────────────────────────────────────────────

def _field_matches(field: str, value: int, min_v: int, max_v: int) -> bool:
    """Return True if `value` satisfies the cron `field` string."""
    if field == "*":
        return True
    parts = field.split(",")
    for part in parts:
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            start = min_v if base == "*" else int(base.split("-")[0])
            if value >= start and (value - start) % step == 0:
                return True
        elif "-" in part:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
        elif int(part) == value:
            return True
    return False


def cron_matches(expr: str, dt: datetime) -> bool:
    """Return True if cron `expr` fires at datetime `dt` (UTC, minute resolution)."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return False
    minute, hour, day, month, weekday = parts
    return (
        _field_matches(minute,  dt.minute,   0, 59)
        and _field_matches(hour,    dt.hour,     0, 23)
        and _field_matches(day,     dt.day,      1, 31)
        and _field_matches(month,   dt.month,    1, 12)
        and _field_matches(weekday, dt.weekday(), 0, 6)  # 0=Mon … 6=Sun
    )


def next_fire(expr: str, after: datetime) -> Optional[datetime]:
    """Return the next datetime (minute-resolution) when `expr` fires after `after`."""
    dt = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 366):  # up to ~1 year look-ahead
        if cron_matches(expr, dt):
            return dt
        dt += timedelta(minutes=1)
    return None


# ── DB helper ─────────────────────────────────────────────────────────────────

def _get_scheduled_workflows() -> List[Dict[str, Any]]:
    """Return all active workflows whose trigger_type is 'schedule'."""
    try:
        con = sqlite3.connect(_WORKFLOWS_DB, timeout=10, check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """SELECT id, name, trigger_cfg, steps_json
               FROM workflows
               WHERE is_active=1 AND trigger_type='schedule' LIMIT 10000"""
        ).fetchall()
        con.close()
        result = []
        for r in rows:
            try:
                cfg = json.loads(r["trigger_cfg"] or "{}")
                result.append({
                    "id":        r["id"],
                    "name":      r["name"],
                    "cron":      cfg.get("cron", ""),
                    "steps":     json.loads(r["steps_json"] or "[]"),
                    "cfg":       cfg,
                })
            except Exception:
                pass
        return result
    except Exception as exc:
        logger.debug("WorkflowScheduler: DB read failed: %s", exc)
        return []


# ── Scheduler ─────────────────────────────────────────────────────────────────

class WorkflowScheduler:
    """
    Checks every 60 seconds whether any scheduled workflow should fire.
    Maintains a last-fired registry so the same minute is never double-fired.
    """

    CHECK_INTERVAL_S = 60

    def __init__(self) -> None:
        self._running   = False
        self._task:      Optional[asyncio.Task] = None
        self._fired:     Dict[str, str] = {}   # wf_id → last-fired minute ISO
        self._run_count  = 0
        self._last_check: Optional[str] = None
        self._triggered: List[Dict[str, Any]] = []  # ring buffer, last 100

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("WorkflowScheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("WorkflowScheduler error: %s", exc)
            try:
                await asyncio.sleep(self.CHECK_INTERVAL_S)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        self._run_count += 1
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        minute_key = now.isoformat()
        self._last_check = minute_key

        workflows = _get_scheduled_workflows()
        for wf in workflows:
            cron = wf.get("cron", "")
            if not cron:
                continue
            # Skip if already fired this minute
            if self._fired.get(wf["id"]) == minute_key:
                continue
            try:
                if cron_matches(cron, now):
                    self._fired[wf["id"]] = minute_key
                    await self._fire(wf, now)
            except Exception as exc:
                logger.debug("WorkflowScheduler: cron check error for %s: %s", wf["id"], exc)

    async def _fire(self, wf: Dict[str, Any], fired_at: datetime) -> None:
        wf_id = wf["id"]
        name  = wf["name"]
        try:
            from backend.api.workflows import _engine, _conn, _now
            import uuid

            exec_id = str(uuid.uuid4())
            steps   = wf["steps"]
            now_s   = _now()

            with _conn() as con:
                con.execute(
                    """INSERT INTO workflow_executions
                       (id, workflow_id, trigger_type, status, step_count,
                        steps_done, input_data, output_data, created_at)
                       VALUES (?,?,'schedule','pending',?,0,?,'{}',?)""",
                    (exec_id, wf_id, len(steps), json.dumps({"fired_at": fired_at.isoformat()}), now_s),
                )
                con.commit()

            async def _run():
                try:
                    await _engine.execute(
                        workflow_id=wf_id,
                        execution_id=exec_id,
                        steps=steps,
                        input_data={"fired_at": fired_at.isoformat()},
                        trigger_type="schedule",
                    )
                except Exception as exc:
                    logger.error("Scheduled workflow %s execution failed: %s", wf_id, exc)

            asyncio.create_task(_run())

            entry = {
                "workflow_id":   wf_id,
                "workflow_name": name,
                "execution_id":  exec_id,
                "cron":          wf["cron"],
                "fired_at":      fired_at.isoformat(),
            }
            self._triggered.append(entry)
            if len(self._triggered) > 100:
                self._triggered.pop(0)

            logger.info("WorkflowScheduler: fired '%s' (exec=%s)", name, exec_id[:8])

            try:
                from backend.api.event_bus import emit
                asyncio.create_task(emit(
                    "workflow.scheduled_fire",
                    source="workflow_scheduler",
                    payload={"workflow_id": wf_id, "workflow_name": name, "execution_id": exec_id, "cron": wf["cron"]},
                    severity="low",
                ))
            except Exception:
                pass

        except Exception as exc:
            logger.error("WorkflowScheduler: fire failed for %s: %s", wf_id, exc)

    def status(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        workflows = _get_scheduled_workflows()
        upcoming = []
        for wf in workflows:
            cron = wf.get("cron", "")
            if not cron:
                continue
            nf = next_fire(cron, now)
            upcoming.append({
                "workflow_id":   wf["id"],
                "workflow_name": wf["name"],
                "cron":          cron,
                "next_fire":     nf.isoformat() if nf else None,
                "minutes_until": int((nf - now).total_seconds() / 60) if nf else None,
            })
        upcoming.sort(key=lambda x: x["next_fire"] or "")
        return {
            "running":          self._running,
            "run_count":        self._run_count,
            "last_check":       self._last_check,
            "scheduled_workflows": len(workflows),
            "upcoming":         upcoming[:10],
            "recently_fired":   list(reversed(self._triggered[-10:])),
        }


# ── Module singleton ──────────────────────────────────────────────────────────

_scheduler = WorkflowScheduler()


def get_workflow_scheduler() -> WorkflowScheduler:
    return _scheduler


async def ensure_scheduler_running() -> None:
    if not get_runtime_control().is_service_enabled("workflow_scheduler"):
        logger.info("WorkflowScheduler disabled by runtime policy")
        return
    await _scheduler.start()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status", summary="Workflow scheduler status and upcoming runs")
async def scheduler_status(_auth=Depends(require_local_auth)):
    return _scheduler.status()


@router.post("/trigger", summary="Force an immediate schedule evaluation")
async def force_evaluation(_auth=Depends(require_local_auth)):
    asyncio.create_task(_scheduler._tick())
    return {"ok": True, "message": "Schedule evaluation dispatched."}
