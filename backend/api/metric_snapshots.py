"""
Metric Snapshots
================
Hourly time-series capture of key platform metrics.  Gives operators
historical context — "is 15 active threats unusual?" — by storing a
lightweight snapshot every hour and exposing a query API.

The snapshot background task reuses the same metric collectors as the
platform telemetry endpoint so values are always consistent.

Metrics captured every hour:
  active_threats, health_score, workflow_success_rate,
  running_agents, emails_last_1h, scam_last_24h

Endpoints:
  GET /metric-snapshots/history         — time-series for one or all metrics
  GET /metric-snapshots/sparklines      — compact 24h sparkline data for UI
  GET /metric-snapshots/status          — recorder status
  POST /metric-snapshots/record         — force an immediate snapshot
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR
from backend.core.runtime_control import get_runtime_control

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/metric-snapshots", tags=["metric-snapshots"])

_DB_PATH = str(Path(DATA_DIR) / "metric_snapshots.db")

_METRICS = [
    "active_threats",
    "health_score",
    "workflow_success_rate",
    "running_agents",
    "emails_last_1h",
    "scam_last_24h",
]


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS metric_snapshots (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            metric     TEXT NOT NULL,
            value      REAL NOT NULL,
            recorded_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ms_metric_time
            ON metric_snapshots (metric, recorded_at DESC);
    """)
    # Prune records older than 30 days on init
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    con.execute("DELETE FROM metric_snapshots WHERE recorded_at < ?", (cutoff,))
    con.commit()
    con.close()


def _conn() -> sqlite3.Connection:
    from backend.utils.sqlite_connection_guard import connect_with_defaults
    return connect_with_defaults(_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Snapshot collector ────────────────────────────────────────────────────────

def _take_snapshot() -> Dict[str, float]:
    """Collect current metric values using the alert_rules collectors."""
    try:
        from backend.api.alert_rules import _collect_metrics
        return _collect_metrics()
    except Exception as exc:
        logger.debug("MetricSnapshots: metric collection failed: %s", exc)
        return {}


def _write_snapshot(metrics: Dict[str, float]) -> None:
    now_s = _now()
    try:
        con = _conn()
        con.executemany(
            "INSERT INTO metric_snapshots (metric, value, recorded_at) VALUES (?,?,?)",
            [(k, v, now_s) for k, v in metrics.items() if k in _METRICS],
        )
        # Keep at most 720 records per metric (30 days × 24 h)
        for metric in _METRICS:
            con.execute(
                """DELETE FROM metric_snapshots WHERE metric=? AND id NOT IN (
                       SELECT id FROM metric_snapshots
                       WHERE metric=? ORDER BY recorded_at DESC LIMIT 720)""",
                (metric, metric),
            )
        con.commit()
        con.close()
    except Exception as exc:
        logger.debug("MetricSnapshots: write failed: %s", exc)


# ── Background recorder ───────────────────────────────────────────────────────

class MetricRecorder:
    INTERVAL_S = 3600   # hourly

    def __init__(self) -> None:
        self._running    = False
        self._task: Optional[asyncio.Task] = None
        self._run_count  = 0
        self._last_record: Optional[str] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("MetricRecorder started (interval=%ds)", self.INTERVAL_S)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        # Take an immediate first snapshot on startup
        try:
            await self._record()
        except Exception:
            pass
        while self._running:
            try:
                await asyncio.sleep(self.INTERVAL_S)
            except asyncio.CancelledError:
                break
            try:
                await self._record()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("MetricRecorder error: %s", exc)

    async def _record(self) -> None:
        metrics = _take_snapshot()
        if metrics:
            _write_snapshot(metrics)
            self._run_count += 1
            self._last_record = _now()

    def status(self) -> Dict[str, Any]:
        return {
            "running":     self._running,
            "run_count":   self._run_count,
            "last_record": self._last_record,
            "interval_s":  self.INTERVAL_S,
            "metrics":     _METRICS,
        }


# ── Module singleton ──────────────────────────────────────────────────────────

_recorder = MetricRecorder()


def get_recorder() -> MetricRecorder:
    return _recorder


async def ensure_metric_recorder_running() -> None:
    if not get_runtime_control().is_service_enabled("metric_snapshots"):
        logger.info("MetricRecorder disabled by runtime policy")
        return
    _init_db()
    await _recorder.start()


# ── Query helpers ─────────────────────────────────────────────────────────────

def _query_history(metric: str, hours: int) -> List[Dict[str, Any]]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    try:
        con = _conn()
        rows = con.execute(
            """SELECT recorded_at, value FROM metric_snapshots
               WHERE metric=? AND recorded_at >= ?
               ORDER BY recorded_at ASC LIMIT 10000""",
            (metric, cutoff),
        ).fetchall()
        con.close()
        return [{"ts": r[0], "value": r[1]} for r in rows]
    except Exception:
        return []


def _sparkline_data(hours: int = 24) -> Dict[str, List[float]]:
    """Return a compact list of values (oldest → newest) for each metric."""
    result = {}
    for metric in _METRICS:
        pts = _query_history(metric, hours)
        result[metric] = [p["value"] for p in pts]
    return result


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/history", summary="Time-series history for one or all metrics")
async def metric_history(
    metric: Optional[str] = Query(None, description="Metric name; omit for all"),
    hours:  int           = Query(24, ge=1, le=720, description="Look-back window in hours"),
    _auth=Depends(require_local_auth),
):
    metrics_to_query = [metric] if metric else _METRICS
    result = {}
    for m in metrics_to_query:
        if m in _METRICS:
            result[m] = _query_history(m, hours)
    return {"history": result, "hours": hours}


@router.get("/sparklines", summary="Compact 24h sparkline values for dashboard UI")
async def sparklines(
    hours: int = Query(24, ge=1, le=168),
    _auth=Depends(require_local_auth),
):
    data = _sparkline_data(hours)
    # Include min/max/last for each metric so the UI can scale the sparkline
    summary = {}
    for metric, values in data.items():
        if values:
            summary[metric] = {
                "values": values,
                "min":    min(values),
                "max":    max(values),
                "last":   values[-1],
                "count":  len(values),
            }
        else:
            summary[metric] = {"values": [], "min": 0, "max": 0, "last": 0, "count": 0}
    return {"sparklines": summary, "hours": hours}


@router.get("/status", summary="Metric recorder status")
async def recorder_status(_auth=Depends(require_local_auth)):
    return _recorder.status()


@router.post("/record", summary="Force an immediate metric snapshot")
async def force_record(_auth=Depends(require_local_auth)):
    asyncio.create_task(_recorder._record())
    return {"ok": True, "message": "Snapshot dispatched."}
