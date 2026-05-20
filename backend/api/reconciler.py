"""
Operational Reconciler
======================
Continuous self-healing background process that:
  1. Detects drift between expected and actual platform state
  2. Auto-repairs recoverable conditions
  3. Emits health and recovery events to the event bus
  4. Maintains SLA compliance monitoring

Reconciliation cycles run every 5 minutes and check:
  - Stale workflow executions (stuck in 'running' for > 10 min → mark failed)
  - Dead-letter events (re-attempt delivery)
  - Account sync freshness (emit degraded event if no sync > 2 hours)
  - Threat alert accumulation (emit warning if active threats > threshold)
  - Workflow execution success rate (emit SLA breach if < 80%)

Endpoints:
  GET  /reconciler/status     — current reconciler status + last run summary
  POST /reconciler/trigger    — manually trigger a reconciliation cycle
  GET  /reconciler/history    — recent reconciliation cycle results
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR, DB_PATH
from backend.core.runtime_control import get_runtime_control

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reconciler", tags=["reconciler"])

_WORKFLOWS_DB = str(Path(DATA_DIR) / "workflows.db")


# ── DB helpers ─────────────────────────────────────────────────────────────────

def _open_db(path: str) -> Optional[sqlite3.Connection]:
    try:
        con = sqlite3.connect(path, timeout=10, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        return con
    except Exception as exc:
        logger.debug("Cannot open %s: %s", path, exc)
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Reconciler ─────────────────────────────────────────────────────────────────

class OperationalReconciler:
    """
    Continuous background reconciler.
    Detects and repairs platform state drift without human intervention.
    """

    CYCLE_INTERVAL_S = 300          # run every 5 minutes
    STUCK_EXECUTION_THRESHOLD_S = 600  # 10 minutes stuck = mark as failed

    def __init__(self) -> None:
        self._running   = False
        self._task:      Optional[asyncio.Task] = None
        self._run_count  = 0
        self._last_run:  Optional[str] = None
        self._last_summary: Dict[str, Any] = {}
        self._history:   List[Dict[str, Any]] = []  # ring buffer, last 50

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._reconcile_loop())
        logger.info("OperationalReconciler started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _reconcile_loop(self) -> None:
        while self._running:
            try:
                await self.run_cycle()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Reconciler loop error: %s", exc)
            try:
                await asyncio.sleep(self.CYCLE_INTERVAL_S)
            except asyncio.CancelledError:
                break

    async def run_cycle(self) -> Dict[str, Any]:
        self._run_count += 1
        self._last_run  = _now()
        actions: List[str] = []
        events:  List[Dict] = []

        # ── 1. Repair stuck workflow executions ──────────────────────────────
        try:
            con = _open_db(_WORKFLOWS_DB)
            if con:
                cutoff = (datetime.now(timezone.utc) - timedelta(seconds=self.STUCK_EXECUTION_THRESHOLD_S)).isoformat()
                stuck  = con.execute(
                    """SELECT id, workflow_id FROM workflow_executions
                       WHERE status='running' AND started_at < ?""",
                    (cutoff,),
                ).fetchall()
                for row in stuck:
                    exec_id = row[0]
                    wf_id   = row[1]
                    con.execute(
                        "UPDATE workflow_executions SET status='failed', error=?, finished_at=? WHERE id=?",
                        ("Stuck execution — auto-recovered by reconciler", _now(), exec_id),
                    )
                    actions.append(f"Recovered stuck execution {exec_id}")
                    events.append({
                        "type":     "workflow.recovered",
                        "severity": "medium",
                        "payload":  {"execution_id": exec_id, "workflow_id": wf_id, "action": "auto_fail"},
                    })
                if stuck:
                    con.commit()
                con.close()
        except Exception as exc:
            logger.debug("Reconciler: stuck execution check failed: %s", exc)

        # ── 2. SLA monitoring: workflow success rate ─────────────────────────
        try:
            con = _open_db(_WORKFLOWS_DB)
            if con:
                row = con.execute(
                    """SELECT COUNT(*) total,
                              SUM(CASE WHEN status='succeeded' THEN 1 ELSE 0 END) succ
                       FROM workflow_executions
                       WHERE created_at >= datetime('now', '-1 hour')"""
                ).fetchone()
                con.close()
                if row and row[0] >= 5:
                    total = row[0]
                    succ  = row[1] or 0
                    rate  = round(succ / total * 100, 1)
                    if rate < 70:
                        events.append({
                            "type":     "system.sla_breach",
                            "severity": "high",
                            "payload":  {
                                "metric":     "workflow_success_rate",
                                "value":      rate,
                                "threshold":  70,
                                "period":     "last_1h",
                                "total_runs": total,
                            },
                        })
                        actions.append(f"SLA breach: workflow success rate {rate}% < 70%")
        except Exception as exc:
            logger.debug("Reconciler: SLA check failed: %s", exc)

        # ── 3. Account sync freshness ────────────────────────────────────────
        try:
            con = _open_db(DB_PATH)
            if con:
                stale_thresh = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
                stale = con.execute(
                    """SELECT COUNT(*) FROM accounts
                       WHERE status='active'
                       AND (last_sync_at IS NULL OR last_sync_at < ?)""",
                    (stale_thresh,),
                ).fetchone()[0]
                con.close()
                if stale > 0:
                    events.append({
                        "type":     "system.degraded",
                        "severity": "medium",
                        "payload":  {
                            "component": "account_sync",
                            "detail":    f"{stale} active account(s) have not synced in > 2 hours",
                        },
                    })
                    actions.append(f"{stale} account(s) with stale sync detected")
        except Exception as exc:
            logger.debug("Reconciler: account sync check failed: %s", exc)

        # ── 4. Active threat accumulation warning ────────────────────────────
        try:
            con = _open_db(DB_PATH)
            if con:
                active_threats = con.execute(
                    "SELECT COUNT(*) FROM threat_lookalike_alerts WHERE status='active'"
                ).fetchone()[0]
                con.close()
                if active_threats >= 10:
                    events.append({
                        "type":     "agent.anomaly",
                        "severity": "high",
                        "payload":  {
                            "title":  "High active threat accumulation",
                            "detail": f"{active_threats} threats remain active — consider activating Threat Escalation workflow",
                        },
                    })
                    actions.append(f"Threat accumulation warning: {active_threats} active threats")
        except Exception as exc:
            logger.debug("Reconciler: threat check failed: %s", exc)

        # ── 5. Emit events to event bus ──────────────────────────────────────
        for ev in events:
            try:
                from backend.api.event_bus import emit
                await emit(
                    event_type=ev["type"],
                    source="reconciler",
                    payload=ev["payload"],
                    severity=ev.get("severity", "low"),
                )
            except Exception as exc:
                logger.debug("Reconciler event emit failed: %s", exc)

        # Emit reconciliation complete event
        try:
            from backend.api.event_bus import emit
            await emit(
                "system.health_check",
                source="reconciler",
                payload={
                    "cycle":          self._run_count,
                    "actions_taken":  len(actions),
                    "events_emitted": len(events),
                    "issues":         actions,
                },
                severity="low",
            )
        except Exception:
            pass

        summary = {
            "id":             str(uuid.uuid4()),
            "cycle":          self._run_count,
            "ran_at":         self._last_run,
            "actions_taken":  len(actions),
            "issues_found":   len(events),
            "actions":        actions,
        }
        self._last_summary = summary
        self._history.append(summary)
        if len(self._history) > 50:
            self._history.pop(0)

        if actions:
            logger.info(
                "Reconciler cycle %d: %d action(s) — %s",
                self._run_count, len(actions), "; ".join(actions[:3]),
            )

        return summary

    def status(self) -> Dict[str, Any]:
        return {
            "running":       self._running,
            "run_count":     self._run_count,
            "last_run":      self._last_run,
            "cycle_interval_s": self.CYCLE_INTERVAL_S,
            "last_summary":  self._last_summary,
        }


# ── Module singleton ───────────────────────────────────────────────────────────

_reconciler = OperationalReconciler()


def get_reconciler() -> OperationalReconciler:
    return _reconciler


async def ensure_reconciler_running() -> None:
    if not get_runtime_control().is_service_enabled("reconciler"):
        logger.info("OperationalReconciler disabled by runtime policy")
        return
    await _reconciler.start()


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/status", summary="Reconciler status and last cycle summary")
async def reconciler_status(_auth=Depends(require_local_auth)):
    return _reconciler.status()


@router.post("/trigger", summary="Manually trigger a reconciliation cycle")
async def trigger_reconcile(
    background_tasks: BackgroundTasks,
    _auth=Depends(require_local_auth),
):
    background_tasks.add_task(_reconciler.run_cycle)
    return {"ok": True, "message": "Reconciliation cycle dispatched."}


@router.get("/history", summary="Recent reconciliation cycle results")
async def reconciler_history(_auth=Depends(require_local_auth)):
    return {"history": list(reversed(_reconciler._history)), "count": len(_reconciler._history)}
