"""Database maintenance helpers for Phase-1 production stability.

Provides:
  - Retention policy: prune old completed/dead-letter job queue entries and stale sync logs
  - WAL checkpoint: reclaim disk space consumed by the SQLite write-ahead log
  - Storage report: current DB + data directory sizes

All operations are designed to run inside the daemon-thread Scheduler so they
do not block the async event loop.  Each function is safe to call repeatedly
and tolerates a missing or locked database gracefully.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict

logger = logging.getLogger("db_maintenance")

# ── tuneable constants ────────────────────────────────────────────────────────

# Completed/dead-letter job queue rows older than this are deleted
JOB_RETENTION_DAYS = int(os.environ.get("JOB_RETENTION_DAYS", "7"))

# Completed sync_status rows older than this are deleted
SYNC_STATUS_RETENTION_DAYS = int(os.environ.get("SYNC_STATUS_RETENTION_DAYS", "30"))

# OAuth states that have expired are purged
OAUTH_STATE_RETENTION_DAYS = int(os.environ.get("OAUTH_STATE_RETENTION_DAYS", "1"))

# provider_diagnostics rows older than this are deleted (keeps last N days only)
DIAGNOSTICS_RETENTION_DAYS = int(os.environ.get("DIAGNOSTICS_RETENTION_DAYS", "14"))


# ── WAL checkpoint ────────────────────────────────────────────────────────────

def run_wal_checkpoint(db_paths: list[str | Path]) -> Dict[str, int]:
    """
    Run a PASSIVE WAL checkpoint on all provided database files.

    A PASSIVE checkpoint transfers WAL pages to the main database file without
    blocking readers or writers.  Calling it periodically prevents the WAL from
    growing without bound after many write transactions.

    Returns a dict of {path: pages_checkpointed}.
    """
    results = {}
    for path in db_paths:
        path = str(path)
        if not os.path.exists(path):
            continue
        try:
            conn = sqlite3.connect(path, timeout=10)
            row = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
            conn.close()
            # row = (busy, log, checkpointed)
            checkpointed = int(row[2]) if row else 0
            results[path] = checkpointed
            if checkpointed:
                logger.info("WAL checkpoint: %s — %d pages written", path, checkpointed)
        except Exception as exc:
            logger.warning("WAL checkpoint failed for %s: %s", path, exc)
            results[path] = -1
    return results


# ── job queue retention ───────────────────────────────────────────────────────

def prune_job_queue(db_path: str | Path, retention_days: int = JOB_RETENTION_DAYS) -> int:
    """Delete completed and terminal job records older than `retention_days`."""
    cutoff = time.time() - retention_days * 86400
    path = str(db_path)
    if not os.path.exists(path):
        return 0
    try:
        conn = sqlite3.connect(path, timeout=15, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        cur = conn.execute(
            "DELETE FROM persistent_jobs WHERE status IN ('completed', 'dead_letter', 'failed') AND updated_at < ?",
            (cutoff,),
        )
        deleted = cur.rowcount
        conn.close()
        if deleted:
            logger.info("Job queue pruned: removed %d old records (>%d days)", deleted, retention_days)
        return deleted
    except Exception as exc:
        logger.warning("Job queue pruning failed: %s", exc)
        return 0


# ── application DB retention ──────────────────────────────────────────────────

def prune_app_db(db_path: str | Path) -> Dict[str, int]:
    """
    Remove stale rows from the main application database:
      - sync_status rows older than SYNC_STATUS_RETENTION_DAYS
      - expired oauth_states rows
      - provider_diagnostics rows older than DIAGNOSTICS_RETENTION_DAYS

    Does NOT touch emails, accounts, or user data — only operational/audit tables.
    """
    path = str(db_path)
    if not os.path.exists(path):
        return {}
    results = {}
    cutoffs = {
        "sync_status":         time.time() - SYNC_STATUS_RETENTION_DAYS * 86400,
        "oauth_states":        time.time() - OAUTH_STATE_RETENTION_DAYS  * 86400,
        "provider_diagnostics": time.time() - DIAGNOSTICS_RETENTION_DAYS * 86400,
    }
    queries = {
        "sync_status":          ("DELETE FROM sync_status WHERE started_at < datetime(?, 'unixepoch') AND status IN ('completed', 'failed')", cutoffs["sync_status"]),
        "oauth_states":         ("DELETE FROM oauth_states WHERE expires_at < datetime(?, 'unixepoch')", cutoffs["oauth_states"]),
        "provider_diagnostics": ("DELETE FROM provider_diagnostics WHERE checked_at < datetime(?, 'unixepoch')", cutoffs["provider_diagnostics"]),
    }
    try:
        conn = sqlite3.connect(path, timeout=15, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        for table, (sql, cutoff) in queries.items():
            try:
                cur = conn.execute(sql, (cutoff,))
                results[table] = cur.rowcount
                if cur.rowcount:
                    logger.info("Pruned %s: removed %d rows", table, cur.rowcount)
            except Exception as exc:
                logger.debug("Prune skipped for %s: %s", table, exc)
                results[table] = 0
        conn.close()
    except Exception as exc:
        logger.warning("App DB pruning failed: %s", exc)
    return results


# ── storage report ────────────────────────────────────────────────────────────

def storage_report(paths: list[str | Path]) -> Dict[str, float]:
    """Return size in MB for each provided file or directory path."""
    report = {}
    for path in paths:
        path = Path(path)
        try:
            if path.is_file():
                report[str(path)] = round(path.stat().st_size / 1_048_576, 2)
            elif path.is_dir():
                total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                report[str(path)] = round(total / 1_048_576, 2)
        except Exception:
            report[str(path)] = -1.0
    return report


__all__ = [
    "run_wal_checkpoint",
    "prune_job_queue",
    "prune_app_db",
    "storage_report",
    "JOB_RETENTION_DAYS",
    "SYNC_STATUS_RETENTION_DAYS",
]
