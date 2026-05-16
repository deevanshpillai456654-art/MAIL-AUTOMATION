"""
Safe guided-action registry.

Every action that the assistant can execute on behalf of the user lives here.
Actions are:
  - explicitly whitelisted (no arbitrary code execution)
  - documented with impact and rollback info
  - logged to audit trail
  - safe to retry

Actions that are destructive or irreversible require confirm_required=True,
which the API enforces before calling execute().
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from backend import config

logger = logging.getLogger("assistant.actions")


@dataclass
class ActionDefinition:
    id: str
    label: str
    description: str
    impact: str                         # plain-English impact explanation
    rollback: str                       # what happens if user wants to undo
    confirm_required: bool
    admin_only: bool
    safe: bool = True                   # False = destructive, requires extra confirmation


@dataclass
class ActionResult:
    success: bool
    message: str
    detail: str = ""
    data: Dict[str, Any] = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}


# ── action registry ───────────────────────────────────────────────────────────

_REGISTRY: Dict[str, ActionDefinition] = {}
_HANDLERS: Dict[str, Callable[..., ActionResult]] = {}


def _register(defn: ActionDefinition, handler: Callable[..., ActionResult]) -> None:
    _REGISTRY[defn.id] = defn
    _HANDLERS[defn.id] = handler


# ── action: restart sync ──────────────────────────────────────────────────────

def _restart_sync(params: Dict[str, Any]) -> ActionResult:
    from backend.scheduler.tasks import scheduler
    task = scheduler.get_task("sync_emails")
    if task is None:
        return ActionResult(False, "Sync task not found in scheduler")
    task.next_run = None         # force immediate execution next tick
    task.enabled = True
    logger.info("Assistant action: sync_emails task reset for immediate run")
    return ActionResult(True, "Sync engine reset — will start within 30 seconds",
                        detail="The sync task's next_run was cleared. The scheduler will pick it up on the next tick.")


_register(
    ActionDefinition(
        id="restart_sync",
        label="Restart Sync Engine",
        description="Reset the sync scheduler to run immediately on all connected accounts.",
        impact="Sync will restart from the last checkpoint. No emails are deleted or duplicated. Expected completion: 30 seconds–3 minutes.",
        rollback="Not needed — this action is read-safe. Sync will run as normal after restart.",
        confirm_required=True,
        admin_only=False,
    ),
    _restart_sync,
)

# ── action: reconnect OAuth ───────────────────────────────────────────────────

def _reconnect_oauth(params: Dict[str, Any]) -> ActionResult:
    account_id = params.get("account_id")
    if account_id:
        return ActionResult(
            True,
            "Navigate to Accounts → Reconnect to re-authorise this account",
            detail=f"Open the Accounts panel, find account #{account_id}, and click Reconnect.",
            data={"redirect": "/dashboard#accounts"},
        )
    return ActionResult(
        True,
        "Open the Accounts panel to reconnect your account",
        detail="In the left sidebar, click Accounts. Find the disconnected account and click Reconnect.",
        data={"redirect": "/dashboard#accounts"},
    )


_register(
    ActionDefinition(
        id="reconnect_oauth",
        label="Reconnect Account",
        description="Guide the user through re-authorising a disconnected OAuth account.",
        impact="Redirects to the OAuth consent page. No data is lost. Sync resumes after reconnection.",
        rollback="You can revoke INTEMO's access again at any time via Google/Microsoft account settings.",
        confirm_required=False,
        admin_only=False,
    ),
    _reconnect_oauth,
)

# ── action: retry stale jobs ──────────────────────────────────────────────────

def _retry_stale_jobs(params: Dict[str, Any]) -> ActionResult:
    import sqlite3
    job_db = os.path.join(os.path.dirname(config.DB_PATH), "job_queue.db")
    if not os.path.exists(job_db):
        return ActionResult(False, "Job queue database not found")
    try:
        conn = sqlite3.connect(job_db, timeout=10, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        cutoff = time.time() - 300   # jobs leased > 5 min ago
        cur = conn.execute(
            "UPDATE persistent_jobs SET status='pending', lease_expires_at=NULL "
            "WHERE status='leased' AND updated_at < ?",
            (cutoff,),
        )
        recovered = cur.rowcount
        conn.close()
        logger.info("Assistant action: recovered %d stale job leases", recovered)
        if recovered:
            return ActionResult(True, f"Recovered {recovered} stale job(s) — they will be retried automatically")
        return ActionResult(True, "No stale jobs found — queue is clean")
    except Exception as exc:
        logger.warning("retry_stale_jobs failed: %s", exc)
        return ActionResult(False, f"Could not access job queue: {exc}")


_register(
    ActionDefinition(
        id="retry_stale_jobs",
        label="Retry Stale Jobs",
        description="Reset job leases older than 5 minutes so they are retried automatically.",
        impact="Stale sync and OAuth jobs are returned to 'pending' state and will re-run within 2 seconds.",
        rollback="Jobs will simply retry. If the underlying issue persists they will fail again — which is safe.",
        confirm_required=False,
        admin_only=False,
    ),
    _retry_stale_jobs,
)

# ── action: run DB maintenance ────────────────────────────────────────────────

def _run_db_maintenance(params: Dict[str, Any]) -> ActionResult:
    from backend.core.db_maintenance import prune_job_queue, prune_app_db, run_wal_checkpoint
    import pathlib
    job_db = pathlib.Path(os.path.dirname(config.DB_PATH)) / "job_queue.db"
    try:
        pruned_jobs = prune_job_queue(job_db)
        pruned_app  = prune_app_db(config.DB_PATH)
        wal_results = run_wal_checkpoint([config.DB_PATH, str(job_db)])
        total_pruned = pruned_jobs + sum(pruned_app.values())
        total_ckpt   = sum(v for v in wal_results.values() if v > 0)
        logger.info("Assistant action: DB maintenance pruned=%d wal_pages=%d", total_pruned, total_ckpt)
        return ActionResult(
            True,
            f"Maintenance complete — pruned {total_pruned} old records, checkpointed {total_ckpt} WAL pages",
            detail="Old job queue entries and sync logs removed. WAL file compacted.",
            data={"pruned_records": total_pruned, "wal_pages": total_ckpt},
        )
    except Exception as exc:
        logger.warning("run_db_maintenance failed: %s", exc)
        return ActionResult(False, f"Maintenance failed: {exc}")


_register(
    ActionDefinition(
        id="run_db_maintenance",
        label="Run DB Maintenance",
        description="Prune old job records and run a WAL checkpoint on all databases.",
        impact="Removes old completed/failed job records and compacts the WAL file. No user data is deleted. Takes 1–3 seconds.",
        rollback="This operation only removes operational metadata (job history, sync logs). It cannot be undone but has no user-visible effect.",
        confirm_required=False,
        admin_only=False,
    ),
    _run_db_maintenance,
)

# ── action: run health check ──────────────────────────────────────────────────

def _run_health_check(params: Dict[str, Any]) -> ActionResult:
    from backend.core.assistant.diagnostics_engine import get_diagnostics_engine
    report = get_diagnostics_engine().run(admin=params.get("admin", False))
    return ActionResult(
        True,
        f"Health check complete — overall: {report.overall}",
        detail="; ".join(f"{c.name}: {c.status}" for c in report.components),
        data={
            "overall": report.overall,
            "detected_issues": report.detected_issues,
            "recommendations": report.recommendations,
            "components": [{"name": c.name, "status": c.status, "message": c.message} for c in report.components],
        },
    )


_register(
    ActionDefinition(
        id="run_health_check",
        label="Run Health Check",
        description="Run a full diagnostic scan of all INTEMO components.",
        impact="Read-only. Queries system metrics, database, job queue, and accounts. Takes under 2 seconds.",
        rollback="N/A — read-only operation.",
        confirm_required=False,
        admin_only=False,
    ),
    _run_health_check,
)

# ── action: trigger manual sync ──────────────────────────────────────────────

def _trigger_manual_sync(params: Dict[str, Any]) -> ActionResult:
    from backend.scheduler.tasks import scheduler
    task = scheduler.get_task("sync_emails")
    if task is None:
        return ActionResult(False, "Sync task not registered in scheduler")
    task.next_run = None
    task.enabled = True
    logger.info("Assistant action: manual sync triggered")
    return ActionResult(True, "Manual sync triggered — will run within 30 seconds",
                        detail="Sync task reset to run on next scheduler tick.")


_register(
    ActionDefinition(
        id="trigger_manual_sync",
        label="Sync Now",
        description="Trigger an immediate sync cycle.",
        impact="Starts a full sync cycle. Runs in the background. No emails are deleted.",
        rollback="N/A — read-only operation that simply starts sync.",
        confirm_required=False,
        admin_only=False,
    ),
    _trigger_manual_sync,
)

# ── action: reload rules ──────────────────────────────────────────────────────

def _reload_rules(params: Dict[str, Any]) -> ActionResult:
    logger.info("Assistant action: rules engine reload requested")
    return ActionResult(
        True,
        "Rules will be reloaded on next email processing cycle",
        detail="The rules engine reads from the database on each evaluation pass, so no explicit reload is needed.",
    )


_register(
    ActionDefinition(
        id="reload_rules",
        label="Reload Rules",
        description="Signal the rules engine to reload all rules on next pass.",
        impact="New/changed rules will take effect immediately on the next incoming email.",
        rollback="N/A — rules are always read fresh from the database.",
        confirm_required=False,
        admin_only=False,
    ),
    _reload_rules,
)

# ── action: check scheduler status (admin) ────────────────────────────────────

def _check_scheduler_status(params: Dict[str, Any]) -> ActionResult:
    from backend.scheduler.tasks import scheduler
    data = scheduler.get_status()
    return ActionResult(True, "Scheduler status retrieved", data=data)


_register(
    ActionDefinition(
        id="check_scheduler_status",
        label="View Scheduler Status",
        description="Return current scheduler task states and next-run times.",
        impact="Read-only.",
        rollback="N/A.",
        confirm_required=False,
        admin_only=True,
    ),
    _check_scheduler_status,
)

# ── action: fetch recent logs (admin) ─────────────────────────────────────────

def _fetch_recent_logs(params: Dict[str, Any]) -> ActionResult:
    log_path = os.path.join(config.LOG_DIR, "service.log")
    if not os.path.exists(log_path):
        return ActionResult(False, "service.log not found", detail=f"Expected: {log_path}")
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        tail = lines[-200:]          # last 200 lines only
        # redact any obvious secrets before returning
        safe_lines = []
        for line in tail:
            for pattern in ("token=", "password=", "secret=", "key=", "Bearer "):
                if pattern.lower() in line.lower():
                    line = "[REDACTED LINE]"
                    break
            safe_lines.append(line.rstrip())
        return ActionResult(True, f"Last {len(safe_lines)} log lines", data={"lines": safe_lines})
    except Exception as exc:
        return ActionResult(False, f"Cannot read log: {exc}")


_register(
    ActionDefinition(
        id="fetch_recent_logs",
        label="View Recent Logs",
        description="Return the last 200 lines of the service log (admin only, redacted).",
        impact="Read-only. Sensitive values are redacted.",
        rollback="N/A.",
        confirm_required=False,
        admin_only=True,
    ),
    _fetch_recent_logs,
)

# ── action: inspect token health (admin) ─────────────────────────────────────

def _inspect_token_health(params: Dict[str, Any]) -> ActionResult:
    from backend.db.database import Database
    db = Database(config.DB_PATH)
    try:
        rows = db.fetch_all(
            "SELECT id, email, provider, status, last_error, token_expiry "
            "FROM accounts ORDER BY id"
        ) or []
    except Exception as exc:
        return ActionResult(False, f"Cannot query accounts: {exc}")

    now = time.time()
    summary = []
    for r in rows:
        expiry = r.get("token_expiry")
        status = r.get("status", "unknown")
        try:
            expires_in = int(float(expiry) - now) if expiry else None
        except (TypeError, ValueError):
            expires_in = None
        summary.append({
            "id": r.get("id"),
            "email": r.get("email"),
            "provider": r.get("provider"),
            "status": status,
            "expires_in_seconds": expires_in,
            "expired": expires_in is not None and expires_in < 0,
            "last_error": r.get("last_error"),
        })
    expired = sum(1 for s in summary if s["expired"])
    return ActionResult(
        True,
        f"Token health: {len(summary)} accounts, {expired} with expired tokens",
        data={"accounts": summary},
    )


_register(
    ActionDefinition(
        id="inspect_token_health",
        label="Inspect Token Health",
        description="Check OAuth token expiry and status for all accounts (admin).",
        impact="Read-only. Token values are not returned — only metadata.",
        rollback="N/A.",
        confirm_required=False,
        admin_only=True,
    ),
    _inspect_token_health,
)

# ── action: check backend binding (admin) ─────────────────────────────────────

def _check_backend_binding(params: Dict[str, Any]) -> ActionResult:
    return ActionResult(
        True,
        f"Backend is configured to bind on {config.API_HOST}:{config.API_PORT}",
        detail="If the extension cannot connect, verify no firewall or antivirus is blocking loopback traffic on this port.",
        data={"host": config.API_HOST, "port": config.API_PORT},
    )


_register(
    ActionDefinition(
        id="check_backend_binding",
        label="Check Backend Binding",
        description="Return the host/port the backend is bound to.",
        impact="Read-only.",
        rollback="N/A.",
        confirm_required=False,
        admin_only=True,
    ),
    _check_backend_binding,
)

# ── public API ────────────────────────────────────────────────────────────────

class ActionHandler:

    def list_actions(self, admin: bool = False) -> List[Dict[str, Any]]:
        return [
            {
                "id": d.id,
                "label": d.label,
                "description": d.description,
                "impact": d.impact,
                "rollback": d.rollback,
                "confirm_required": d.confirm_required,
                "admin_only": d.admin_only,
            }
            for d in _REGISTRY.values()
            if admin or not d.admin_only
        ]

    def get_definition(self, action_id: str) -> Optional[ActionDefinition]:
        return _REGISTRY.get(action_id)

    def execute(self, action_id: str, params: Dict[str, Any] | None = None, admin: bool = False) -> ActionResult:
        defn = _REGISTRY.get(action_id)
        if defn is None:
            return ActionResult(False, f"Unknown action: {action_id}")
        if defn.admin_only and not admin:
            return ActionResult(False, "This action requires admin mode")
        handler = _HANDLERS.get(action_id)
        if handler is None:
            return ActionResult(False, "Action has no handler registered")
        try:
            result = handler(params or {})
            logger.info("Action executed: %s success=%s", action_id, result.success)
            return result
        except Exception as exc:
            logger.exception("Action %s raised: %s", action_id, exc)
            return ActionResult(False, f"Action failed unexpectedly: {exc}")


_handler: Optional[ActionHandler] = None


def get_action_handler() -> ActionHandler:
    global _handler
    if _handler is None:
        _handler = ActionHandler()
    return _handler
