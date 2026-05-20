"""
Alert Rules Engine
==================
Configurable threshold-based alerting that closes the monitoring loop:
  Telemetry → Rules → Event Bus → Webhooks → external notification

Each rule watches a single platform metric and fires when the metric
crosses the configured threshold.  A cooldown period prevents flood of
repeated alerts.  On breach the engine:
  1. Emits an `alert.threshold.breach` event on the event bus (severity
     mirrors the rule's configured severity, so webhooks can filter on it).
  2. Updates the per-rule breach state in SQLite.

Supported metrics
-----------------
  active_threats          — count of active threat_lookalike_alerts
  health_score            — composite platform health score (0-100)
  workflow_success_rate   — 24h workflow success rate (%)
  running_agents          — count of running autonomous agents
  emails_last_1h          — emails received in the last hour
  scam_last_24h           — scam/phishing emails in the last 24 h

Supported operators: > < >= <= ==

Endpoints
---------
  GET    /alert-rules                — list rules
  POST   /alert-rules                — create rule
  GET    /alert-rules/status         — current metric snapshot + rule eval
  POST   /alert-rules/evaluate       — force immediate evaluation
  GET    /alert-rules/{id}           — get rule
  PATCH  /alert-rules/{id}           — update rule
  DELETE /alert-rules/{id}           — delete rule
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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR, DB_PATH
from backend.core.runtime_control import get_runtime_control

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alert-rules", tags=["alert-rules"])

_DB_PATH      = str(Path(DATA_DIR) / "alert_rules.db")
_WORKFLOWS_DB = str(Path(DATA_DIR) / "workflows.db")
_ACTIONS_DB   = str(Path(DATA_DIR) / "agent_actions.db")

_SUPPORTED_METRICS = {
    "active_threats":        "Active lookalike/threat alerts",
    "health_score":          "Composite platform health score (0-100)",
    "workflow_success_rate": "24h workflow success rate (%)",
    "running_agents":        "Number of running autonomous agents",
    "emails_last_1h":        "Emails received in the last hour",
    "scam_last_24h":         "Scam / phishing emails in the last 24 h",
}
_SUPPORTED_OPERATORS = (">", "<", ">=", "<=", "==")
_SEVERITIES          = ("low", "medium", "high", "critical")


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS alert_rules (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            metric       TEXT NOT NULL,
            operator     TEXT NOT NULL,
            threshold    REAL NOT NULL,
            severity     TEXT DEFAULT 'medium',
            cooldown_min INTEGER DEFAULT 30,
            is_active    INTEGER DEFAULT 1,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS alert_rule_state (
            rule_id      TEXT PRIMARY KEY,
            last_breach  TEXT,
            breach_count INTEGER DEFAULT 0,
            last_value   REAL
        );
    """)
    con.close()


def _conn() -> sqlite3.Connection:
    return sqlite3.connect(_DB_PATH, timeout=10)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _q1(db: str, sql: str, params: tuple = (), fallback: Any = 0) -> Any:
    try:
        con = sqlite3.connect(db, timeout=5)
        val = con.execute(sql, params).fetchone()
        con.close()
        return val[0] if val and val[0] is not None else fallback
    except Exception:
        return fallback


def _since(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ── Metric collectors ─────────────────────────────────────────────────────────

def _collect_metrics() -> Dict[str, float]:
    active_threats = float(_q1(
        DB_PATH, "SELECT COUNT(*) FROM threat_lookalike_alerts WHERE status='active'", fallback=0
    ))
    emails_1h = float(_q1(
        DB_PATH, "SELECT COUNT(*) FROM emails WHERE created_at >= ?", (_since(1),), 0
    ))
    scam_24h = float(_q1(
        DB_PATH,
        "SELECT COUNT(*) FROM emails WHERE category IN ('Scam','Phishing') AND created_at >= ?",
        (_since(24),), 0,
    ))

    # Workflow success rate
    last_24h = _q1(_WORKFLOWS_DB, "SELECT COUNT(*) FROM workflow_executions WHERE created_at >= ?", (_since(24),), 0)
    succeeded = _q1(_WORKFLOWS_DB, "SELECT COUNT(*) FROM workflow_executions WHERE status='succeeded' AND created_at >= ?", (_since(24),), 0)
    wf_success = round(succeeded / last_24h * 100, 1) if last_24h > 0 else 100.0

    # Agent count
    try:
        from backend.api.agents import get_supervisor
        health = get_supervisor().supervisor_health()
        running_agents = float(health.get("running", 0))
        total_agents   = float(health.get("total_agents", 0))
    except Exception:
        running_agents = 0.0
        total_agents   = 0.0

    # Composite health score
    unread      = float(_q1(DB_PATH, "SELECT COUNT(*) FROM emails WHERE is_read=0", fallback=0))
    email_score = min(100.0, max(0.0, 100.0 - unread * 2))
    sec_scores  = {"good": 100, "medium": 70, "high": 40, "critical": 10}
    posture     = "critical" if active_threats >= 20 else "high" if active_threats >= 10 else "medium" if active_threats >= 3 else "good"
    sec_score   = float(sec_scores.get(posture, 50))
    wf_score    = min(100.0, max(0.0, wf_success))
    ag_score    = 100.0 if (running_agents == total_agents and total_agents > 0) else 60.0
    health_score = email_score * 0.2 + sec_score * 0.35 + wf_score * 0.3 + ag_score * 0.15

    return {
        "active_threats":        active_threats,
        "health_score":          round(health_score, 1),
        "workflow_success_rate": wf_success,
        "running_agents":        running_agents,
        "emails_last_1h":        emails_1h,
        "scam_last_24h":         scam_24h,
    }


# ── Condition evaluation ──────────────────────────────────────────────────────

def _eval_condition(value: float, operator: str, threshold: float) -> bool:
    if operator == ">":  return value > threshold
    if operator == "<":  return value < threshold
    if operator == ">=": return value >= threshold
    if operator == "<=": return value <= threshold
    if operator == "==": return value == threshold
    return False


# ── Background evaluator ──────────────────────────────────────────────────────

class AlertRulesEngine:
    CHECK_INTERVAL_S = 60

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._run_count  = 0
        self._last_check: Optional[str] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("AlertRulesEngine started")

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
                logger.error("AlertRulesEngine error: %s", exc)
            try:
                await asyncio.sleep(self.CHECK_INTERVAL_S)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        self._run_count += 1
        self._last_check = _now()

        try:
            metrics = _collect_metrics()
        except Exception as exc:
            logger.debug("AlertRulesEngine: metric collection failed: %s", exc)
            return

        try:
            con = _conn()
            con.row_factory = sqlite3.Row
            rules = con.execute("SELECT * FROM alert_rules WHERE is_active=1").fetchall()
            con.close()
        except Exception as exc:
            logger.debug("AlertRulesEngine: DB read failed: %s", exc)
            return

        now_dt = datetime.now(timezone.utc)
        for rule in rules:
            rule_id   = rule["id"]
            metric    = rule["metric"]
            operator  = rule["operator"]
            threshold = rule["threshold"]
            severity  = rule["severity"]
            cooldown  = rule["cooldown_min"]

            value = metrics.get(metric)
            if value is None:
                continue

            breached = _eval_condition(value, operator, threshold)

            # Update last_value in state regardless
            try:
                con = _conn()
                con.execute(
                    """INSERT INTO alert_rule_state (rule_id, last_value)
                       VALUES (?, ?)
                       ON CONFLICT(rule_id) DO UPDATE SET last_value=excluded.last_value""",
                    (rule_id, value),
                )
                con.commit()
                con.close()
            except Exception:
                pass

            if not breached:
                continue

            # Check cooldown
            try:
                con = _conn()
                row = con.execute(
                    "SELECT last_breach FROM alert_rule_state WHERE rule_id=?", (rule_id,)
                ).fetchone()
                con.close()
                if row and row[0]:
                    last_dt = datetime.fromisoformat(row[0])
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if (now_dt - last_dt).total_seconds() < cooldown * 60:
                        continue   # still in cooldown
            except Exception:
                pass

            # Fire breach
            await self._fire_breach(rule_id, rule["name"], metric, operator, threshold, value, severity)

    async def _fire_breach(
        self,
        rule_id: str, rule_name: str,
        metric: str, operator: str, threshold: float,
        value: float, severity: str,
    ) -> None:
        now_s = _now()
        try:
            con = _conn()
            con.execute(
                """INSERT INTO alert_rule_state (rule_id, last_breach, breach_count, last_value)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(rule_id) DO UPDATE SET
                     last_breach=excluded.last_breach,
                     breach_count=breach_count+1,
                     last_value=excluded.last_value""",
                (rule_id, now_s, value),
            )
            con.commit()
            con.close()
        except Exception as exc:
            logger.debug("AlertRulesEngine: state update failed: %s", exc)

        logger.warning(
            "Alert rule '%s' breached: %s %s %s (current=%.2f)",
            rule_name, metric, operator, threshold, value,
        )

        try:
            from backend.api.event_bus import emit
            asyncio.create_task(emit(
                event_type="alert.threshold.breach",
                source="alert_rules_engine",
                payload={
                    "rule_id":    rule_id,
                    "rule_name":  rule_name,
                    "metric":     metric,
                    "operator":   operator,
                    "threshold":  threshold,
                    "value":      value,
                    "message":    f"{rule_name}: {metric} {operator} {threshold} (current={value:.2f})",
                },
                severity=severity,
            ))
        except Exception as exc:
            logger.debug("AlertRulesEngine: event emit failed: %s", exc)

    def status(self) -> Dict[str, Any]:
        try:
            metrics = _collect_metrics()
        except Exception:
            metrics = {}

        try:
            con = _conn()
            con.row_factory = sqlite3.Row
            rules = con.execute("SELECT * FROM alert_rules WHERE is_active=1").fetchall()
            states = {
                r[0]: dict(r) for r in con.execute("SELECT * FROM alert_rule_state").fetchall()
            }
            con.close()
        except Exception:
            rules, states = [], {}

        evaluations = []
        for rule in rules:
            rule_d = dict(rule)
            state  = states.get(rule["id"], {})
            value  = metrics.get(rule["metric"])
            breached = _eval_condition(value, rule["operator"], rule["threshold"]) if value is not None else False
            evaluations.append({
                "rule_id":      rule["id"],
                "rule_name":    rule["name"],
                "metric":       rule["metric"],
                "operator":     rule["operator"],
                "threshold":    rule["threshold"],
                "current_value": value,
                "breached":     breached,
                "last_breach":  state.get("last_breach"),
                "breach_count": state.get("breach_count", 0),
            })

        return {
            "running":    self._running,
            "run_count":  self._run_count,
            "last_check": self._last_check,
            "metrics":    metrics,
            "rules":      evaluations,
        }


# ── Module singleton ──────────────────────────────────────────────────────────

_engine = AlertRulesEngine()


def get_alert_rules_engine() -> AlertRulesEngine:
    return _engine


async def ensure_alert_rules_running() -> None:
    if not get_runtime_control().is_service_enabled("alert_rules"):
        logger.info("AlertRulesEngine disabled by runtime policy")
        return
    _init_db()
    await _engine.start()


# ── Pydantic models ───────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    name:         str
    metric:       str
    operator:     str
    threshold:    float
    severity:     str  = "medium"
    cooldown_min: int  = 30


class RuleUpdate(BaseModel):
    name:         Optional[str]   = None
    metric:       Optional[str]   = None
    operator:     Optional[str]   = None
    threshold:    Optional[float] = None
    severity:     Optional[str]   = None
    cooldown_min: Optional[int]   = None
    is_active:    Optional[bool]  = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate_rule(metric: str, operator: str) -> None:
    if metric not in _SUPPORTED_METRICS:
        raise HTTPException(400, f"Unknown metric '{metric}'. Supported: {list(_SUPPORTED_METRICS)}")
    if operator not in _SUPPORTED_OPERATORS:
        raise HTTPException(400, f"Unknown operator '{operator}'. Supported: {list(_SUPPORTED_OPERATORS)}")


def _row_to_dict(row) -> Dict:
    d = dict(row)
    d["is_active"] = bool(d.get("is_active", 1))
    return d


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="List all alert rules")
async def list_rules(_auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM alert_rules ORDER BY created_at DESC").fetchall()
        con.close()
        return {"rules": [_row_to_dict(r) for r in rows], "count": len(rows)}
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")


@router.get("/status", summary="Current metrics snapshot and rule evaluation")
async def rules_status(_auth=Depends(require_local_auth)):
    return _engine.status()


@router.get("/metrics", summary="Supported metric names and descriptions")
async def list_metrics(_auth=Depends(require_local_auth)):
    return {
        "metrics":   [{"id": k, "description": v} for k, v in _SUPPORTED_METRICS.items()],
        "operators": list(_SUPPORTED_OPERATORS),
    }


@router.post("/evaluate", summary="Force an immediate rule evaluation cycle")
async def force_evaluate(_auth=Depends(require_local_auth)):
    asyncio.create_task(_engine._tick())
    return {"ok": True, "message": "Alert rule evaluation dispatched."}


@router.post("", summary="Create an alert rule", status_code=201)
async def create_rule(body: RuleCreate, _auth=Depends(require_local_auth)):
    _validate_rule(body.metric, body.operator)
    rule_id = str(uuid.uuid4())
    now     = _now()
    try:
        con = _conn()
        con.execute(
            """INSERT INTO alert_rules
               (id, name, metric, operator, threshold, severity, cooldown_min, is_active, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,1,?,?)""",
            (rule_id, body.name, body.metric, body.operator,
             body.threshold, body.severity, body.cooldown_min, now, now),
        )
        con.commit()
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
        con.close()
        return _row_to_dict(row)
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")


@router.get("/{rule_id}", summary="Get an alert rule")
async def get_rule(rule_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
        con.close()
        if not row:
            raise HTTPException(404, "Rule not found")
        return _row_to_dict(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")


@router.patch("/{rule_id}", summary="Update an alert rule")
async def update_rule(rule_id: str, body: RuleUpdate, _auth=Depends(require_local_auth)):
    if body.metric   is not None: _validate_rule(body.metric, body.operator or ">")
    if body.operator is not None: _validate_rule(body.metric or "active_threats", body.operator)
    fields: Dict[str, Any] = {}
    if body.name         is not None: fields["name"]         = body.name
    if body.metric       is not None: fields["metric"]        = body.metric
    if body.operator     is not None: fields["operator"]      = body.operator
    if body.threshold    is not None: fields["threshold"]     = body.threshold
    if body.severity     is not None: fields["severity"]      = body.severity
    if body.cooldown_min is not None: fields["cooldown_min"]  = body.cooldown_min
    if body.is_active    is not None: fields["is_active"]     = int(body.is_active)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    try:
        con = _conn()
        result = con.execute(
            f"UPDATE alert_rules SET {set_clause} WHERE id=?",
            (*fields.values(), rule_id),
        )
        con.commit()
        if result.rowcount == 0:
            con.close()
            raise HTTPException(404, "Rule not found")
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM alert_rules WHERE id=?", (rule_id,)).fetchone()
        con.close()
        return _row_to_dict(row)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")


@router.delete("/{rule_id}", summary="Delete an alert rule", status_code=204)
async def delete_rule(rule_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        result = con.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,))
        con.commit()
        con.close()
        if result.rowcount == 0:
            raise HTTPException(404, "Rule not found")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"DB error: {exc}")
