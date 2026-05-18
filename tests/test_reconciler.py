"""Tests for the operational reconciler (backend/api/reconciler.py)."""
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_reconciler():
    from backend.api.reconciler import OperationalReconciler
    r = OperationalReconciler()
    return r


def _seed_workflows_db(path: str, stuck_count: int = 0, succeeded: int = 3, failed: int = 0):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT,
            status TEXT,
            started_at TEXT,
            finished_at TEXT,
            error TEXT,
            created_at TEXT
        );
    """)
    now = datetime.now(timezone.utc)
    for i in range(stuck_count):
        stuck_time = (now - timedelta(minutes=15)).isoformat()
        con.execute(
            "INSERT INTO workflow_executions (id, workflow_id, status, started_at, created_at) VALUES (?,?,?,?,?)",
            (f"stuck-{i}", f"wf-{i}", "running", stuck_time, stuck_time),
        )
    for i in range(succeeded):
        t = (now - timedelta(minutes=i)).isoformat()
        con.execute(
            "INSERT INTO workflow_executions (id, workflow_id, status, started_at, created_at) VALUES (?,?,?,?,?)",
            (f"ok-{i}", "wf-ok", "succeeded", t, t),
        )
    for i in range(failed):
        t = (now - timedelta(minutes=i + 10)).isoformat()
        con.execute(
            "INSERT INTO workflow_executions (id, workflow_id, status, started_at, created_at) VALUES (?,?,?,?,?)",
            (f"fail-{i}", "wf-fail", "failed", t, t),
        )
    con.commit()
    con.close()


def _seed_main_db(path: str, stale_accounts: int = 0, active_threats: int = 0):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY, status TEXT, last_sync_at TEXT
        );
        CREATE TABLE IF NOT EXISTS threat_lookalike_alerts (
            id INTEGER PRIMARY KEY, status TEXT, created_at TEXT
        );
    """)
    now = datetime.now(timezone.utc)
    for i in range(stale_accounts):
        old = (now - timedelta(hours=3)).isoformat()
        con.execute("INSERT INTO accounts (status, last_sync_at) VALUES ('active', ?)", (old,))
    for i in range(active_threats):
        con.execute(
            "INSERT INTO threat_lookalike_alerts (status, created_at) VALUES ('active', ?)",
            (now.isoformat(),),
        )
    con.commit()
    con.close()


# ── unit tests ────────────────────────────────────────────────────────────────

def test_reconciler_initial_status(monkeypatch):
    r = _make_reconciler()
    status = r.status()
    assert status["running"] is False
    assert status["run_count"] == 0
    assert status["last_run"] is None


def test_run_cycle_increments_run_count(tmp_path, monkeypatch):
    from backend.api import reconciler as rec
    wf_db = str(tmp_path / "workflows.db")
    main_db = str(tmp_path / "main.db")
    _seed_workflows_db(wf_db)
    _seed_main_db(main_db)

    monkeypatch.setattr(rec, "_WORKFLOWS_DB", wf_db)
    monkeypatch.setattr(rec, "DB_PATH", main_db)

    # Patch event bus emit to be a no-op
    async def _noop(*a, **kw):
        return "fake-id"
    monkeypatch.setattr("backend.api.event_bus.emit", _noop)

    r = _make_reconciler()
    summary = _run(r.run_cycle())
    assert r._run_count == 1
    assert summary["cycle"] == 1
    assert "ran_at" in summary


def test_run_cycle_detects_and_recovers_stuck_executions(tmp_path, monkeypatch):
    from backend.api import reconciler as rec
    wf_db = str(tmp_path / "workflows.db")
    main_db = str(tmp_path / "main.db")
    _seed_workflows_db(wf_db, stuck_count=2)
    _seed_main_db(main_db)

    monkeypatch.setattr(rec, "_WORKFLOWS_DB", wf_db)
    monkeypatch.setattr(rec, "DB_PATH", main_db)

    async def _noop(*a, **kw):
        return "fake-id"
    monkeypatch.setattr("backend.api.event_bus.emit", _noop)

    r = _make_reconciler()
    summary = _run(r.run_cycle())

    assert summary["actions_taken"] >= 2
    assert any("stuck" in a.lower() for a in summary["actions"])

    # Verify DB was updated
    con = sqlite3.connect(wf_db)
    still_running = con.execute(
        "SELECT COUNT(*) FROM workflow_executions WHERE status='running'"
    ).fetchone()[0]
    con.close()
    assert still_running == 0


def test_run_cycle_detects_stale_accounts(tmp_path, monkeypatch):
    from backend.api import reconciler as rec
    wf_db = str(tmp_path / "workflows.db")
    main_db = str(tmp_path / "main.db")
    _seed_workflows_db(wf_db)
    _seed_main_db(main_db, stale_accounts=3)

    monkeypatch.setattr(rec, "_WORKFLOWS_DB", wf_db)
    monkeypatch.setattr(rec, "DB_PATH", main_db)

    async def _noop(*a, **kw):
        return "fake-id"
    monkeypatch.setattr("backend.api.event_bus.emit", _noop)

    r = _make_reconciler()
    summary = _run(r.run_cycle())

    assert any("stale" in a.lower() or "account" in a.lower() for a in summary["actions"])


def test_run_cycle_detects_threat_accumulation(tmp_path, monkeypatch):
    from backend.api import reconciler as rec
    wf_db = str(tmp_path / "workflows.db")
    main_db = str(tmp_path / "main.db")
    _seed_workflows_db(wf_db)
    _seed_main_db(main_db, active_threats=12)

    monkeypatch.setattr(rec, "_WORKFLOWS_DB", wf_db)
    monkeypatch.setattr(rec, "DB_PATH", main_db)

    async def _noop(*a, **kw):
        return "fake-id"
    monkeypatch.setattr("backend.api.event_bus.emit", _noop)

    r = _make_reconciler()
    summary = _run(r.run_cycle())

    assert any("threat" in a.lower() for a in summary["actions"])


def test_history_ring_buffer_caps_at_50(tmp_path, monkeypatch):
    from backend.api import reconciler as rec
    wf_db = str(tmp_path / "workflows.db")
    main_db = str(tmp_path / "main.db")
    _seed_workflows_db(wf_db)
    _seed_main_db(main_db)

    monkeypatch.setattr(rec, "_WORKFLOWS_DB", wf_db)
    monkeypatch.setattr(rec, "DB_PATH", main_db)

    async def _noop(*a, **kw):
        return "fake-id"
    monkeypatch.setattr("backend.api.event_bus.emit", _noop)

    r = _make_reconciler()
    for _ in range(55):
        _run(r.run_cycle())

    assert len(r._history) == 50


# ── REST endpoints ─────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    from backend.api import reconciler as rec
    from backend.auth.local_auth import require_local_auth

    wf_db = str(tmp_path / "workflows.db")
    main_db = str(tmp_path / "main.db")
    _seed_workflows_db(wf_db)
    _seed_main_db(main_db)

    monkeypatch.setattr(rec, "_WORKFLOWS_DB", wf_db)
    monkeypatch.setattr(rec, "DB_PATH", main_db)

    async def _noop(*a, **kw):
        return "fake-id"
    monkeypatch.setattr("backend.api.event_bus.emit", _noop)

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(rec.router, prefix="/api/v1")
    return TestClient(app)


def test_status_endpoint_returns_reconciler_state(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/reconciler/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "run_count" in data
    assert "cycle_interval_s" in data


def test_trigger_endpoint_dispatches_cycle(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/reconciler/trigger")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_history_endpoint_returns_past_cycles(tmp_path, monkeypatch):
    from backend.api import reconciler as rec
    client = _client(tmp_path, monkeypatch)

    # Run a cycle directly on the singleton
    _run(rec._reconciler.run_cycle())

    resp = client.get("/api/v1/reconciler/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "history" in data
    assert "count" in data
