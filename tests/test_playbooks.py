"""Tests for backend/api/playbooks.py"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.playbooks as pb


def _run(coro):
    return asyncio.run(coro)


def _setup(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "playbooks.db")
    monkeypatch.setattr(pb, "_DB_PATH", db)
    monkeypatch.setattr(pb, "_subscribed", False)
    pb._init_db()
    return db


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(pb.router)
    app.dependency_overrides[pb.require_local_auth] = lambda: "test"
    return TestClient(app, raise_server_exceptions=True)


def _insert_playbook(db_path: str, *, trigger_type="manual", trigger_filter="",
                     steps=None, enabled=1) -> str:
    pb_id = str(uuid.uuid4())
    now = pb._now()
    con = sqlite3.connect(db_path)
    con.execute(
        f"INSERT INTO playbooks ({','.join(pb._PB_COLS)}) VALUES ({','.join(['?']*len(pb._PB_COLS))})",
        (pb_id, "Test PB", "desc", trigger_type, trigger_filter,
         json.dumps(steps or []), enabled, now, now, 0),
    )
    con.commit()
    con.close()
    return pb_id


# ── Template rendering ─────────────────────────────────────────────────────────

def test_render_substitutes_known_key():
    assert pb._render("hello {{name}}", {"name": "world"}) == "hello world"


def test_render_leaves_unknown_key():
    result = pb._render("val={{missing}}", {})
    assert result == "val={{missing}}"


def test_render_strips_whitespace_in_key():
    assert pb._render("{{  x  }}", {"x": "42"}) == "42"


def test_render_non_string_template():
    assert pb._render(123, {"x": "y"}) == "123"


def test_render_dict_applies_to_values():
    result = pb._render_dict({"a": "hello {{x}}", "b": "{{y}}"}, {"x": "A", "y": "B"})
    assert result == {"a": "hello A", "b": "B"}


# ── _execute_step ──────────────────────────────────────────────────────────────

def test_execute_step_emit_event():
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        result = _run(pb._execute_step(
            {"type": "emit_event", "event_type": "test.ping", "payload": {"k": "v"}},
            {},
        ))
    assert result["status"] == "ok"
    assert "test.ping" in result["output"]
    bus.publish.assert_awaited_once()


def test_execute_step_emit_event_renders_event_type():
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        result = _run(pb._execute_step(
            {"type": "emit_event", "event_type": "{{prefix}}.ping"},
            {"prefix": "custom"},
        ))
    assert "custom.ping" in result["output"]


def test_execute_step_trigger_workflow():
    mock_trigger = AsyncMock()
    with patch("backend.api.workflows.trigger_workflow_by_template", mock_trigger):
        result = _run(pb._execute_step(
            {"type": "trigger_workflow", "template": "my_template"},
            {"_trigger_type": "manual"},
        ))
    assert result["status"] == "ok"
    assert "my_template" in result["output"]
    mock_trigger.assert_awaited_once()


def test_execute_step_trigger_workflow_missing_template():
    result = _run(pb._execute_step({"type": "trigger_workflow"}, {}))
    assert result["status"] == "error"
    assert "template" in result["error"]


def test_execute_step_webhook_post_success():
    with patch("backend.api.playbooks._http_post", AsyncMock(return_value=True)):
        result = _run(pb._execute_step(
            {"type": "webhook_post", "url": "http://example.com/hook", "payload": {}},
            {},
        ))
    assert result["status"] == "ok"
    assert "example.com" in result["output"]


def test_execute_step_webhook_post_missing_url():
    result = _run(pb._execute_step({"type": "webhook_post"}, {}))
    assert result["status"] == "error"


def test_execute_step_webhook_post_http_error():
    with patch("backend.api.playbooks._http_post", AsyncMock(return_value=False)):
        result = _run(pb._execute_step(
            {"type": "webhook_post", "url": "http://x.com/hook"},
            {},
        ))
    assert result["status"] == "error"


def test_execute_step_incident_comment_with_id(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import backend.api.incidents as inc_mod
    db_inc = str(tmp_path / "incidents.db")
    monkeypatch.setattr(inc_mod, "_DB_PATH", db_inc)
    inc_mod._init_db()
    mock_add = MagicMock()
    monkeypatch.setattr(inc_mod, "_add_timeline", mock_add)
    result = _run(pb._execute_step(
        {"type": "incident_comment", "incident_id": "inc-1", "note": "hello"},
        {"incident_id": "inc-1"},
    ))
    assert result["status"] == "ok"
    mock_add.assert_called_once()


def test_execute_step_incident_comment_no_id_skips():
    result = _run(pb._execute_step({"type": "incident_comment", "note": "x"}, {}))
    assert result["status"] == "skipped"


def test_execute_step_notify():
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        result = _run(pb._execute_step(
            {"type": "notify", "message": "all good"},
            {},
        ))
    assert result["status"] == "ok"
    assert "all good" in result["output"]
    bus.publish.assert_awaited_once()


def test_execute_step_wait_clamps_to_300(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    _run(pb._execute_step({"type": "wait", "seconds": 9999}, {}))
    assert slept[0] == 300


def test_execute_step_wait_zero():
    result = _run(pb._execute_step({"type": "wait", "seconds": 0}, {}))
    assert result["status"] == "ok"
    assert "0s" in result["output"]


def test_execute_step_unknown_type():
    result = _run(pb._execute_step({"type": "teleport"}, {}))
    assert result["status"] == "error"
    assert "teleport" in result["error"]


# ── _run_playbook ──────────────────────────────────────────────────────────────

def test_run_playbook_completed(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    bus = MagicMock()
    bus.publish = AsyncMock()
    steps = [{"type": "emit_event", "event_type": "test.done"}]
    pb_id = _insert_playbook(db, steps=steps)
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        run_id = _run(pb._run_playbook(pb_id, {"_trigger_type": "manual"}))
    con = sqlite3.connect(db)
    row = con.execute("SELECT status, steps_done FROM playbook_runs WHERE id=?", (run_id,)).fetchone()
    con.close()
    assert row[0] == "completed"
    assert row[1] == 1


def test_run_playbook_increments_run_count(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    pb_id = _insert_playbook(db, steps=[])
    _run(pb._run_playbook(pb_id, {"_trigger_type": "manual"}))
    _run(pb._run_playbook(pb_id, {"_trigger_type": "manual"}))
    con = sqlite3.connect(db)
    count = con.execute("SELECT run_count FROM playbooks WHERE id=?", (pb_id,)).fetchone()[0]
    con.close()
    assert count == 2


def test_run_playbook_halt_on_error(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    steps = [
        {"type": "unknown_fail", "halt_on_error": True},
        {"type": "emit_event", "event_type": "should.not.run"},
    ]
    pb_id = _insert_playbook(db, steps=steps)
    run_id = _run(pb._run_playbook(pb_id, {"_trigger_type": "manual"}))
    con = sqlite3.connect(db)
    row = con.execute("SELECT status, steps_done FROM playbook_runs WHERE id=?", (run_id,)).fetchone()
    con.close()
    assert row[0] == "failed"
    assert row[1] == 1


def test_run_playbook_no_halt_continues(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    steps = [
        {"type": "unknown_type_a"},
        {"type": "unknown_type_b"},
    ]
    pb_id = _insert_playbook(db, steps=steps)
    run_id = _run(pb._run_playbook(pb_id, {"_trigger_type": "event"}))
    con = sqlite3.connect(db)
    row = con.execute("SELECT status, steps_done FROM playbook_runs WHERE id=?", (run_id,)).fetchone()
    con.close()
    assert row[0] == "completed"
    assert row[1] == 2


def test_run_playbook_nonexistent_returns_run_id(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    run_id = _run(pb._run_playbook("does-not-exist", {"_trigger_type": "manual"}))
    assert isinstance(run_id, str)


def test_run_playbook_step_log_stored(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    steps = [{"type": "wait", "seconds": 0}]
    pb_id = _insert_playbook(db, steps=steps)
    run_id = _run(pb._run_playbook(pb_id, {"_trigger_type": "manual"}))
    con = sqlite3.connect(db)
    log_raw = con.execute("SELECT step_log FROM playbook_runs WHERE id=?", (run_id,)).fetchone()[0]
    con.close()
    log = json.loads(log_raw)
    assert len(log) == 1
    assert log[0]["type"] == "wait"


# ── Event handlers ────────────────────────────────────────────────────────────

def test_make_event_handler_creates_task(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    pb_id = _insert_playbook(db)
    created_tasks = []

    def fake_create_task(coro):
        created_tasks.append(coro)
        coro.close()

    with patch("backend.api.playbooks.asyncio.create_task", side_effect=fake_create_task):
        handler = pb._make_event_handler(pb_id)
        _run(handler({"type": "test.event", "severity": "low", "id": "e1", "payload": {}}))
    assert len(created_tasks) == 1


def test_make_incident_handler_filters_by_severity(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    pb_id = _insert_playbook(db)
    created_tasks = []

    def fake_create_task(coro):
        created_tasks.append(coro)
        coro.close()

    with patch("backend.api.playbooks.asyncio.create_task", side_effect=fake_create_task):
        handler = pb._make_incident_handler(pb_id, "high")

        # low severity — should not fire
        _run(handler({"severity": "low", "payload": {}}))
        assert len(created_tasks) == 0

        # high severity — should fire
        _run(handler({"severity": "high", "payload": {}}))
        assert len(created_tasks) == 1


def test_make_incident_handler_equal_severity_fires(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    pb_id = _insert_playbook(db)
    created_tasks = []

    def fake_create_task(coro):
        created_tasks.append(coro)
        coro.close()

    with patch("backend.api.playbooks.asyncio.create_task", side_effect=fake_create_task):
        handler = pb._make_incident_handler(pb_id, "medium")
        _run(handler({"severity": "medium", "payload": {}}))
    assert len(created_tasks) == 1


# ── ensure_playbooks_running ───────────────────────────────────────────────────

def test_ensure_playbooks_running_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    bus = MagicMock()
    bus.subscribe = MagicMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        pb.ensure_playbooks_running()
        pb.ensure_playbooks_running()
    assert pb._subscribed is True


def test_ensure_playbooks_running_subscribes_event_type(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_playbook(db, trigger_type="event", trigger_filter="test.alert", enabled=1)
    bus = MagicMock()
    bus.subscribe = MagicMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        pb.ensure_playbooks_running()
    bus.subscribe.assert_called_once()
    call_args = bus.subscribe.call_args[0]
    assert call_args[0] == "test.alert"


def test_ensure_playbooks_running_subscribes_incident_type(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_playbook(db, trigger_type="incident", trigger_filter="critical", enabled=1)
    bus = MagicMock()
    bus.subscribe = MagicMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        pb.ensure_playbooks_running()
    bus.subscribe.assert_called_once()
    call_args = bus.subscribe.call_args[0]
    assert call_args[0] == "incident.created"


def test_ensure_playbooks_running_skips_manual(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_playbook(db, trigger_type="manual", enabled=1)
    bus = MagicMock()
    bus.subscribe = MagicMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        pb.ensure_playbooks_running()
    bus.subscribe.assert_not_called()


def test_ensure_playbooks_running_skips_disabled(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_playbook(db, trigger_type="event", trigger_filter="*", enabled=0)
    bus = MagicMock()
    bus.subscribe = MagicMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        pb.ensure_playbooks_running()
    bus.subscribe.assert_not_called()


# ── REST: list ────────────────────────────────────────────────────────────────

def test_ensure_playbooks_running_honors_runtime_service_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_PLAYBOOKS", "false")
    db = _setup(tmp_path, monkeypatch)
    _insert_playbook(db, trigger_type="event", trigger_filter="*", enabled=1)
    bus = MagicMock()
    bus.subscribe = MagicMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        pb.ensure_playbooks_running()
    bus.subscribe.assert_not_called()
    assert pb._subscribed is False


def test_list_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/playbooks")
    assert r.status_code == 200
    assert r.json()["playbooks"] == []


def test_list_returns_playbook(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/playbooks", json={"name": "My PB"})
    r = c.get("/playbooks")
    items = r.json()["playbooks"]
    assert len(items) == 1
    assert items[0]["name"] == "My PB"
    assert isinstance(items[0]["steps"], list)


# ── REST: create ──────────────────────────────────────────────────────────────

def test_create_returns_201(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/playbooks", json={"name": "PB1", "trigger_type": "manual"})
    assert r.status_code == 201
    data = r.json()
    assert "id" in data
    assert data["name"] == "PB1"


def test_create_invalid_trigger_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/playbooks", json={"name": "bad", "trigger_type": "cron"})
    assert r.status_code == 400


def test_create_event_type_subscribes(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(pb.router)
    app.dependency_overrides[pb.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    bus = MagicMock()
    bus.subscribe = MagicMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        r = c.post("/playbooks", json={
            "name": "evt-pb", "trigger_type": "event", "trigger_filter": "my.event"
        })
    assert r.status_code == 201
    bus.subscribe.assert_called_once()


# ── REST: get ─────────────────────────────────────────────────────────────────

def test_get_playbook(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    create_r = c.post("/playbooks", json={"name": "Get Me"})
    pb_id = create_r.json()["id"]
    r = c.get(f"/playbooks/{pb_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Get Me"


def test_get_playbook_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/playbooks/nonexistent-id")
    assert r.status_code == 404


# ── REST: patch ───────────────────────────────────────────────────────────────

def test_patch_playbook_name(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pb_id = c.post("/playbooks", json={"name": "Old"}).json()["id"]
    r = c.patch(f"/playbooks/{pb_id}", json={"name": "New"})
    assert r.status_code == 200
    assert c.get(f"/playbooks/{pb_id}").json()["name"] == "New"


def test_patch_playbook_no_fields_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pb_id = c.post("/playbooks", json={"name": "X"}).json()["id"]
    r = c.patch(f"/playbooks/{pb_id}", json={})
    assert r.status_code == 400


def test_patch_playbook_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.patch("/playbooks/missing", json={"name": "Y"})
    assert r.status_code == 404


def test_patch_invalid_trigger_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pb_id = c.post("/playbooks", json={"name": "X"}).json()["id"]
    r = c.patch(f"/playbooks/{pb_id}", json={"trigger_type": "cron"})
    assert r.status_code == 400


# ── REST: delete ──────────────────────────────────────────────────────────────

def test_delete_playbook(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pb_id = c.post("/playbooks", json={"name": "Del Me"}).json()["id"]
    r = c.delete(f"/playbooks/{pb_id}")
    assert r.status_code == 204
    assert c.get(f"/playbooks/{pb_id}").status_code == 404


def test_delete_also_removes_runs(tmp_path, monkeypatch):
    db = str(tmp_path / "playbooks.db")
    monkeypatch.setattr(pb, "_DB_PATH", db)
    monkeypatch.setattr(pb, "_subscribed", False)
    pb._init_db()
    app = FastAPI()
    app.include_router(pb.router)
    app.dependency_overrides[pb.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    pb_id = c.post("/playbooks", json={"name": "X"}).json()["id"]
    # manually insert a run
    con = sqlite3.connect(db)
    now = pb._now()
    run_id = str(uuid.uuid4())
    con.execute(
        f"INSERT INTO playbook_runs ({','.join(pb._RUN_COLS)}) VALUES ({','.join(['?']*len(pb._RUN_COLS))})",
        (run_id, pb_id, "X", "manual", "{}", now, now, "completed", 0, 0, "[]"),
    )
    con.commit()
    con.close()
    c.delete(f"/playbooks/{pb_id}")
    con2 = sqlite3.connect(db)
    count = con2.execute("SELECT COUNT(*) FROM playbook_runs WHERE playbook_id=?", (pb_id,)).fetchone()[0]
    con2.close()
    assert count == 0


# ── REST: manual trigger ──────────────────────────────────────────────────────

def test_trigger_playbook_manual(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pb_id = c.post("/playbooks", json={"name": "Run Me", "steps": []}).json()["id"]
    r = c.post(f"/playbooks/{pb_id}/run")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "run_id" in data


def test_trigger_playbook_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/playbooks/ghost/run")
    assert r.status_code == 404


# ── REST: list runs ───────────────────────────────────────────────────────────

def test_list_runs_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/playbooks/runs")
    assert r.status_code == 200
    assert r.json()["runs"] == []
    assert r.json()["total"] == 0


def test_list_runs_after_trigger(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pb_id = c.post("/playbooks", json={"name": "PB", "steps": []}).json()["id"]
    c.post(f"/playbooks/{pb_id}/run")
    r = c.get("/playbooks/runs")
    data = r.json()
    assert data["total"] == 1
    run = data["runs"][0]
    # step_log and trigger_context stripped from list view
    assert "step_log" not in run
    assert "trigger_context" not in run


def test_list_runs_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pb_id = c.post("/playbooks", json={"name": "PB", "steps": []}).json()["id"]
    for _ in range(5):
        c.post(f"/playbooks/{pb_id}/run")
    r1 = c.get("/playbooks/runs?limit=3&offset=0")
    r2 = c.get("/playbooks/runs?limit=3&offset=3")
    assert len(r1.json()["runs"]) == 3
    assert len(r2.json()["runs"]) == 2
    assert r1.json()["total"] == 5


# ── REST: run detail ──────────────────────────────────────────────────────────

def test_get_run_detail(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pb_id = c.post("/playbooks", json={
        "name": "DetailPB", "steps": [{"type": "wait", "seconds": 0}]
    }).json()["id"]
    run_id = c.post(f"/playbooks/{pb_id}/run").json()["run_id"]
    r = c.get(f"/playbooks/runs/{run_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == run_id
    assert data["status"] == "completed"
    assert isinstance(data["step_log"], list)
    assert isinstance(data["trigger_context"], dict)


def test_get_run_detail_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/playbooks/runs/no-such-run")
    assert r.status_code == 404
