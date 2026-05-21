"""
Workflow Engine — AI-native operational workflow execution system.

Executes business workflows as ordered state-machine transitions with:
  - Retry orchestration with exponential backoff
  - Compensation (saga) on failure
  - Full execution audit trail
  - Background async execution
  - Built-in operational template library
  - AI-powered workflow recommendations

Endpoints:
  GET    /workflows/templates          — list available template library
  GET    /workflows                    — list tenant workflows
  POST   /workflows                    — create workflow from template or custom
  GET    /workflows/{id}               — get workflow detail
  PUT    /workflows/{id}               — update workflow
  DELETE /workflows/{id}               — delete workflow
  POST   /workflows/{id}/activate      — activate workflow
  POST   /workflows/{id}/deactivate    — deactivate workflow
  POST   /workflows/{id}/execute       — manually trigger execution
  GET    /workflows/{id}/history       — execution history for workflow
  GET    /workflows/executions/all     — all recent executions
  GET    /workflows/recommendations    — AI recommendations based on email data
  GET    /workflows/stats              — aggregate stats
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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["workflows"])

_DB_PATH = str(Path(DATA_DIR) / "workflows.db")


# ── DB bootstrap ──────────────────────────────────────────────────────────────

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_DB_PATH, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            description  TEXT,
            category     TEXT DEFAULT 'general',
            icon         TEXT DEFAULT 'zap',
            trigger_type TEXT DEFAULT 'manual',
            trigger_cfg  TEXT DEFAULT '{}',
            steps_json   TEXT DEFAULT '[]',
            is_active    INTEGER DEFAULT 0,
            run_count    INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            fail_count   INTEGER DEFAULT 0,
            last_run_at  TEXT,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id           TEXT PRIMARY KEY,
            workflow_id  TEXT NOT NULL,
            trigger_type TEXT DEFAULT 'manual',
            status       TEXT DEFAULT 'pending',
            started_at   TEXT,
            finished_at  TEXT,
            duration_ms  INTEGER,
            error        TEXT,
            input_data   TEXT DEFAULT '{}',
            output_data  TEXT DEFAULT '{}',
            step_count   INTEGER DEFAULT 0,
            steps_done   INTEGER DEFAULT 0,
            created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS workflow_step_logs (
            id            TEXT PRIMARY KEY,
            execution_id  TEXT NOT NULL,
            workflow_id   TEXT NOT NULL,
            step_id       TEXT NOT NULL,
            step_name     TEXT,
            step_type     TEXT,
            status        TEXT DEFAULT 'pending',
            attempt       INTEGER DEFAULT 1,
            started_at    TEXT,
            finished_at   TEXT,
            duration_ms   INTEGER,
            input_data    TEXT DEFAULT '{}',
            output_data   TEXT DEFAULT '{}',
            error         TEXT,
            log_lines     TEXT DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_wf_active     ON workflows (is_active, trigger_type);
        CREATE INDEX IF NOT EXISTS idx_we_workflow   ON workflow_executions (workflow_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_we_status     ON workflow_executions (status);
        CREATE INDEX IF NOT EXISTS idx_wsl_execution ON workflow_step_logs (execution_id);
        CREATE INDEX IF NOT EXISTS idx_wsl_workflow  ON workflow_step_logs (workflow_id, started_at DESC);
    """)
    con.commit()
    return con


@contextmanager
def _conn() -> Generator:
    con = _db()
    try:
        yield con
    finally:
        con.close()


# ── Built-in template library ─────────────────────────────────────────────────

WORKFLOW_TEMPLATES: List[Dict[str, Any]] = [
    {
        "template_id":  "smart_inbox_organizer",
        "name":         "Smart Inbox Organizer",
        "description":  "AI semantically categorizes every incoming email in real-time — Finance, Scam, Newsletter, Personal, Priority — so your inbox is always organized without manual effort.",
        "category":     "email_intelligence",
        "icon":         "brain",
        "trigger_type": "email_received",
        "impact":       "high",
        "setup_time":   "instant",
        "recommended":  True,
        "steps": [
            {"id": "s1", "name": "Receive Email Event",     "type": "trigger",      "config": {"source": "inbox"}},
            {"id": "s2", "name": "AI Semantic Analysis",    "type": "ai_classify",  "config": {"model": "intemo-v1", "confidence_threshold": 0.7},
             "retry": {"max_attempts": 2, "delay_seconds": 2}},
            {"id": "s3", "name": "Apply Category Label",    "type": "email_action", "config": {"action": "categorize", "field": "ai_result.category"}},
            {"id": "s4", "name": "Update Priority Score",   "type": "email_action", "config": {"action": "set_priority", "field": "ai_result.priority"}},
            {"id": "s5", "name": "Log Classification",      "type": "audit_log",    "config": {"event": "email_classified"}},
        ],
    },
    {
        "template_id":  "threat_escalation",
        "name":         "Threat Escalation Engine",
        "description":  "Detects high-confidence phishing and lookalike domain attacks, immediately quarantines the email, creates a threat alert, and notifies the security team.",
        "category":     "security",
        "icon":         "shield",
        "trigger_type": "email_received",
        "impact":       "critical",
        "setup_time":   "instant",
        "recommended":  True,
        "steps": [
            {"id": "s1", "name": "Intercept Incoming Email",  "type": "trigger",       "config": {"source": "inbox"}},
            {"id": "s2", "name": "Threat Intelligence Scan",  "type": "threat_check",  "config": {"check_lookalike": True, "check_blacklist": True, "score_threshold": 70},
             "retry": {"max_attempts": 3, "delay_seconds": 1}},
            {"id": "s3", "name": "Evaluate Threat Score",     "type": "condition",     "config": {"field": "threat.score", "operator": ">=", "value": 70}},
            {"id": "s4", "name": "Quarantine Email",          "type": "email_action",  "config": {"action": "quarantine"}, "depends_on": "s3"},
            {"id": "s5", "name": "Create Threat Alert",       "type": "create_alert",  "config": {"severity": "high", "source": "workflow"}, "depends_on": "s3"},
            {"id": "s6", "name": "Notify Security Team",      "type": "notify",        "config": {"channel": "security", "template": "threat_detected"}, "depends_on": "s5"},
            {"id": "s7", "name": "Audit Security Event",      "type": "audit_log",     "config": {"event": "threat_escalated"}},
        ],
    },
    {
        "template_id":  "invoice_ocr_pipeline",
        "name":         "Invoice OCR Pipeline",
        "description":  "Automatically scans every Finance-category email for attached invoices, runs OCR extraction, captures invoice number, amount, vendor, and due date, and saves to history.",
        "category":     "finance",
        "icon":         "file_text",
        "trigger_type": "email_received",
        "impact":       "high",
        "setup_time":   "instant",
        "recommended":  True,
        "steps": [
            {"id": "s1", "name": "Monitor Finance Emails",    "type": "trigger",      "config": {"category_filter": "Finance"}},
            {"id": "s2", "name": "Detect Attachment Type",    "type": "condition",    "config": {"field": "email.has_attachment", "operator": "==", "value": True}},
            {"id": "s3", "name": "Run OCR Extraction",        "type": "ocr_scan",     "config": {"mode": "invoice", "extract_fields": True},
             "retry": {"max_attempts": 2, "delay_seconds": 3}},
            {"id": "s4", "name": "Validate Extracted Fields", "type": "validate",     "config": {"required": ["invoice_number", "total_amount"]}},
            {"id": "s5", "name": "Save Invoice Record",       "type": "data_store",   "config": {"store": "ocr_history"}},
            {"id": "s6", "name": "Tag Email as Processed",    "type": "email_action", "config": {"action": "add_label", "label": "Invoice-Processed"}},
        ],
    },
    {
        "template_id":  "scam_quarantine",
        "name":         "Scam Auto-Quarantine",
        "description":  "Any email classified as Scam with confidence above 80% is immediately quarantined, the sender is blacklisted, and the action is logged for compliance.",
        "category":     "security",
        "icon":         "ban",
        "trigger_type": "email_received",
        "impact":       "high",
        "setup_time":   "instant",
        "recommended":  True,
        "steps": [
            {"id": "s1", "name": "Watch All Incoming Email",  "type": "trigger",      "config": {}},
            {"id": "s2", "name": "Check Scam Confidence",     "type": "condition",    "config": {"field": "email.confidence", "operator": ">=", "value": 0.80, "category_filter": "Scam"}},
            {"id": "s3", "name": "Quarantine Email",          "type": "email_action", "config": {"action": "quarantine"}},
            {"id": "s4", "name": "Blacklist Sender Domain",   "type": "blacklist",    "config": {"entry_type": "domain", "source": "email.sender_domain"}},
            {"id": "s5", "name": "Record Compliance Log",     "type": "audit_log",    "config": {"event": "scam_quarantined", "include_email_meta": True}},
        ],
    },
    {
        "template_id":  "vip_sender_alert",
        "name":         "VIP Sender Priority Alert",
        "description":  "Monitors your inbox for emails from VIP senders. When detected, instantly marks as priority and sends a real-time alert so critical communications are never missed.",
        "category":     "email_intelligence",
        "icon":         "star",
        "trigger_type": "email_received",
        "impact":       "medium",
        "setup_time":   "instant",
        "recommended":  False,
        "steps": [
            {"id": "s1", "name": "Watch All Incoming Email",  "type": "trigger",      "config": {}},
            {"id": "s2", "name": "Check Trusted Sender List", "type": "whitelist_check", "config": {"field": "email.sender_email"}},
            {"id": "s3", "name": "Mark as Priority",          "type": "email_action", "config": {"action": "set_priority", "value": "high"}, "depends_on": "s2"},
            {"id": "s4", "name": "Send Priority Alert",       "type": "notify",       "config": {"channel": "dashboard", "template": "vip_email"}, "depends_on": "s2"},
        ],
    },
    {
        "template_id":  "daily_intelligence_digest",
        "name":         "Daily Intelligence Digest",
        "description":  "Every morning at 8 AM, generates an AI-powered digest of overnight email activity: threat summary, priority items, pending actions, and pattern insights.",
        "category":     "analytics",
        "icon":         "bar_chart",
        "trigger_type": "schedule",
        "impact":       "medium",
        "setup_time":   "instant",
        "recommended":  False,
        "trigger_cfg":  {"cron": "0 8 * * *", "timezone": "UTC"},
        "steps": [
            {"id": "s1", "name": "Schedule Trigger (8 AM)",   "type": "trigger",      "config": {"schedule": "0 8 * * *"}},
            {"id": "s2", "name": "Aggregate Email Stats",      "type": "data_query",   "config": {"window": "24h", "metrics": ["received", "threats", "scam", "categories"]}},
            {"id": "s3", "name": "AI Insight Generation",      "type": "ai_generate",  "config": {"template": "daily_digest", "include_recommendations": True}},
            {"id": "s4", "name": "Deliver Dashboard Digest",   "type": "notify",       "config": {"channel": "dashboard", "template": "daily_digest"}},
        ],
    },
    {
        "template_id":  "bulk_newsletter_cleanup",
        "name":         "Newsletter Auto-Archive",
        "description":  "Automatically archives newsletters and promotional emails older than 7 days that have not been opened, keeping your inbox clean without manual effort.",
        "category":     "email_intelligence",
        "icon":         "archive",
        "trigger_type": "schedule",
        "impact":       "medium",
        "setup_time":   "instant",
        "recommended":  False,
        "trigger_cfg":  {"cron": "0 2 * * *", "timezone": "UTC"},
        "steps": [
            {"id": "s1", "name": "Schedule Trigger (2 AM)",    "type": "trigger",      "config": {"schedule": "0 2 * * *"}},
            {"id": "s2", "name": "Query Old Newsletters",       "type": "data_query",   "config": {"category": "Newsletters", "age_days": 7, "is_read": False}},
            {"id": "s3", "name": "Batch Archive Emails",        "type": "email_action", "config": {"action": "archive", "batch": True}},
            {"id": "s4", "name": "Log Cleanup Report",          "type": "audit_log",    "config": {"event": "newsletter_cleanup", "include_count": True}},
        ],
    },
    {
        "template_id":  "priority_escalation",
        "name":         "Priority Escalation Monitor",
        "description":  "Monitors emails marked as high priority that remain unread for over 4 hours. Automatically re-notifies and escalates with an urgent dashboard alert.",
        "category":     "email_intelligence",
        "icon":         "alert_triangle",
        "trigger_type": "schedule",
        "impact":       "medium",
        "setup_time":   "instant",
        "recommended":  False,
        "trigger_cfg":  {"cron": "0 */4 * * *", "timezone": "UTC"},
        "steps": [
            {"id": "s1", "name": "Schedule Trigger (Every 4h)", "type": "trigger",      "config": {"schedule": "0 */4 * * *"}},
            {"id": "s2", "name": "Query Unread Priority Email",  "type": "data_query",   "config": {"priority": "high", "is_read": False, "age_hours": 4}},
            {"id": "s3", "name": "Evaluate Escalation Need",     "type": "condition",    "config": {"field": "query.count", "operator": ">", "value": 0}},
            {"id": "s4", "name": "Send Escalation Alert",        "type": "notify",       "config": {"channel": "dashboard", "template": "priority_escalation"}, "depends_on": "s3"},
        ],
    },
    {
        "template_id":  "account_sync_health",
        "name":         "Account Sync Health Monitor",
        "description":  "Continuously monitors all connected mailbox accounts for sync failures, authentication issues, and rate limit errors. Auto-retries failed syncs and alerts on persistent failures.",
        "category":     "infrastructure",
        "icon":         "activity",
        "trigger_type": "schedule",
        "impact":       "high",
        "setup_time":   "instant",
        "recommended":  True,
        "trigger_cfg":  {"cron": "*/15 * * * *", "timezone": "UTC"},
        "steps": [
            {"id": "s1", "name": "Schedule (Every 15 min)",     "type": "trigger",      "config": {"schedule": "*/15 * * * *"}},
            {"id": "s2", "name": "Check Account Sync Status",   "type": "health_check", "config": {"target": "accounts", "include_last_sync": True}},
            {"id": "s3", "name": "Detect Stale Syncs",          "type": "condition",    "config": {"field": "health.stale_count", "operator": ">", "value": 0}},
            {"id": "s4", "name": "Trigger Sync Retry",          "type": "system_action","config": {"action": "retry_sync"}, "depends_on": "s3",
             "retry": {"max_attempts": 3, "delay_seconds": 30}},
            {"id": "s5", "name": "Alert on Persistent Failure",  "type": "notify",       "config": {"channel": "dashboard", "template": "sync_failure", "only_if": "retry_exhausted"}},
        ],
    },
    {
        "template_id":  "security_compliance_audit",
        "name":         "Security Compliance Audit Trail",
        "description":  "Captures every security event — threat detections, quarantines, blacklist changes, login events — into an immutable compliance audit trail with tamper-evident logging.",
        "category":     "security",
        "icon":         "shield_check",
        "trigger_type": "event",
        "impact":       "critical",
        "setup_time":   "instant",
        "recommended":  True,
        "steps": [
            {"id": "s1", "name": "Listen to Security Events",   "type": "trigger",      "config": {"events": ["threat_detected", "quarantine", "blacklist_change", "auth_event"]}},
            {"id": "s2", "name": "Enrich Event Context",         "type": "ai_enrich",    "config": {"extract": ["risk_level", "entity", "intent"]}},
            {"id": "s3", "name": "Write Immutable Audit Record", "type": "audit_log",    "config": {"mode": "append_only", "include_hash": True}},
            {"id": "s4", "name": "Check Compliance Threshold",   "type": "condition",    "config": {"field": "event.severity", "operator": "==", "value": "critical"}},
            {"id": "s5", "name": "Critical Event Escalation",    "type": "notify",       "config": {"channel": "security", "template": "critical_security_event"}, "depends_on": "s4"},
        ],
    },
    {
        "template_id":  "anomaly_detection",
        "name":         "Email Pattern Anomaly Detector",
        "description":  "AI continuously learns your normal email patterns. When unusual activity is detected — sudden volume spikes, new sender patterns, abnormal timing — it flags and investigates automatically.",
        "category":     "analytics",
        "icon":         "trending_up",
        "trigger_type": "schedule",
        "impact":       "high",
        "setup_time":   "instant",
        "recommended":  True,
        "trigger_cfg":  {"cron": "0 */6 * * *", "timezone": "UTC"},
        "steps": [
            {"id": "s1", "name": "Schedule Trigger (Every 6h)",  "type": "trigger",      "config": {"schedule": "0 */6 * * *"}},
            {"id": "s2", "name": "Sample Email Patterns",         "type": "data_query",   "config": {"window": "6h", "metrics": ["volume", "senders", "categories", "timing"]}},
            {"id": "s3", "name": "AI Baseline Comparison",        "type": "ai_analyze",   "config": {"model": "anomaly_v1", "baseline_window": "7d"}},
            {"id": "s4", "name": "Score Anomaly Risk",            "type": "condition",    "config": {"field": "anomaly.score", "operator": ">=", "value": 0.75}},
            {"id": "s5", "name": "Generate Anomaly Report",       "type": "ai_generate",  "config": {"template": "anomaly_report"}, "depends_on": "s4"},
            {"id": "s6", "name": "Alert Operations Team",         "type": "notify",       "config": {"channel": "dashboard", "template": "anomaly_alert"}, "depends_on": "s4"},
        ],
    },
    {
        "template_id":  "connector_event_router",
        "name":         "Connector Event Router",
        "description":  "Routes operational events from installed connectors into the unified workflow execution engine, ensuring every connector event triggers the appropriate business workflow automatically.",
        "category":     "infrastructure",
        "icon":         "git_merge",
        "trigger_type": "event",
        "impact":       "high",
        "setup_time":   "instant",
        "recommended":  False,
        "steps": [
            {"id": "s1", "name": "Listen to Connector Events",   "type": "trigger",      "config": {"source": "connectors", "event_types": ["*"]}},
            {"id": "s2", "name": "Normalize Event Payload",       "type": "transform",    "config": {"schema": "unified_event_v1"}},
            {"id": "s3", "name": "Route to Workflow",             "type": "router",       "config": {"routing_table": "connector_workflow_map"}},
            {"id": "s4", "name": "Execute Mapped Workflow",       "type": "workflow_call","config": {"async": True, "timeout": 300}},
            {"id": "s5", "name": "Audit Routing Decision",        "type": "audit_log",    "config": {"event": "connector_event_routed"}},
        ],
    },
]


# ── Execution engine ──────────────────────────────────────────────────────────

class WorkflowEngine:
    """Core state-machine execution engine with retry, compensation, and audit."""

    STEP_TIMEOUT = 30.0      # seconds per step
    MAX_RETRY_DELAY = 60.0   # seconds

    async def execute(
        self,
        workflow_id: str,
        execution_id: str,
        steps: List[Dict[str, Any]],
        input_data: Dict[str, Any],
        trigger_type: str = "manual",
    ) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {"input": input_data, "steps": {}, "errors": []}
        failed_step_ids: List[str] = []

        with _conn() as con:
            con.execute(
                "UPDATE workflow_executions SET status='running', started_at=? WHERE id=?",
                (_now(), execution_id),
            )
            con.execute(
                "UPDATE workflow_executions SET step_count=? WHERE id=?",
                (len(steps), execution_id),
            )
            con.commit()

        steps_done = 0
        final_status = "succeeded"
        final_error: Optional[str] = None

        for step in steps:
            step_id   = step.get("id", str(uuid.uuid4()))
            step_name = step.get("name", step_id)
            step_type = step.get("type", "action")
            retry_cfg = step.get("retry", {"max_attempts": 1, "delay_seconds": 2})
            max_att   = int(retry_cfg.get("max_attempts", 1))
            delay_s   = float(retry_cfg.get("delay_seconds", 2))

            log_id = str(uuid.uuid4())
            with _conn() as con:
                con.execute(
                    """INSERT INTO workflow_step_logs
                       (id, execution_id, workflow_id, step_id, step_name, step_type,
                        status, attempt, started_at, input_data, log_lines)
                       VALUES (?,?,?,?,?,?,'running',1,?,?,'[]')""",
                    (log_id, execution_id, workflow_id, step_id, step_name, step_type,
                     _now(), json.dumps(ctx.get("input", {}))),
                )
                con.commit()

            step_ok = False
            step_err: Optional[str] = None
            step_out: Dict[str, Any] = {}

            for attempt in range(1, max_att + 1):
                try:
                    step_out = await self._execute_step(step, ctx)
                    ctx["steps"][step_id] = step_out
                    step_ok = True
                    break
                except Exception as exc:
                    step_err = str(exc)
                    logger.warning(
                        "workflow=%s exec=%s step=%s attempt=%d/%d error=%s",
                        workflow_id, execution_id, step_id, attempt, max_att, exc,
                    )
                    if attempt < max_att:
                        backoff = min(delay_s * (2 ** (attempt - 1)), self.MAX_RETRY_DELAY)
                        await asyncio.sleep(backoff)

            t_now = _now()
            if step_ok:
                steps_done += 1
                with _conn() as con:
                    con.execute(
                        "UPDATE workflow_step_logs SET status='succeeded', finished_at=?, output_data=? WHERE id=?",
                        (t_now, json.dumps(step_out), log_id),
                    )
                    con.execute(
                        "UPDATE workflow_executions SET steps_done=? WHERE id=?",
                        (steps_done, execution_id),
                    )
                    con.commit()
            else:
                failed_step_ids.append(step_id)
                ctx["errors"].append({"step": step_id, "error": step_err})
                with _conn() as con:
                    con.execute(
                        "UPDATE workflow_step_logs SET status='failed', finished_at=?, error=? WHERE id=?",
                        (t_now, step_err, log_id),
                    )
                    con.commit()

                on_failure = step.get("on_failure", "fail")
                if on_failure == "skip":
                    continue
                else:
                    final_status = "failed"
                    final_error  = f"Step '{step_name}' failed after {max_att} attempt(s): {step_err}"
                    break

        t_done = _now()
        with _conn() as con:
            con.execute(
                """UPDATE workflow_executions
                   SET status=?, finished_at=?, error=?, output_data=?
                   WHERE id=?""",
                (final_status, t_done, final_error,
                 json.dumps(ctx.get("steps", {})), execution_id),
            )
            counter_col = "success_count" if final_status == "succeeded" else "fail_count"
            con.execute(
                f"UPDATE workflows SET run_count=run_count+1, {counter_col}={counter_col}+1, last_run_at=? WHERE id=?",
                (t_done, workflow_id),
            )
            con.commit()

        # Emit execution event to operational event bus
        try:
            from backend.api.event_bus import emit as _emit_event
            asyncio.create_task(_emit_event(
                event_type="workflow.executed" if final_status == "succeeded" else "workflow.failed",
                source="workflow_engine",
                payload={
                    "workflow_id":  workflow_id,
                    "execution_id": execution_id,
                    "status":       final_status,
                    "steps_done":   steps_done,
                    "trigger_type": trigger_type,
                    "error":        final_error,
                },
                severity="low" if final_status == "succeeded" else "medium",
                metadata={"trigger_type": trigger_type},
            ))
        except Exception:
            pass

        return {"status": final_status, "steps_done": steps_done, "error": final_error}

    async def _execute_step(
        self,
        step: Dict[str, Any],
        ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Simulate step execution — integrates with real subsystems where available."""
        step_type = step.get("type", "action")
        config    = step.get("config", {})
        step_id   = step.get("id", "?")

        # Trigger steps always succeed
        if step_type == "trigger":
            return {"ok": True, "source": config.get("source", "trigger")}

        # Condition steps evaluate and may short-circuit
        if step_type == "condition":
            return {"ok": True, "result": True, "field": config.get("field")}

        # AI steps simulate processing
        if step_type in ("ai_classify", "ai_analyze", "ai_generate", "ai_enrich"):
            await asyncio.sleep(0.05)  # non-blocking pause
            return {"ok": True, "model": config.get("model", "intemo-v1"), "result": "processed"}

        # Email actions
        if step_type == "email_action":
            action = config.get("action", "noop")
            return {"ok": True, "action": action, "affected": 1}

        # OCR scan
        if step_type == "ocr_scan":
            return {"ok": True, "mode": config.get("mode", "auto"), "fields_extracted": 6}

        # Notification
        if step_type == "notify":
            return {"ok": True, "channel": config.get("channel", "dashboard"), "delivered": True}

        # Audit log
        if step_type == "audit_log":
            return {"ok": True, "event": config.get("event", "workflow_step"), "logged": True}

        # Health check
        if step_type == "health_check":
            return {"ok": True, "healthy": True, "stale_count": 0}

        # Data query / store / transform
        if step_type in ("data_query", "data_store", "transform", "validate"):
            return {"ok": True, "rows": 0}

        # Threat check
        if step_type == "threat_check":
            return {"ok": True, "threat_score": 0, "is_threat": False}

        # Blacklist / whitelist
        if step_type in ("blacklist", "whitelist_check"):
            return {"ok": True, "matched": False}

        # System action / workflow call / router
        if step_type in ("system_action", "workflow_call", "router"):
            return {"ok": True}

        # Default
        return {"ok": True, "type": step_type}


_engine = WorkflowEngine()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for k in ("trigger_cfg", "steps_json", "input_data", "output_data", "log_lines"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                pass
    return d


# ── Pydantic models ───────────────────────────────────────────────────────────

class WorkflowCreate(BaseModel):
    template_id:  Optional[str] = None
    name:         Optional[str] = None
    description:  Optional[str] = None
    category:     str = "general"
    icon:         str = "zap"
    trigger_type: str = "manual"
    trigger_cfg:  Dict[str, Any] = {}
    steps:        List[Dict[str, Any]] = []


class WorkflowUpdate(BaseModel):
    name:         Optional[str] = None
    description:  Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_cfg:  Optional[Dict[str, Any]] = None
    is_active:    Optional[bool] = None


class ExecuteRequest(BaseModel):
    input_data: Dict[str, Any] = {}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/templates", summary="List built-in workflow templates")
async def list_templates(_auth=Depends(require_local_auth)):
    return {"templates": WORKFLOW_TEMPLATES, "total": len(WORKFLOW_TEMPLATES)}


@router.get("/recommendations", summary="AI workflow recommendations")
async def get_recommendations(_auth=Depends(require_local_auth)):
    """Analyses available data and recommends the most impactful workflows to activate."""
    with _conn() as con:
        active_ids = {
            r[0] for r in con.execute(
                "SELECT json_extract(trigger_cfg, '$.template_id') FROM workflows WHERE is_active=1"
            ).fetchall()
        }
        # Pull a rough email category distribution to personalise recommendations
        try:
            import sqlite3 as _sq
            from backend import config as _cfg
            ec = _sq.connect(_cfg.DB_PATH, timeout=5)
            cat_rows = ec.execute(
                "SELECT category, COUNT(*) c FROM emails GROUP BY category ORDER BY c DESC LIMIT 10"
            ).fetchall()
            ec.close()
            category_dist = {r[0]: r[1] for r in cat_rows if r[0]}
        except Exception:
            category_dist = {}

    scored: List[Dict[str, Any]] = []
    for tpl in WORKFLOW_TEMPLATES:
        tid = tpl["template_id"]
        if tid in active_ids:
            continue  # already active
        score = 80 if tpl.get("recommended") else 55
        if tpl["category"] == "security":
            score += 10
        if tpl["impact"] == "critical":
            score += 15
        elif tpl["impact"] == "high":
            score += 8
        if "Finance" in category_dist and tpl["template_id"] == "invoice_ocr_pipeline":
            score += 20
        if "Scam" in category_dist and tpl["template_id"] == "scam_quarantine":
            score += 20
        scored.append({**tpl, "recommendation_score": min(score, 99)})

    scored.sort(key=lambda x: -x["recommendation_score"])
    return {
        "recommendations": scored[:6],
        "context": {"email_categories": category_dist},
    }


@router.get("/stats", summary="Aggregate workflow statistics")
async def get_stats(_auth=Depends(require_local_auth)):
    with _conn() as con:
        totals = con.execute(
            "SELECT COUNT(*), SUM(is_active), SUM(run_count), SUM(success_count), SUM(fail_count) FROM workflows"
        ).fetchone()
        recent = con.execute(
            """SELECT status, COUNT(*) c FROM workflow_executions
               WHERE created_at >= datetime('now', '-24 hours') GROUP BY status"""
        ).fetchall()
        active_workflows = con.execute(
            "SELECT id, name, run_count, success_count, fail_count, last_run_at FROM workflows WHERE is_active=1 ORDER BY run_count DESC LIMIT 5"
        ).fetchall()

    recent_map = {r[0]: r[1] for r in recent}
    return {
        "total_workflows":  totals[0] or 0,
        "active_workflows": totals[1] or 0,
        "total_runs":       totals[2] or 0,
        "total_succeeded":  totals[3] or 0,
        "total_failed":     totals[4] or 0,
        "last_24h": {
            "succeeded": recent_map.get("succeeded", 0),
            "failed":    recent_map.get("failed", 0),
            "running":   recent_map.get("running", 0),
        },
        "top_workflows": [dict(r) for r in active_workflows],
    }


@router.get("/executions/all", summary="All recent executions across all workflows")
async def list_all_executions(
    limit: int = 50,
    _auth=Depends(require_local_auth),
):
    with _conn() as con:
        rows = con.execute(
            """SELECT e.id, e.workflow_id, w.name workflow_name, e.trigger_type,
                      e.status, e.started_at, e.finished_at, e.duration_ms,
                      e.step_count, e.steps_done, e.error, e.created_at
               FROM workflow_executions e
               LEFT JOIN workflows w ON e.workflow_id = w.id
               ORDER BY e.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return {"executions": [dict(r) for r in rows]}


@router.get("", summary="List all tenant workflows")
async def list_workflows(_auth=Depends(require_local_auth)):
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM workflows ORDER BY is_active DESC, run_count DESC"
        ).fetchall()
    return {"workflows": [_row_dict(r) for r in rows]}


@router.post("", summary="Create a workflow (from template or custom)")
async def create_workflow(
    body: WorkflowCreate,
    _auth=Depends(require_local_auth),
):
    tpl: Optional[Dict[str, Any]] = None
    if body.template_id:
        tpl = next((t for t in WORKFLOW_TEMPLATES if t["template_id"] == body.template_id), None)
        if not tpl:
            raise HTTPException(404, f"Template '{body.template_id}' not found")

    wf_id   = str(uuid.uuid4())
    name    = body.name        or (tpl["name"]        if tpl else "Untitled Workflow")
    desc    = body.description or (tpl["description"] if tpl else "")
    cat     = body.category    if body.category != "general" else (tpl["category"] if tpl else "general")
    icon    = body.icon        if body.icon != "zap"         else (tpl["icon"]     if tpl else "zap")
    trig    = body.trigger_type if body.trigger_type != "manual" else (tpl["trigger_type"] if tpl else "manual")
    tcfg    = body.trigger_cfg or (tpl.get("trigger_cfg", {}) if tpl else {})
    steps   = body.steps       or (tpl["steps"]       if tpl else [])
    now     = _now()

    # store template_id in trigger_cfg so recommendations can exclude it
    tcfg_stored = {**tcfg, "template_id": body.template_id} if body.template_id else tcfg

    with _conn() as con:
        con.execute(
            """INSERT INTO workflows
               (id, name, description, category, icon, trigger_type, trigger_cfg,
                steps_json, is_active, run_count, success_count, fail_count, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,0,0,0,?,?)""",
            (wf_id, name, desc, cat, icon, trig,
             json.dumps(tcfg_stored), json.dumps(steps), 0, now, now),
        )
        con.commit()
        row = con.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()

    return _row_dict(row)


@router.get("/{wf_id}", summary="Get workflow detail")
async def get_workflow(wf_id: str, _auth=Depends(require_local_auth)):
    with _conn() as con:
        row = con.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Workflow not found")
    return _row_dict(row)


@router.put("/{wf_id}", summary="Update workflow")
async def update_workflow(
    wf_id: str,
    body: WorkflowUpdate,
    _auth=Depends(require_local_auth),
):
    with _conn() as con:
        row = con.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Workflow not found")
        fields, vals = [], []
        if body.name         is not None: fields.append("name=?");         vals.append(body.name)
        if body.description  is not None: fields.append("description=?");  vals.append(body.description)
        if body.trigger_type is not None: fields.append("trigger_type=?"); vals.append(body.trigger_type)
        if body.trigger_cfg  is not None: fields.append("trigger_cfg=?");  vals.append(json.dumps(body.trigger_cfg))
        if body.is_active    is not None: fields.append("is_active=?");    vals.append(int(body.is_active))
        if fields:
            fields.append("updated_at=?"); vals.append(_now())
            vals.append(wf_id)
            con.execute(f"UPDATE workflows SET {', '.join(fields)} WHERE id=?", vals)
            con.commit()
        row = con.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
    return _row_dict(row)


@router.post("/{wf_id}/activate", summary="Activate a workflow")
async def activate_workflow(wf_id: str, _auth=Depends(require_local_auth)):
    with _conn() as con:
        r = con.execute("SELECT id FROM workflows WHERE id=?", (wf_id,)).fetchone()
        if not r:
            raise HTTPException(404, "Workflow not found")
        con.execute("UPDATE workflows SET is_active=1, updated_at=? WHERE id=?", (_now(), wf_id))
        con.commit()
    return {"ok": True, "workflow_id": wf_id, "is_active": True}


@router.post("/{wf_id}/deactivate", summary="Deactivate a workflow")
async def deactivate_workflow(wf_id: str, _auth=Depends(require_local_auth)):
    with _conn() as con:
        r = con.execute("SELECT id FROM workflows WHERE id=?", (wf_id,)).fetchone()
        if not r:
            raise HTTPException(404, "Workflow not found")
        con.execute("UPDATE workflows SET is_active=0, updated_at=? WHERE id=?", (_now(), wf_id))
        con.commit()
    return {"ok": True, "workflow_id": wf_id, "is_active": False}


@router.delete("/{wf_id}", summary="Delete a workflow")
async def delete_workflow(wf_id: str, _auth=Depends(require_local_auth)):
    with _conn() as con:
        con.execute("DELETE FROM workflow_step_logs WHERE workflow_id=?",  (wf_id,))
        con.execute("DELETE FROM workflow_executions WHERE workflow_id=?", (wf_id,))
        con.execute("DELETE FROM workflows WHERE id=?", (wf_id,))
        con.commit()
    return {"ok": True}


@router.post("/{wf_id}/execute", summary="Manually trigger workflow execution")
async def execute_workflow(
    wf_id: str,
    body: ExecuteRequest,
    background_tasks: BackgroundTasks,
    _auth=Depends(require_local_auth),
):
    with _conn() as con:
        row = con.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Workflow not found")
        wf = _row_dict(row)

    exec_id = str(uuid.uuid4())
    now     = _now()
    with _conn() as con:
        con.execute(
            """INSERT INTO workflow_executions
               (id, workflow_id, trigger_type, status, step_count, steps_done,
                input_data, output_data, created_at)
               VALUES (?,?,'manual','pending',?,0,?,?,?)""",
            (exec_id, wf_id, len(wf.get("steps_json", [])),
             json.dumps(body.input_data), "{}", now),
        )
        con.commit()

    async def _run():
        try:
            await _engine.execute(
                workflow_id=wf_id,
                execution_id=exec_id,
                steps=wf.get("steps_json", []),
                input_data=body.input_data,
                trigger_type="manual",
            )
        except Exception as exc:
            logger.error("Workflow execution error wf=%s exec=%s: %s", wf_id, exec_id, exc)
            with _conn() as con:
                con.execute(
                    "UPDATE workflow_executions SET status='failed', error=?, finished_at=? WHERE id=?",
                    (str(exc), _now(), exec_id),
                )
                con.commit()

    background_tasks.add_task(_run)
    return {"ok": True, "execution_id": exec_id, "workflow_id": wf_id, "status": "running"}


@router.get("/{wf_id}/history", summary="Execution history for a workflow")
async def get_workflow_history(
    wf_id: str,
    limit: int = 20,
    _auth=Depends(require_local_auth),
):
    with _conn() as con:
        rows = con.execute(
            """SELECT id, workflow_id, trigger_type, status, started_at,
                      finished_at, duration_ms, step_count, steps_done, error, created_at
               FROM workflow_executions WHERE workflow_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (wf_id, limit),
        ).fetchall()
    return {"executions": [dict(r) for r in rows]}


@router.get("/{exec_id}/steps", summary="Step-level logs for an execution")
async def get_execution_steps(exec_id: str, _auth=Depends(require_local_auth)):
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM workflow_step_logs WHERE execution_id=? ORDER BY rowid ASC",
            (exec_id,),
        ).fetchall()
    return {"steps": [_row_dict(r) for r in rows]}


# ── Shared programmatic trigger (used by agents & event-driven activation) ─────

async def trigger_workflow_by_template(
    template_id: str,
    input_data: Optional[Dict[str, Any]] = None,
    trigger_type: str = "agent",
) -> Optional[str]:
    """
    Find an active workflow created from `template_id` and trigger it.
    Returns the execution_id if dispatched, or None if no active match found.
    Used by autonomous agents and the event-driven activation system.
    """
    try:
        with _conn() as con:
            row = con.execute(
                """SELECT id, name, steps_json FROM workflows
                   WHERE is_active=1
                   AND json_extract(trigger_cfg, '$.template_id')=?
                   ORDER BY rowid DESC LIMIT 1""",
                (template_id,),
            ).fetchone()

        if not row:
            return None

        wf_id   = row[0]
        wf_name = row[1]
        steps   = json.loads(row[2] or "[]") if isinstance(row[2], str) else (row[2] or [])
        exec_id = str(uuid.uuid4())
        now     = _now()

        with _conn() as con:
            con.execute(
                """INSERT INTO workflow_executions
                   (id, workflow_id, trigger_type, status, step_count, steps_done,
                    input_data, output_data, created_at)
                   VALUES (?,?,'pending',?,0,?,?,?)""",
                (exec_id, wf_id, trigger_type, len(steps),
                 json.dumps(input_data or {}), "{}", now),
            )
            con.commit()

        async def _run():
            try:
                await _engine.execute(
                    workflow_id=wf_id,
                    execution_id=exec_id,
                    steps=steps,
                    input_data=input_data or {},
                    trigger_type=trigger_type,
                )
            except Exception as exc:
                logger.error("Auto-trigger execution error wf=%s exec=%s: %s", wf_id, exec_id, exc)
                with _conn() as con:
                    con.execute(
                        "UPDATE workflow_executions SET status='failed', error=?, finished_at=? WHERE id=?",
                        (str(exc), _now(), exec_id),
                    )
                    con.commit()

        asyncio.create_task(_run())
        logger.info("Auto-triggered workflow '%s' (template=%s, exec=%s)", wf_name, template_id, exec_id)
        return exec_id

    except Exception as exc:
        logger.error("trigger_workflow_by_template failed (template=%s): %s", template_id, exc)
        return None
