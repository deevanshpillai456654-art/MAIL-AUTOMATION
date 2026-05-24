"""
Diagnostics engine — aggregates data from all existing health systems.

Integrates with:
  - backend/api/health_checks.py  (CPU, memory, disk, DB)
  - backend/api/health.py         (get_db_status, get_system_status)
  - backend/core/job_runner.py    (job runner status)
  - backend/scheduler/tasks.py    (scheduler status)
  - backend/db/database.py        (sync status, account health)
  - backend/core/db_maintenance.py (WAL / storage)

Returns a normalised DiagnosticsReport that the FlowEngine and API use to
auto-detect relevant issues and pre-fill session context.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend import config

logger = logging.getLogger("assistant.diagnostics")


# ── report model ──────────────────────────────────────────────────────────────

@dataclass
class ComponentStatus:
    name: str
    status: str          # "healthy" | "degraded" | "unhealthy" | "unknown"
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticsReport:
    timestamp: float
    overall: str                              # "healthy" | "degraded" | "unhealthy"
    components: List[ComponentStatus]
    detected_issues: List[str]                # list of issue IDs from knowledge base
    signals: Dict[str, Any]                   # raw signal bag for FlowEngine
    recommendations: List[str]               # human-readable quick tips
    admin_context: Dict[str, Any] = field(default_factory=dict)


# ── helpers ───────────────────────────────────────────────────────────────────

def _safe(fn, default=None):
    try:
        return fn()
    except Exception as exc:
        logger.debug("Diagnostics probe failed: %s", exc)
        return default


def _status(value: str) -> str:
    v = (value or "").lower()
    if v in ("healthy", "ok", "connected", "running", "up", "active"):
        return "healthy"
    if v in ("degraded", "warning", "slow", "limited"):
        return "degraded"
    if v in ("unhealthy", "error", "failed", "disconnected", "offline", "locked"):
        return "unhealthy"
    return "unknown"


# ── probe functions ───────────────────────────────────────────────────────────

def _probe_system() -> ComponentStatus:
    from backend.api.health_checks import check_cpu_health, check_disk_health, check_memory_health
    cpu  = _safe(check_cpu_health)
    mem  = _safe(check_memory_health)
    disk = _safe(check_disk_health)

    issues = []
    meta: Dict[str, Any] = {}
    if cpu:
        meta["cpu_pct"] = cpu.metadata.get("percent", 0)
        if cpu.status.value in ("degraded", "unhealthy"):
            issues.append(cpu.message)
    if mem:
        meta["mem_pct"] = mem.metadata.get("percent", 0)
        if mem.status.value in ("degraded", "unhealthy"):
            issues.append(mem.message)
    if disk:
        meta["disk_pct"] = disk.metadata.get("percent", 0)
        if disk.status.value in ("degraded", "unhealthy"):
            issues.append(disk.message)

    worst = "healthy"
    for chk in [cpu, mem, disk]:
        if chk and chk.status.value == "unhealthy":
            worst = "unhealthy"
            break
        if chk and chk.status.value == "degraded":
            worst = "degraded"

    return ComponentStatus(
        name="system",
        status=worst,
        message="; ".join(issues) if issues else "System resources normal",
        metadata=meta,
    )


def _probe_database() -> ComponentStatus:
    from backend.api.health import get_db_status
    data = _safe(get_db_status, default={})
    connected = data.get("connected", False)
    meta = {k: v for k, v in data.items() if k != "connected"}
    return ComponentStatus(
        name="database",
        status="healthy" if connected else "unhealthy",
        message="Database connected" if connected else data.get("error", "Database unreachable"),
        metadata=meta,
    )


def _probe_accounts() -> ComponentStatus:
    """Check OAuth/account health from DB."""
    from backend.db.database import Database
    db = Database(config.DB_PATH)
    try:
        rows = db.fetch_all(
            "SELECT id, email, provider, status, last_error, last_sync_at "
            "FROM accounts ORDER BY id"
        ) or []
    except Exception as exc:
        return ComponentStatus("accounts", "unknown", f"Cannot read accounts: {exc}")

    total = len(rows)
    disconnected = [r for r in rows if (r.get("status") or "").lower() in ("error", "disconnected", "reconnect_required")]
    synced_recently = [
        r for r in rows
        if r.get("last_sync_at") and (time.time() - float(r["last_sync_at"] or 0)) < 3600
    ]
    never_synced = [r for r in rows if not r.get("last_sync_at")]

    if total == 0:
        status = "degraded"
        msg = "No email accounts connected"
    elif disconnected:
        status = "unhealthy"
        msg = f"{len(disconnected)} account(s) require reconnection"
    else:
        status = "healthy"
        msg = f"{total} account(s) connected"

    return ComponentStatus(
        name="accounts",
        status=status,
        message=msg,
        metadata={
            "total": total,
            "disconnected": len(disconnected),
            "disconnected_accounts": [r.get("email", "") for r in disconnected],
            "synced_recently": len(synced_recently),
            "never_synced": len(never_synced),
        },
    )


def _probe_sync() -> ComponentStatus:
    """Detect stale syncs, stuck jobs, and accounts that haven't synced."""
    import sqlite3

    from backend.db.database import Database
    db = Database(config.DB_PATH)

    # check for stale sync_status rows
    stale_syncs = 0
    try:
        cutoff_ts = time.time() - 600  # 10 minutes
        rows = db.fetch_all(
            "SELECT id FROM sync_status "
            "WHERE status = 'running' AND started_at < datetime(?, 'unixepoch')",
            (cutoff_ts,),
        ) or []
        stale_syncs = len(rows)
    except Exception:
        pass

    # check job queue for stale leases
    stale_jobs = 0
    job_queue_path = os.path.join(config.DATA_DIR, "job_queue.db")

    if os.path.exists(job_queue_path):
        try:
            conn = sqlite3.connect(job_queue_path, timeout=5)
            cutoff = time.time() - 600
            row = conn.execute(
                "SELECT COUNT(*) FROM persistent_jobs WHERE status='leased' AND updated_at < ?",
                (cutoff,),
            ).fetchone()
            stale_jobs = int(row[0]) if row else 0
            conn.close()
        except Exception:
            pass

    if stale_syncs > 0 or stale_jobs > 0:
        status = "degraded"
        msg = f"Stale sync detected ({stale_syncs} running, {stale_jobs} stuck jobs)"
    else:
        status = "healthy"
        msg = "Sync engine healthy"

    return ComponentStatus(
        name="sync",
        status=status,
        message=msg,
        metadata={"stale_syncs": stale_syncs, "stale_jobs": stale_jobs},
    )


def _probe_job_runner() -> ComponentStatus:
    from backend.core.job_runner import get_job_runner
    runner = _safe(get_job_runner)
    if runner is None:
        return ComponentStatus("job_runner", "unknown", "Job runner not initialized")
    data = _safe(runner.status, default={}) or {}
    running = data.get("running", False)
    return ComponentStatus(
        name="job_runner",
        status="healthy" if running else "unhealthy",
        message="Job runner active" if running else "Job runner stopped",
        metadata=data,
    )


def _probe_scheduler() -> ComponentStatus:
    from backend.scheduler.tasks import scheduler
    data = _safe(scheduler.get_status, default={}) or {}
    running = data.get("running", False)
    tasks = data.get("tasks", [])
    sync_task = next((t for t in tasks if t.get("id") == "sync_emails"), None)
    sync_enabled = sync_task.get("enabled", False) if sync_task else False

    if not running:
        return ComponentStatus("scheduler", "unhealthy", "Scheduler not running", metadata=data)
    if not sync_enabled:
        return ComponentStatus("scheduler", "degraded", "Sync task is disabled", metadata=data)
    return ComponentStatus("scheduler", "healthy", "Scheduler running, sync enabled", metadata=data)


def _probe_database_health_detail() -> ComponentStatus:
    """Check WAL size and DB integrity."""
    db_path = config.DB_PATH
    if not os.path.exists(db_path):
        return ComponentStatus("database_files", "unknown", "DB file not found")
    wal_path = db_path + "-wal"
    wal_size_mb = 0.0
    if os.path.exists(wal_path):
        wal_size_mb = os.path.getsize(wal_path) / 1_048_576

    if wal_size_mb > 100:
        status = "degraded"
        msg = f"WAL file large ({wal_size_mb:.1f} MB) — checkpoint recommended"
    else:
        status = "healthy"
        msg = f"WAL size normal ({wal_size_mb:.1f} MB)"

    return ComponentStatus(
        name="database_files",
        status=status,
        message=msg,
        metadata={"wal_size_mb": round(wal_size_mb, 2)},
    )


# ── issue auto-detection ──────────────────────────────────────────────────────

def _detect_issues(components: List[ComponentStatus]) -> tuple[List[str], Dict[str, Any], List[str]]:
    """Map component health to issue IDs from the knowledge base."""
    by_name = {c.name: c for c in components}
    signals: Dict[str, Any] = {}
    detected: List[str] = []
    recs: List[str] = []

    # accounts
    acct = by_name.get("accounts")
    if acct:
        disc = acct.metadata.get("disconnected", 0)
        total = acct.metadata.get("total", 0)
        signals["disconnected_accounts"] = disc
        signals["oauth_errors"] = disc > 0
        signals["no_accounts"] = total == 0
        if total == 0:
            detected.append("first_time_setup")
            recs.append("Connect your first email account to start syncing.")
        elif disc > 0:
            detected.append("oauth_disconnected")
            names = acct.metadata.get("disconnected_accounts", [])
            recs.append(f"Reconnect {disc} account(s): {', '.join(names[:3])}")

    # sync
    sync = by_name.get("sync")
    if sync and sync.status != "healthy":
        stale_syncs = sync.metadata.get("stale_syncs", 0)
        stale_jobs = sync.metadata.get("stale_jobs", 0)
        signals["stale_sync_jobs"] = stale_jobs
        signals["sync_duration_exceeded"] = stale_syncs > 0
        detected.append("sync_stuck")
        recs.append("Sync appears stuck. Restart the sync engine.")

    # scheduler
    sched = by_name.get("scheduler")
    if sched:
        signals["sync_task_disabled"] = sched.status == "degraded"
        if sched.status == "degraded":
            detected.append("sync_not_starting")
            recs.append("Auto-sync is disabled. Enable it in Settings → Sync.")

    # system resources
    sys_c = by_name.get("system")
    if sys_c:
        cpu = sys_c.metadata.get("cpu_pct", 0)
        mem = sys_c.metadata.get("mem_pct", 0)
        signals["high_cpu"] = cpu > 70
        signals["high_memory"] = mem > 80
        if cpu > 70 or mem > 80:
            detected.append("high_resource_usage")
            recs.append(f"High resource usage detected (CPU {cpu:.0f}%, RAM {mem:.0f}%).")

    # database
    db = by_name.get("database")
    if db and db.status == "unhealthy":
        signals["database_locked"] = "locked" in db.message.lower()
        signals["backend_health_failed"] = True
        if signals["database_locked"]:
            detected.append("database_locked")
        detected.append("backend_not_responding")
        recs.append("Backend database is not healthy — restart INTEMO.")

    db_files = by_name.get("database_files")
    if db_files and db_files.status == "degraded":
        if "database_locked" not in detected:
            detected.append("database_locked")
        recs.append("WAL file is large — run DB maintenance to reclaim space.")

    # job runner
    jr = by_name.get("job_runner")
    if jr and jr.status == "unhealthy":
        signals["backend_health_failed"] = True
        if "backend_not_responding" not in detected:
            detected.append("backend_not_responding")

    return detected, signals, recs


# ── main engine ───────────────────────────────────────────────────────────────

class DiagnosticsEngine:

    def run(self, admin: bool = False) -> DiagnosticsReport:
        """Run all probes and return a complete report."""
        t0 = time.time()
        components = [
            _safe(_probe_system) or ComponentStatus("system", "unknown", "Probe failed"),
            _safe(_probe_database) or ComponentStatus("database", "unknown", "Probe failed"),
            _safe(_probe_database_health_detail) or ComponentStatus("database_files", "unknown", "Probe failed"),
            _safe(_probe_accounts) or ComponentStatus("accounts", "unknown", "Probe failed"),
            _safe(_probe_sync) or ComponentStatus("sync", "unknown", "Probe failed"),
            _safe(_probe_scheduler) or ComponentStatus("scheduler", "unknown", "Probe failed"),
            _safe(_probe_job_runner) or ComponentStatus("job_runner", "unknown", "Probe failed"),
        ]

        detected, signals, recs = _detect_issues(components)

        # overall severity
        statuses = [c.status for c in components]
        if "unhealthy" in statuses:
            overall = "unhealthy"
        elif "degraded" in statuses:
            overall = "degraded"
        else:
            overall = "healthy"

        admin_ctx: Dict[str, Any] = {}
        if admin:
            admin_ctx = {
                "probe_duration_ms": round((time.time() - t0) * 1000, 1),
                "db_path": config.DB_PATH,
                "raw_components": [
                    {"name": c.name, "status": c.status, "metadata": c.metadata}
                    for c in components
                ],
            }

        logger.info(
            "Diagnostics complete: overall=%s detected=%s (%.0fms)",
            overall, detected, (time.time() - t0) * 1000,
        )

        return DiagnosticsReport(
            timestamp=time.time(),
            overall=overall,
            components=components,
            detected_issues=detected,
            signals=signals,
            recommendations=recs,
            admin_context=admin_ctx,
        )

    def quick_check(self) -> Dict[str, Any]:
        """Fast subset — DB + accounts only.  Used by the liveness bar."""
        db = _safe(_probe_database) or ComponentStatus("database", "unknown", "Probe failed")
        acct = _safe(_probe_accounts) or ComponentStatus("accounts", "unknown", "Probe failed")
        return {
            "database": {"status": db.status, "message": db.message},
            "accounts": {
                "status": acct.status,
                "message": acct.message,
                "total": acct.metadata.get("total", 0),
                "disconnected": acct.metadata.get("disconnected", 0),
            },
        }


_engine: Optional[DiagnosticsEngine] = None


def get_diagnostics_engine() -> DiagnosticsEngine:
    global _engine
    if _engine is None:
        _engine = DiagnosticsEngine()
    return _engine
