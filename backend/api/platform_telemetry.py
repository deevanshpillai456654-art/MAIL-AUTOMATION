"""
Platform Telemetry
==================
Unified platform-wide KPI aggregation endpoint.

Aggregates metrics from all subsystems in a single call, giving the
Command Center dashboard a consistent, low-latency snapshot of the
entire operational platform.

Metrics collected:
  - Email processing (volume, rate, backlog)
  - Security (active threats, scam detections, posture score)
  - Workflow engine (active, executions, success rate, SLA)
  - Event bus (throughput, event type distribution)
  - Agent system (running, action count, anomaly count)
  - Reconciler (cycles, last run, issues)
  - Workflow scheduler (scheduled workflows, next fire)

Endpoint:
  GET /telemetry           — full platform KPI snapshot
  GET /telemetry/summary   — compact summary for dashboard strip
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR, DB_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/telemetry", tags=["platform-telemetry"])

_WORKFLOWS_DB  = str(Path(DATA_DIR) / "workflows.db")
_EVENTS_DB     = str(Path(DATA_DIR) / "event_bus.db")
_ACTIONS_DB    = str(Path(DATA_DIR) / "agent_actions.db")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _q1(db: str, sql: str, params: tuple = (), fallback: Any = 0) -> Any:
    try:
        con = sqlite3.connect(db, timeout=5)
        val = con.execute(sql, params).fetchone()
        con.close()
        return val[0] if val and val[0] is not None else fallback
    except Exception:
        return fallback


def _q(db: str, sql: str, params: tuple = ()) -> list:
    try:
        con = sqlite3.connect(db, timeout=5)
        rows = con.execute(sql, params).fetchall()
        con.close()
        return rows
    except Exception:
        return []


def _since(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ── Collector functions ───────────────────────────────────────────────────────

def _email_metrics() -> Dict[str, Any]:
    total     = _q1(DB_PATH, "SELECT COUNT(*) FROM emails", fallback=0)
    unread    = _q1(DB_PATH, "SELECT COUNT(*) FROM emails WHERE is_read=0", fallback=0)
    last_24h  = _q1(DB_PATH, "SELECT COUNT(*) FROM emails WHERE created_at >= ?", (_since(24),), 0)
    last_1h   = _q1(DB_PATH, "SELECT COUNT(*) FROM emails WHERE created_at >= ?", (_since(1),), 0)
    scam      = _q1(DB_PATH, "SELECT COUNT(*) FROM emails WHERE category IN ('Scam','Phishing') AND created_at >= ?", (_since(24),), 0)
    return {
        "total":         total,
        "unread":        unread,
        "last_24h":      last_24h,
        "last_1h":       last_1h,
        "scam_last_24h": scam,
    }


def _security_metrics() -> Dict[str, Any]:
    active   = _q1(DB_PATH, "SELECT COUNT(*) FROM threat_lookalike_alerts WHERE status='active'", fallback=0)
    total    = _q1(DB_PATH, "SELECT COUNT(*) FROM threat_lookalike_alerts", fallback=0)
    last_24h = _q1(DB_PATH, "SELECT COUNT(*) FROM threat_lookalike_alerts WHERE created_at >= ?", (_since(24),), 0)
    critical = _q1(DB_PATH, "SELECT COUNT(*) FROM threat_lookalike_alerts WHERE status='active' AND confidence_score >= 90", fallback=0)
    brands_q = _q(DB_PATH, "SELECT impersonated_brand, COUNT(*) c FROM threat_lookalike_alerts WHERE status='active' GROUP BY impersonated_brand ORDER BY c DESC LIMIT 3")
    return {
        "active_threats":       active,
        "total_threats":        total,
        "threats_last_24h":     last_24h,
        "critical_threats":     critical,
        "top_targeted_brands":  [{"brand": r[0], "count": r[1]} for r in brands_q],
        "posture":              "critical" if active >= 20 else "high" if active >= 10 else "medium" if active >= 3 else "good",
    }


def _workflow_metrics() -> Dict[str, Any]:
    active_wf  = _q1(_WORKFLOWS_DB, "SELECT COUNT(*) FROM workflows WHERE is_active=1", fallback=0)
    total_wf   = _q1(_WORKFLOWS_DB, "SELECT COUNT(*) FROM workflows", fallback=0)
    running    = _q1(_WORKFLOWS_DB, "SELECT COUNT(*) FROM workflow_executions WHERE status='running'", fallback=0)
    last_24h   = _q1(_WORKFLOWS_DB, "SELECT COUNT(*) FROM workflow_executions WHERE created_at >= ?", (_since(24),), 0)
    succeeded  = _q1(_WORKFLOWS_DB, "SELECT COUNT(*) FROM workflow_executions WHERE status='succeeded' AND created_at >= ?", (_since(24),), 0)
    failed     = _q1(_WORKFLOWS_DB, "SELECT COUNT(*) FROM workflow_executions WHERE status='failed' AND created_at >= ?", (_since(24),), 0)
    success_rate = round(succeeded / last_24h * 100, 1) if last_24h > 0 else 100.0
    avg_dur    = _q1(_WORKFLOWS_DB, "SELECT AVG(duration_ms) FROM workflow_executions WHERE status='succeeded' AND created_at >= ?", (_since(24),), 0)
    return {
        "active_workflows":    active_wf,
        "total_workflows":     total_wf,
        "running_executions":  running,
        "executions_last_24h": last_24h,
        "succeeded_last_24h":  succeeded,
        "failed_last_24h":     failed,
        "success_rate_24h":    success_rate,
        "avg_duration_ms":     int(avg_dur or 0),
        "sla_ok":              success_rate >= 70,
    }


def _event_bus_metrics() -> Dict[str, Any]:
    total    = _q1(_EVENTS_DB, "SELECT COUNT(*) FROM operational_events", fallback=0)
    last_1h  = _q1(_EVENTS_DB, "SELECT COUNT(*) FROM operational_events WHERE created_at >= ?", (_since(1),), 0)
    last_24h = _q1(_EVENTS_DB, "SELECT COUNT(*) FROM operational_events WHERE created_at >= ?", (_since(24),), 0)
    by_type  = _q(_EVENTS_DB, "SELECT type, COUNT(*) c FROM operational_events WHERE created_at >= ? GROUP BY type ORDER BY c DESC LIMIT 5", (_since(24),))
    return {
        "total_events":      total,
        "events_last_1h":    last_1h,
        "events_last_24h":   last_24h,
        "top_types_24h":     [{"type": r[0], "count": r[1]} for r in by_type],
    }


def _agent_metrics() -> Dict[str, Any]:
    try:
        from backend.api.agents import get_supervisor
        supervisor = get_supervisor()
        health = supervisor.supervisor_health()
        running = health.get("running", 0)
        total   = health.get("total_agents", 0)
        enabled = health.get("enabled", total)
        disabled = health.get("disabled", max(0, total - enabled))
    except Exception:
        running, total, enabled, disabled = 0, 0, 0, 0

    action_count = _q1(_ACTIONS_DB, "SELECT COUNT(*) FROM agent_actions", fallback=0)
    anomaly_count = _q1(_ACTIONS_DB, "SELECT COUNT(*) FROM agent_actions WHERE action_type='anomaly' AND created_at >= ?", (_since(24),), 0)
    insight_count = _q1(_ACTIONS_DB, "SELECT COUNT(*) FROM agent_actions WHERE action_type='insight' AND created_at >= ?", (_since(24),), 0)
    return {
        "total_agents":      total,
        "enabled_agents":    enabled,
        "disabled_agents":   disabled,
        "running_agents":    running,
        "total_actions":     action_count,
        "anomalies_24h":     anomaly_count,
        "insights_24h":      insight_count,
    }


def _reconciler_metrics() -> Dict[str, Any]:
    try:
        from backend.api.reconciler import get_reconciler
        r = get_reconciler()
        s = r.status()
        summary = s.get("last_summary", {})
        return {
            "running":       s.get("running", False),
            "cycles_run":    s.get("run_count", 0),
            "last_run":      s.get("last_run"),
            "last_actions":  summary.get("actions_taken", 0),
            "last_issues":   summary.get("issues_found", 0),
        }
    except Exception:
        return {"running": False, "cycles_run": 0}


def _scheduler_metrics() -> Dict[str, Any]:
    try:
        from backend.api.workflow_scheduler import get_workflow_scheduler
        s = get_workflow_scheduler()
        status = s.status()
        return {
            "running":              status.get("running", False),
            "scheduled_workflows":  status.get("scheduled_workflows", 0),
            "next_fire":            status.get("upcoming", [{}])[0].get("next_fire") if status.get("upcoming") else None,
            "checks_run":           status.get("run_count", 0),
        }
    except Exception:
        return {"running": False, "scheduled_workflows": 0}


def _human_approval_metrics() -> Dict[str, Any]:
    try:
        from backend.api.human_approval import get_human_approval_queue

        queue = get_human_approval_queue()
        pending = [
            item for item in queue._items.values()
            if getattr(item, "status", "") == "pending"
        ]
        tenants = {item.tenant_id for item in pending}
        return {
            "pending": len(pending),
            "tenants_with_pending": len(tenants),
        }
    except Exception:
        return {"pending": 0, "tenants_with_pending": 0}


def _ai_gateway_metrics() -> Dict[str, Any]:
    try:
        from backend.core.ai_gateway import get_ai_gateway

        return get_ai_gateway().status()
    except Exception:
        return {
            "mode": "unknown",
            "enabled": False,
            "provider_order": [],
            "local_models_loaded": False,
            "always_on_models": False,
        }


def _compute_overall_health(
    emails: Dict, security: Dict, workflows: Dict, agents: Dict
) -> Dict[str, Any]:
    """Composite health score 0-100."""
    email_score = min(100, max(0, 100 - emails["unread"] * 2))
    sec_score   = {"good": 100, "medium": 70, "high": 40, "critical": 10}.get(security["posture"], 50)
    wf_score    = min(100, max(0, int(workflows["success_rate_24h"])))
    enabled_agents = int(agents.get("enabled_agents", agents.get("total_agents", 0)) or 0)
    running_agents = int(agents.get("running_agents", 0) or 0)
    agent_score = 100 if enabled_agents == 0 or running_agents == enabled_agents else 60

    weights = {"email": 0.2, "security": 0.35, "workflow": 0.3, "agents": 0.15}
    overall = int(
        email_score    * weights["email"]
        + sec_score    * weights["security"]
        + wf_score     * weights["workflow"]
        + agent_score  * weights["agents"]
    )
    status = "healthy" if overall >= 80 else "degraded" if overall >= 50 else "critical"
    return {"overall": overall, "status": status, "components": {
        "email":    {"score": email_score,  "weight": weights["email"]},
        "security": {"score": sec_score,    "weight": weights["security"]},
        "workflow": {"score": wf_score,     "weight": weights["workflow"]},
        "agents":   {"score": agent_score,  "weight": weights["agents"]},
    }}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="Full platform KPI snapshot")
async def platform_telemetry(_auth=Depends(require_local_auth)):
    emails      = _email_metrics()
    security    = _security_metrics()
    workflows   = _workflow_metrics()
    events      = _event_bus_metrics()
    agents      = _agent_metrics()
    reconciler  = _reconciler_metrics()
    scheduler   = _scheduler_metrics()
    approvals   = _human_approval_metrics()
    ai_gateway  = _ai_gateway_metrics()
    health      = _compute_overall_health(emails, security, workflows, agents)

    return {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "health":      health,
        "email":       emails,
        "security":    security,
        "workflows":   workflows,
        "event_bus":   events,
        "agents":      agents,
        "human_approvals": approvals,
        "ai_gateway":  ai_gateway,
        "reconciler":  reconciler,
        "scheduler":   scheduler,
    }


@router.get("/summary", summary="Compact platform summary for dashboard strip")
async def platform_summary(_auth=Depends(require_local_auth)):
    """Four-metric strip for the main dashboard."""
    emails    = _email_metrics()
    security  = _security_metrics()
    workflows = _workflow_metrics()
    agents    = _agent_metrics()
    health    = _compute_overall_health(emails, security, workflows, agents)

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "health_score": health["overall"],
        "health_status": health["status"],
        "metrics": [
            {
                "id":     "email_volume",
                "label":  "Emails (24h)",
                "value":  emails["last_24h"],
                "unit":   "",
                "trend":  "up" if emails["last_1h"] > 0 else "flat",
                "alert":  emails["scam_last_24h"] > 0,
            },
            {
                "id":     "active_threats",
                "label":  "Active Threats",
                "value":  security["active_threats"],
                "unit":   "",
                "trend":  "up" if security["threats_last_24h"] > 3 else "flat",
                "alert":  security["active_threats"] >= 10,
            },
            {
                "id":     "workflow_success",
                "label":  "WF Success Rate",
                "value":  workflows["success_rate_24h"],
                "unit":   "%",
                "trend":  "up" if workflows["success_rate_24h"] >= 90 else "down",
                "alert":  not workflows["sla_ok"],
            },
            {
                "id":     "agents_running",
                "label":  "Agents Running",
                "value":  agents["running_agents"],
                "unit":   f"/{agents.get('enabled_agents', agents['total_agents'])} enabled",
                "trend":  "flat",
                "alert":  agents["running_agents"] < agents.get("enabled_agents", agents["total_agents"]),
            },
        ],
    }
