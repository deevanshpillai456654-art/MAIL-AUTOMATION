"""SQLite database layer for AI Automation Platform."""
from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_thread_local = threading.local()
_db_path: str | None = None
_init_lock = threading.Lock()


def _get_default_db_path() -> str:
    env = os.environ.get("AI_AUTOMATION_DB_PATH")
    if env:
        return env
    root = Path(__file__).resolve().parents[3]
    return str(root / "platform" / "ai_automation.db")


def get_db():
    """Return a thread-local SQLite connection, creating it if needed."""
    import sqlite3
    if not hasattr(_thread_local, "conn") or _thread_local.conn is None:
        path = _db_path or _get_default_db_path()
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA cache_size=-32000")
        _thread_local.conn = conn
    return _thread_local.conn


@contextmanager
def tx():
    """Context manager for database transactions."""
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_ai_automation_db(db_path: str | None = None) -> None:
    global _db_path
    with _init_lock:
        if db_path:
            _db_path = db_path
        _create_schema()
    log.info("AI Automation DB ready at %s", _db_path or _get_default_db_path())


def _create_schema() -> None:
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            tenant_id TEXT NOT NULL,
            version INTEGER DEFAULT 1,
            status TEXT DEFAULT 'draft',
            nodes_json TEXT DEFAULT '[]',
            connections_json TEXT DEFAULT '[]',
            variables_json TEXT DEFAULT '{}',
            tags_json TEXT DEFAULT '[]',
            created_at TEXT,
            updated_at TEXT,
            created_by TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_workflows_tenant ON workflows(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status);

        CREATE TABLE IF NOT EXISTS executions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            workflow_name TEXT,
            tenant_id TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            trigger_data_json TEXT DEFAULT '{}',
            context_json TEXT DEFAULT '{}',
            current_node_id TEXT,
            error TEXT,
            started_at TEXT,
            completed_at TEXT,
            duration_ms INTEGER,
            triggered_by TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_executions_workflow ON executions(workflow_id);
        CREATE INDEX IF NOT EXISTS idx_executions_tenant ON executions(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);

        CREATE TABLE IF NOT EXISTS execution_steps (
            id TEXT PRIMARY KEY,
            execution_id TEXT NOT NULL,
            node_id TEXT NOT NULL,
            node_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            input_data_json TEXT DEFAULT '{}',
            output_data_json TEXT DEFAULT '{}',
            error TEXT,
            started_at TEXT,
            completed_at TEXT,
            duration_ms INTEGER,
            retry_count INTEGER DEFAULT 0,
            FOREIGN KEY(execution_id) REFERENCES executions(id)
        );

        CREATE INDEX IF NOT EXISTS idx_steps_execution ON execution_steps(execution_id);

        CREATE TABLE IF NOT EXISTS approval_requests (
            id TEXT PRIMARY KEY,
            execution_id TEXT,
            workflow_id TEXT,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            risk_level TEXT DEFAULT 'low',
            data_json TEXT DEFAULT '{}',
            assignee TEXT,
            assignee_group TEXT,
            status TEXT DEFAULT 'pending',
            decision TEXT,
            decision_notes TEXT,
            decided_by TEXT,
            expires_at TEXT,
            escalate_after_minutes INTEGER,
            created_at TEXT,
            decided_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_approvals_tenant ON approval_requests(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_approvals_status ON approval_requests(status);

        CREATE TABLE IF NOT EXISTS ai_requests_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT,
            provider TEXT,
            model TEXT,
            tokens_used INTEGER DEFAULT 0,
            cost_estimate REAL DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ocr_results (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            document_type TEXT,
            raw_text TEXT,
            fields_json TEXT DEFAULT '[]',
            confidence REAL DEFAULT 0,
            needs_review INTEGER DEFAULT 0,
            review_reason TEXT,
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ai_provider_configs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            api_key_enc TEXT,
            base_url TEXT,
            default_model TEXT,
            enabled INTEGER DEFAULT 1,
            rate_limit_rpm INTEGER DEFAULT 60,
            metadata_json TEXT DEFAULT '{}',
            UNIQUE(tenant_id, provider)
        );
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_dict(row) -> Dict[str, Any]:
    if row is None:
        return {}
    return dict(row)


def json_field(row, key: str) -> Any:
    val = row[key] if key in row.keys() else None
    if val is None:
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return val
