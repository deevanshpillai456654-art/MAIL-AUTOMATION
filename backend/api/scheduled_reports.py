"""
Scheduled Reports (Dispatches)
================================
Generates periodic operational digests from live platform data and
delivers them to configured webhook endpoints or stores them locally.

Every enabled report config is evaluated on a 5-minute check cycle.
When next_run ≤ now the report is generated, written to report_runs,
and optionally POSTed to a webhook URL.

Report sections (all optional, comma-separated in config.sections):
  platform_health   — current metric snapshot + alert flag
  incidents         — open/acknowledged counts + critical list
  alert_rules       — rule count, recent breaches
  metric_trends     — 24h sparkline summary (min/max/last/count)
  audit_summary     — top event types in last 24h

Tables:
  report_configs  — per-config schedule and delivery settings
  report_runs     — run history with JSON report content (max 50/config)

Endpoints:
  GET    /scheduled-reports                     — list configs
  POST   /scheduled-reports                     — create config
  GET    /scheduled-reports/scheduler/status    — scheduler status
  GET    /scheduled-reports/runs                — recent runs (all configs)
  GET    /scheduled-reports/runs/{run_id}       — run detail + content
  GET    /scheduled-reports/{config_id}         — config detail
  PATCH  /scheduled-reports/{config_id}         — update config
  DELETE /scheduled-reports/{config_id}         — delete config
  POST   /scheduled-reports/{config_id}/run     — manual trigger
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR
from backend.core.runtime_control import get_runtime_control

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/scheduled-reports", tags=["scheduled-reports"])

_DB_PATH = str(Path(DATA_DIR) / "scheduled_reports.db")
_SECTIONS = ["platform_health", "incidents", "alert_rules", "metric_trends", "audit_summary"]
_DEFAULT_SECTIONS = ",".join(_SECTIONS)

_CONFIG_COLS = [
    "id", "name", "interval_hours", "sections", "delivery",
    "webhook_url", "enabled", "last_run", "next_run", "created_at",
]
_RUN_COLS = [
    "id", "config_id", "config_name", "generated_at",
    "status", "error_msg", "content", "delivered",
]


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS report_configs (
            id             TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            interval_hours INTEGER NOT NULL DEFAULT 24,
            sections       TEXT NOT NULL,
            delivery       TEXT NOT NULL DEFAULT 'store',
            webhook_url    TEXT NOT NULL DEFAULT '',
            enabled        INTEGER NOT NULL DEFAULT 1,
            last_run       TEXT,
            next_run       TEXT NOT NULL,
            created_at     TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS report_runs (
            id           TEXT PRIMARY KEY,
            config_id    TEXT NOT NULL,
            config_name  TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            status       TEXT NOT NULL DEFAULT 'ok',
            error_msg    TEXT NOT NULL DEFAULT '',
            content      TEXT NOT NULL DEFAULT '',
            delivered    INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_rc_enabled  ON report_configs (enabled);
        CREATE INDEX IF NOT EXISTS idx_rc_next     ON report_configs (next_run);
        CREATE INDEX IF NOT EXISTS idx_rr_config
            ON report_runs (config_id, generated_at DESC);
    """)
    con.commit()
    con.close()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_run_from_now(interval_hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=interval_hours)).isoformat()


# ── Data collectors ───────────────────────────────────────────────────────────

def _collect_platform_health() -> dict:
    try:
        from backend.api.alert_rules import _collect_metrics
        metrics = _collect_metrics()
        alert = metrics.get("active_threats", 0) >= 10
        return {"metrics": metrics, "alert": alert}
    except Exception as exc:
        logger.debug("ScheduledReports: platform_health collection failed: %s", exc)
        return {"metrics": {}, "alert": False}


def _collect_incidents_section() -> dict:
    try:
        from backend.api.incidents import _DB_PATH as INC_DB
        con = sqlite3.connect(INC_DB, timeout=5)
        by_status = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT status, COUNT(*) FROM incidents GROUP BY status"
            ).fetchall()
        }
        critical_open = [
            {"id": r[0], "title": r[1], "severity": r[2], "created_at": r[3]}
            for r in con.execute(
                "SELECT id, title, severity, created_at FROM incidents "
                "WHERE status IN ('open','acknowledged') AND severity IN ('critical','high') "
                "ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
        ]
        con.close()
        return {
            "by_status":    by_status,
            "critical_open": critical_open,
            "total": sum(by_status.values()),
        }
    except Exception as exc:
        logger.debug("ScheduledReports: incidents collection failed: %s", exc)
        return {"by_status": {}, "critical_open": [], "total": 0}


def _collect_alert_rules_section() -> dict:
    try:
        from backend.api.alert_rules import _DB_PATH as AR_DB
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        con = sqlite3.connect(AR_DB, timeout=5)
        total   = con.execute("SELECT COUNT(*) FROM alert_rules").fetchone()[0]
        active  = con.execute("SELECT COUNT(*) FROM alert_rules WHERE is_active=1").fetchone()[0]
        breached_24h = con.execute(
            "SELECT COUNT(*) FROM alert_rule_state WHERE last_breach >= ?", (cutoff,)
        ).fetchone()[0]
        recent = [
            {"rule_id": r[0], "last_breach": r[1], "breach_count": r[2], "last_value": r[3]}
            for r in con.execute(
                "SELECT rule_id, last_breach, breach_count, last_value "
                "FROM alert_rule_state WHERE last_breach >= ? ORDER BY last_breach DESC LIMIT 5",
                (cutoff,),
            ).fetchall()
        ]
        con.close()
        return {
            "total": total, "active": active,
            "breached_24h": breached_24h, "recent_breaches": recent,
        }
    except Exception as exc:
        logger.debug("ScheduledReports: alert_rules collection failed: %s", exc)
        return {"total": 0, "active": 0, "breached_24h": 0, "recent_breaches": []}


def _collect_metric_trends_section() -> dict:
    try:
        from backend.api.metric_snapshots import _sparkline_data
        raw = _sparkline_data(hours=24)
        return {
            k: {
                "last":  v[-1] if v else None,
                "min":   min(v) if v else None,
                "max":   max(v) if v else None,
                "count": len(v),
            }
            for k, v in raw.items()
        }
    except Exception as exc:
        logger.debug("ScheduledReports: metric_trends collection failed: %s", exc)
        return {}


def _collect_audit_summary_section() -> dict:
    try:
        from backend.api.audit_log import _DB_PATH as AL_DB
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        con = sqlite3.connect(AL_DB, timeout=5)
        total_24h = con.execute(
            "SELECT COUNT(*) FROM audit_entries WHERE ts >= ?", (cutoff,)
        ).fetchone()[0]
        top_types = [
            {"event_type": r[0], "count": r[1]}
            for r in con.execute(
                "SELECT event_type, COUNT(*) c FROM audit_entries "
                "WHERE ts >= ? GROUP BY event_type ORDER BY c DESC LIMIT 8",
                (cutoff,),
            ).fetchall()
        ]
        by_severity = {
            r[0]: r[1]
            for r in con.execute(
                "SELECT severity, COUNT(*) FROM audit_entries WHERE ts >= ? GROUP BY severity",
                (cutoff,),
            ).fetchall()
        }
        con.close()
        return {
            "total_24h": total_24h,
            "by_severity": by_severity,
            "top_event_types": top_types,
        }
    except Exception as exc:
        logger.debug("ScheduledReports: audit_summary collection failed: %s", exc)
        return {"total_24h": 0, "by_severity": {}, "top_event_types": []}


async def _generate_report_content(config_name: str, sections: list[str]) -> dict:
    content: dict[str, Any] = {
        "generated_at": _now(),
        "config_name":  config_name,
        "sections":     {},
    }
    collectors = {
        "platform_health": _collect_platform_health,
        "incidents":       _collect_incidents_section,
        "alert_rules":     _collect_alert_rules_section,
        "metric_trends":   _collect_metric_trends_section,
        "audit_summary":   _collect_audit_summary_section,
    }
    for section in sections:
        fn = collectors.get(section)
        if fn:
            try:
                content["sections"][section] = fn()
            except Exception as exc:
                content["sections"][section] = {"error": str(exc)}
    return content


# ── Webhook delivery ──────────────────────────────────────────────────────────

async def _post_webhook(url: str, payload: dict) -> bool:
    """POST JSON report to a webhook URL. Returns True on 2xx."""
    try:
        import hmac as hmaclib
        import hashlib
        body = json.dumps(payload).encode()
        sig = "sha256=" + hmaclib.new(b"", body, hashlib.sha256).hexdigest()
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    url, content=body,
                    headers={"Content-Type": "application/json",
                             "X-Intemo-Signature": sig},
                )
                return resp.status_code < 400
        except ImportError:
            import urllib.request
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json",
                         "X-Intemo-Signature": sig},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status < 400
    except Exception as exc:
        logger.warning("ScheduledReports: webhook delivery failed: %s", exc)
        return False


# ── Run execution ─────────────────────────────────────────────────────────────

async def _run_config(config: dict) -> str:
    run_id = str(uuid.uuid4())
    sections = [s.strip() for s in config["sections"].split(",") if s.strip()]
    status = "ok"
    error_msg = ""
    content_json = ""
    delivered = False

    try:
        content = await _generate_report_content(config["name"], sections)
        content_json = json.dumps(content)
        if config["delivery"] == "webhook" and config["webhook_url"]:
            delivered = await _post_webhook(config["webhook_url"], content)
        else:
            delivered = True
    except Exception as exc:
        status = "error"
        error_msg = str(exc)
        logger.error("ScheduledReports: run failed for '%s': %s", config["name"], exc)

    now = _now()
    next_run = _next_run_from_now(config["interval_hours"])
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO report_runs ({','.join(_RUN_COLS)}) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, config["id"], config["name"], now,
             status, error_msg, content_json, 1 if delivered else 0),
        )
        con.execute(
            "UPDATE report_configs SET last_run=?, next_run=? WHERE id=?",
            (now, next_run, config["id"]),
        )
        # Keep at most 50 runs per config
        con.execute(
            """DELETE FROM report_runs WHERE config_id=? AND id NOT IN (
               SELECT id FROM report_runs WHERE config_id=?
               ORDER BY generated_at DESC LIMIT 50)""",
            (config["id"], config["id"]),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.error("ScheduledReports: failed to write run record: %s", exc)

    return run_id


# ── Background scheduler ──────────────────────────────────────────────────────

class ReportScheduler:
    INTERVAL_S = 300  # Check every 5 minutes

    def __init__(self) -> None:
        self._running     = False
        self._task: Optional[asyncio.Task] = None
        self._run_count   = 0
        self._last_check: Optional[str] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("ReportScheduler started (interval=%ds)", self.INTERVAL_S)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._check()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ReportScheduler error: %s", exc)
            try:
                await asyncio.sleep(self.INTERVAL_S)
            except asyncio.CancelledError:
                break

    async def _check(self) -> None:
        now = _now()
        self._last_check = now
        try:
            con = _conn()
            rows = con.execute(
                f"SELECT {','.join(_CONFIG_COLS)} FROM report_configs "
                "WHERE enabled=1 AND next_run <= ?",
                (now,),
            ).fetchall()
            con.close()
        except Exception as exc:
            logger.debug("ReportScheduler: check failed: %s", exc)
            return
        for row in rows:
            config = dict(zip(_CONFIG_COLS, row))
            try:
                await _run_config(config)
                self._run_count += 1
            except Exception as exc:
                logger.error("ReportScheduler: config '%s' failed: %s", config["name"], exc)

    def status(self) -> dict:
        return {
            "running":     self._running,
            "run_count":   self._run_count,
            "last_check":  self._last_check,
            "interval_s":  self.INTERVAL_S,
        }


_scheduler = ReportScheduler()


async def ensure_report_scheduler_running() -> None:
    if not get_runtime_control().is_service_enabled("scheduled_reports"):
        logger.info("ReportScheduler disabled by runtime policy")
        return
    _init_db()
    await _scheduler.start()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ConfigCreate(BaseModel):
    name:           str
    interval_hours: int   = 24
    sections:       str   = _DEFAULT_SECTIONS
    delivery:       str   = "store"
    webhook_url:    str   = ""
    enabled:        bool  = True


class ConfigPatch(BaseModel):
    name:           Optional[str]  = None
    interval_hours: Optional[int]  = None
    sections:       Optional[str]  = None
    delivery:       Optional[str]  = None
    webhook_url:    Optional[str]  = None
    enabled:        Optional[bool] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="List report configs")
async def list_configs(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        rows = con.execute(
            f"SELECT {','.join(_CONFIG_COLS)} FROM report_configs ORDER BY created_at DESC"
        ).fetchall()
        con.close()
    except Exception:
        return {"configs": []}
    return {"configs": [dict(zip(_CONFIG_COLS, r)) for r in rows]}


@router.post("", status_code=201, summary="Create report config")
async def create_config(body: ConfigCreate, _auth=Depends(require_local_auth)):
    if body.interval_hours < 1 or body.interval_hours > 8760:
        raise HTTPException(400, "interval_hours must be 1–8760")
    unknown = [s for s in body.sections.split(",") if s.strip() and s.strip() not in _SECTIONS]
    if unknown:
        raise HTTPException(400, f"Unknown sections: {unknown}. Valid: {_SECTIONS}")

    cfg_id = str(uuid.uuid4())
    now = _now()
    next_run = _next_run_from_now(body.interval_hours)
    row = (
        cfg_id, body.name, body.interval_hours, body.sections,
        body.delivery, body.webhook_url, 1 if body.enabled else 0,
        None, next_run, now,
    )
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO report_configs ({','.join(_CONFIG_COLS)}) VALUES ({','.join(['?']*len(_CONFIG_COLS))})",
            row,
        )
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"id": cfg_id, "name": body.name, "next_run": next_run}


# ── Sub-routes that must appear BEFORE /{config_id} ──────────────────────────

@router.get("/scheduler/status", summary="Report scheduler status")
async def scheduler_status(_auth=Depends(require_local_auth)):
    return _scheduler.status()


@router.get("/runs", summary="Recent report runs (all configs)")
async def list_runs(
    limit:  int           = Query(50, ge=1, le=500),
    offset: int           = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        total = con.execute("SELECT COUNT(*) FROM report_runs").fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_RUN_COLS)} FROM report_runs "
            "ORDER BY generated_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        con.close()
    except Exception:
        return {"runs": [], "total": 0}
    runs = [dict(zip(_RUN_COLS, r)) for r in rows]
    for r in runs:
        r.pop("content", None)  # Omit content from list view
    return {"runs": runs, "total": total, "limit": limit, "offset": offset}


@router.get("/runs/{run_id}", summary="Run detail with report content")
async def get_run(run_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_RUN_COLS)} FROM report_runs WHERE id=?", (run_id,)
        ).fetchone()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if not row:
        raise HTTPException(404, "Run not found")
    run = dict(zip(_RUN_COLS, row))
    if run.get("content"):
        try:
            run["content"] = json.loads(run["content"])
        except Exception:
            pass
    return run


# ── Config-specific routes ────────────────────────────────────────────────────

@router.get("/{config_id}", summary="Config detail")
async def get_config(config_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_CONFIG_COLS)} FROM report_configs WHERE id=?", (config_id,)
        ).fetchone()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if not row:
        raise HTTPException(404, "Config not found")
    return dict(zip(_CONFIG_COLS, row))


@router.patch("/{config_id}", summary="Update report config")
async def patch_config(
    config_id: str, body: ConfigPatch, _auth=Depends(require_local_auth)
):
    updates, params = [], []
    if body.name is not None:
        updates.append("name = ?"); params.append(body.name)
    if body.interval_hours is not None:
        if body.interval_hours < 1 or body.interval_hours > 8760:
            raise HTTPException(400, "interval_hours must be 1–8760")
        updates.append("interval_hours = ?"); params.append(body.interval_hours)
        updates.append("next_run = ?");        params.append(_next_run_from_now(body.interval_hours))
    if body.sections is not None:
        unknown = [s for s in body.sections.split(",") if s.strip() and s.strip() not in _SECTIONS]
        if unknown:
            raise HTTPException(400, f"Unknown sections: {unknown}")
        updates.append("sections = ?"); params.append(body.sections)
    if body.delivery is not None:
        updates.append("delivery = ?"); params.append(body.delivery)
    if body.webhook_url is not None:
        updates.append("webhook_url = ?"); params.append(body.webhook_url)
    if body.enabled is not None:
        updates.append("enabled = ?"); params.append(1 if body.enabled else 0)
    if not updates:
        raise HTTPException(400, "No fields to update")
    params.append(config_id)
    try:
        con = _conn()
        con.execute(f"UPDATE report_configs SET {', '.join(updates)} WHERE id=?", params)
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close()
            raise HTTPException(404, "Config not found")
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, str(exc))
    return {"ok": True}


@router.delete("/{config_id}", status_code=204, summary="Delete report config")
async def delete_config(config_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("DELETE FROM report_runs WHERE config_id=?", (config_id,))
        con.execute("DELETE FROM report_configs WHERE id=?", (config_id,))
        con.commit()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))


@router.post("/{config_id}/run", summary="Trigger an immediate report run")
async def trigger_run(config_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_CONFIG_COLS)} FROM report_configs WHERE id=?", (config_id,)
        ).fetchone()
        con.close()
    except Exception as exc:
        raise HTTPException(500, str(exc))
    if not row:
        raise HTTPException(404, "Config not found")
    config = dict(zip(_CONFIG_COLS, row))
    run_id = await _run_config(config)
    return {"ok": True, "run_id": run_id}
