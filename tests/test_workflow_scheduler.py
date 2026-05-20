"""Tests for workflow_scheduler (backend/api/workflow_scheduler.py)."""
import asyncio
import json
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _seed_workflows_db(path: str, workflows=None):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY,
            name TEXT,
            trigger_type TEXT DEFAULT 'schedule',
            trigger_cfg TEXT DEFAULT '{}',
            steps_json TEXT DEFAULT '[]',
            is_active INTEGER DEFAULT 1,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT,
            trigger_type TEXT,
            status TEXT,
            step_count INTEGER DEFAULT 0,
            steps_done INTEGER DEFAULT 0,
            input_data TEXT,
            output_data TEXT,
            created_at TEXT
        );
    """)
    now = datetime.now(timezone.utc).isoformat()
    if workflows:
        for wf in workflows:
            con.execute(
                """INSERT INTO workflows
                   (id, name, trigger_type, trigger_cfg, steps_json, is_active, created_at)
                   VALUES (?,?,'schedule',?,?,1,?)""",
                (
                    wf["id"], wf["name"],
                    json.dumps({"cron": wf["cron"]}),
                    json.dumps(wf.get("steps", [])),
                    now,
                ),
            )
    con.commit()
    con.close()


# ── cron_matches ──────────────────────────────────────────────────────────────

def test_cron_matches_wildcard():
    from backend.api.workflow_scheduler import cron_matches
    dt = datetime(2024, 6, 15, 14, 37, tzinfo=timezone.utc)
    assert cron_matches("* * * * *", dt) is True


def test_cron_matches_exact():
    from backend.api.workflow_scheduler import cron_matches
    match    = datetime(2024, 6, 15, 9, 30, tzinfo=timezone.utc)
    no_match = datetime(2024, 6, 15, 9, 31, tzinfo=timezone.utc)
    assert cron_matches("30 9 * * *", match) is True
    assert cron_matches("30 9 * * *", no_match) is False


def test_cron_matches_step():
    from backend.api.workflow_scheduler import cron_matches
    expr = "*/15 * * * *"
    for minute in (0, 15, 30, 45):
        dt = datetime(2024, 6, 15, 10, minute, tzinfo=timezone.utc)
        assert cron_matches(expr, dt) is True
    assert cron_matches(expr, datetime(2024, 6, 15, 10, 7, tzinfo=timezone.utc)) is False


def test_cron_matches_range():
    from backend.api.workflow_scheduler import cron_matches
    expr = "0 8-18 * * *"
    assert cron_matches(expr, datetime(2024, 6, 15, 8,  0, tzinfo=timezone.utc)) is True
    assert cron_matches(expr, datetime(2024, 6, 15, 18, 0, tzinfo=timezone.utc)) is True
    assert cron_matches(expr, datetime(2024, 6, 15, 7,  0, tzinfo=timezone.utc)) is False
    assert cron_matches(expr, datetime(2024, 6, 15, 19, 0, tzinfo=timezone.utc)) is False


def test_cron_matches_comma():
    from backend.api.workflow_scheduler import cron_matches
    expr = "0 9,17 * * *"
    assert cron_matches(expr, datetime(2024, 6, 15, 9,  0, tzinfo=timezone.utc)) is True
    assert cron_matches(expr, datetime(2024, 6, 15, 17, 0, tzinfo=timezone.utc)) is True
    assert cron_matches(expr, datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)) is False


def test_cron_invalid_field_count():
    from backend.api.workflow_scheduler import cron_matches
    dt = datetime(2024, 6, 15, 9, 0, tzinfo=timezone.utc)
    assert cron_matches("* * * *", dt) is False


# ── next_fire ─────────────────────────────────────────────────────────────────

def test_next_fire_wildcard():
    from backend.api.workflow_scheduler import next_fire
    now = datetime(2024, 6, 15, 10, 0, tzinfo=timezone.utc)
    nf  = next_fire("* * * * *", now)
    assert nf == datetime(2024, 6, 15, 10, 1, tzinfo=timezone.utc)


def test_next_fire_daily():
    from backend.api.workflow_scheduler import next_fire
    now = datetime(2024, 6, 15, 8, 59, tzinfo=timezone.utc)
    nf  = next_fire("0 9 * * *", now)
    assert nf is not None
    assert nf.hour == 9 and nf.minute == 0


# ── WorkflowScheduler unit tests ──────────────────────────────────────────────

def test_scheduler_initial_status():
    from backend.api.workflow_scheduler import WorkflowScheduler
    s  = WorkflowScheduler()
    st = s.status()
    assert st["running"] is False
    assert st["run_count"] == 0
    assert st["last_check"] is None


def test_tick_increments_run_count(tmp_path, monkeypatch):
    from backend.api import workflow_scheduler as ws

    wf_db = str(tmp_path / "workflows.db")
    _seed_workflows_db(wf_db)
    monkeypatch.setattr(ws, "_WORKFLOWS_DB", wf_db)

    s = ws.WorkflowScheduler()

    async def _scenario():
        await s._tick()
        await s._tick()

    _run(_scenario())
    assert s._run_count == 2


def test_tick_fires_matching_workflow(tmp_path, monkeypatch):
    from backend.api import workflow_scheduler as ws

    wf_db = str(tmp_path / "workflows.db")
    now   = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    cron  = f"{now.minute} {now.hour} * * *"
    _seed_workflows_db(wf_db, [{"id": "wf-sched-1", "name": "Hourly", "cron": cron}])
    monkeypatch.setattr(ws, "_WORKFLOWS_DB", wf_db)

    fired = []

    async def _fake_fire(wf, fired_at):
        fired.append(wf["id"])

    s = ws.WorkflowScheduler()
    monkeypatch.setattr(s, "_fire", _fake_fire)

    _run(s._tick())
    assert "wf-sched-1" in fired


def test_tick_no_double_fire(tmp_path, monkeypatch):
    from backend.api import workflow_scheduler as ws

    wf_db = str(tmp_path / "workflows.db")
    now   = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    cron  = f"{now.minute} {now.hour} * * *"
    _seed_workflows_db(wf_db, [{"id": "wf-nodbl", "name": "NoDbl", "cron": cron}])
    monkeypatch.setattr(ws, "_WORKFLOWS_DB", wf_db)

    fired = []

    async def _fake_fire(wf, fired_at):
        fired.append(wf["id"])

    s = ws.WorkflowScheduler()
    monkeypatch.setattr(s, "_fire", _fake_fire)

    async def _scenario():
        await s._tick()
        await s._tick()

    _run(_scenario())
    assert len(fired) == 1


def test_tick_non_matching_cron_not_fired(tmp_path, monkeypatch):
    from backend.api import workflow_scheduler as ws

    wf_db  = str(tmp_path / "workflows.db")
    future = (datetime.now(timezone.utc) + timedelta(minutes=30)).replace(second=0, microsecond=0)
    cron   = f"{future.minute} {future.hour} * * *"
    _seed_workflows_db(wf_db, [{"id": "wf-future", "name": "Future", "cron": cron}])
    monkeypatch.setattr(ws, "_WORKFLOWS_DB", wf_db)

    fired = []

    async def _fake_fire(wf, fired_at):
        fired.append(wf["id"])

    s = ws.WorkflowScheduler()
    monkeypatch.setattr(s, "_fire", _fake_fire)

    _run(s._tick())
    assert len(fired) == 0


def test_status_shows_upcoming(tmp_path, monkeypatch):
    from backend.api import workflow_scheduler as ws

    wf_db = str(tmp_path / "workflows.db")
    _seed_workflows_db(wf_db, [{"id": "wf-up", "name": "Daily 9am", "cron": "0 9 * * *"}])
    monkeypatch.setattr(ws, "_WORKFLOWS_DB", wf_db)

    s  = ws.WorkflowScheduler()
    st = s.status()
    assert "upcoming" in st
    assert isinstance(st["upcoming"], list)
    assert st["scheduled_workflows"] == 1
    assert st["upcoming"][0]["workflow_id"] == "wf-up"


def test_triggered_ring_buffer_capped_at_100(tmp_path, monkeypatch):
    from backend.api import workflow_scheduler as ws

    wf_db = str(tmp_path / "workflows.db")
    monkeypatch.setattr(ws, "_WORKFLOWS_DB", wf_db)

    s = ws.WorkflowScheduler()
    for i in range(110):
        s._triggered.append({"workflow_id": f"wf-{i}"})
        if len(s._triggered) > 100:
            s._triggered.pop(0)

    assert len(s._triggered) == 100


# ── REST endpoints ────────────────────────────────────────────────────────────

def test_ensure_scheduler_running_honors_runtime_service_toggle(monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_WORKFLOW_SCHEDULER", "false")
    from backend.api import workflow_scheduler as ws

    class FakeScheduler:
        def __init__(self):
            self.started = False

        async def start(self):
            self.started = True

    fake = FakeScheduler()
    monkeypatch.setattr(ws, "_scheduler", fake)

    _run(ws.ensure_scheduler_running())

    assert fake.started is False


def _client(tmp_path, monkeypatch, workflows=None):
    from backend.api import workflow_scheduler as ws
    from backend.auth.local_auth import require_local_auth

    wf_db = str(tmp_path / "workflows.db")
    _seed_workflows_db(wf_db, workflows or [{"id": "wf-ep", "name": "API Job", "cron": "0 6 * * *"}])
    monkeypatch.setattr(ws, "_WORKFLOWS_DB", wf_db)

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(ws.router, prefix="/api/v1")
    return TestClient(app)


def test_status_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/workflow-scheduler/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "scheduled_workflows" in data
    assert "upcoming" in data
    assert "run_count" in data


def test_trigger_endpoint(tmp_path, monkeypatch):
    from backend.api import workflow_scheduler as ws
    monkeypatch.setattr(ws, "_WORKFLOWS_DB", str(tmp_path / "empty.db"))
    _seed_workflows_db(str(tmp_path / "empty.db"))

    client = _client(tmp_path, monkeypatch, workflows=[])
    resp = client.post("/api/v1/workflow-scheduler/trigger")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
