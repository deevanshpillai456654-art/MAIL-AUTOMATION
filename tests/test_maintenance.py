"""Tests for backend/api/maintenance.py"""
from __future__ import annotations

import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.maintenance as maint


def _run(coro):
    return asyncio.run(coro)


def _setup(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "maintenance.db")
    monkeypatch.setattr(maint, "_DB_PATH", db)
    monkeypatch.setattr(maint, "_running", False)
    monkeypatch.setattr(maint, "_checker", None)
    maint._init_db()
    return db


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(maint.router)
    app.dependency_overrides[maint.require_local_auth] = lambda: "test"
    return TestClient(app, raise_server_exceptions=True)


def _ts(delta_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)).isoformat()


def _insert_window(db_path: str, *, status="scheduled",
                   starts_offset_min=60, ends_offset_min=180) -> str:
    win_id = str(uuid.uuid4())
    now = maint._now()
    starts = _ts(starts_offset_min)
    ends   = _ts(ends_offset_min)
    con = sqlite3.connect(db_path)
    con.execute(
        f"INSERT INTO maintenance_windows ({','.join(maint._WINDOW_COLS)}) "
        f"VALUES ({','.join(['?']*len(maint._WINDOW_COLS))})",
        (win_id, "Test Window", "desc", starts, ends, status,
         "test", now, now, 1, 1, 1),
    )
    con.commit()
    con.close()
    return win_id


# ── DB init ───────────────────────────────────────────────────────────────────

def test_init_creates_tables(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    con.close()
    assert "maintenance_windows" in tables
    assert "maintenance_log" in tables


# ── is_maintenance_active / get_active_window ─────────────────────────────────

def test_is_maintenance_active_false_when_no_windows(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert maint.is_maintenance_active() is False


def test_is_maintenance_active_true_when_active(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_window(db, status="active")
    assert maint.is_maintenance_active() is True


def test_get_active_window_returns_none_when_none(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert maint.get_active_window() is None


def test_get_active_window_returns_dict_when_active(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    win_id = _insert_window(db, status="active")
    w = maint.get_active_window()
    assert w is not None
    assert w["id"] == win_id
    assert w["status"] == "active"


# ── _transition ───────────────────────────────────────────────────────────────

def test_transition_scheduled_to_active(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    win_id = _insert_window(db, status="scheduled")
    result = maint._transition(win_id, "active")
    assert result is not None
    assert result["status"] == "active"


def test_transition_active_to_completed(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    win_id = _insert_window(db, status="active")
    result = maint._transition(win_id, "completed")
    assert result["status"] == "completed"


def test_transition_active_to_cancelled(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    win_id = _insert_window(db, status="active")
    result = maint._transition(win_id, "cancelled")
    assert result["status"] == "cancelled"


def test_transition_invalid_returns_none(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    win_id = _insert_window(db, status="completed")
    result = maint._transition(win_id, "active")
    assert result is None


def test_transition_nonexistent_returns_none(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    result = maint._transition("no-such-id", "active")
    assert result is None


# ── _add_log ──────────────────────────────────────────────────────────────────

def test_add_log_writes_entry(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    maint._add_log("win-1", "My Window", "created", "test note")
    con = sqlite3.connect(db)
    row = con.execute("SELECT event, note FROM maintenance_log WHERE window_id='win-1'").fetchone()
    con.close()
    assert row[0] == "created"
    assert row[1] == "test note"


# ── _check_windows ────────────────────────────────────────────────────────────

def test_check_windows_activates_due_window(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    # starts 5 minutes ago — should auto-activate
    win_id = _insert_window(db, status="scheduled",
                             starts_offset_min=-5, ends_offset_min=120)
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(maint._check_windows())
    con = sqlite3.connect(db)
    status = con.execute("SELECT status FROM maintenance_windows WHERE id=?", (win_id,)).fetchone()[0]
    con.close()
    assert status == "active"
    bus.publish.assert_awaited_once()
    event = bus.publish.call_args[0][0]
    assert event["type"] == "maintenance.started"


def test_check_windows_completes_expired_window(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    # started 2h ago, ended 30min ago — should auto-complete
    win_id = _insert_window(db, status="active",
                             starts_offset_min=-120, ends_offset_min=-30)
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(maint._check_windows())
    con = sqlite3.connect(db)
    status = con.execute("SELECT status FROM maintenance_windows WHERE id=?", (win_id,)).fetchone()[0]
    con.close()
    assert status == "completed"
    bus.publish.assert_awaited_once()
    event = bus.publish.call_args[0][0]
    assert event["type"] == "maintenance.ended"


def test_check_windows_ignores_future_window(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    # starts in 2h — should NOT activate
    win_id = _insert_window(db, status="scheduled",
                             starts_offset_min=120, ends_offset_min=240)
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(maint._check_windows())
    con = sqlite3.connect(db)
    status = con.execute("SELECT status FROM maintenance_windows WHERE id=?", (win_id,)).fetchone()[0]
    con.close()
    assert status == "scheduled"
    bus.publish.assert_not_awaited()


# ── REST: list ────────────────────────────────────────────────────────────────

def test_list_windows_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/maintenance")
    assert r.status_code == 200
    assert r.json()["windows"] == []
    assert r.json()["total"] == 0


def test_list_windows_returns_item(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/maintenance", json={
        "name": "W1", "starts_at": _ts(60), "ends_at": _ts(180)
    })
    r = c.get("/maintenance")
    assert r.json()["total"] == 1
    assert r.json()["windows"][0]["name"] == "W1"


def test_list_windows_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/maintenance", json={"name": "W1", "starts_at": _ts(60), "ends_at": _ts(180)})
    r = c.get("/maintenance?status=scheduled")
    assert r.json()["total"] == 1
    r2 = c.get("/maintenance?status=active")
    assert r2.json()["total"] == 0


# ── REST: create ──────────────────────────────────────────────────────────────

def test_create_window_201(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/maintenance", json={
        "name": "Deploy", "starts_at": _ts(30), "ends_at": _ts(90)
    })
    assert r.status_code == 201
    assert "id" in r.json()


def test_create_window_invalid_timestamps(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/maintenance", json={
        "name": "Bad", "starts_at": "not-a-date", "ends_at": "also-bad"
    })
    assert r.status_code == 400


def test_create_window_end_before_start(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/maintenance", json={
        "name": "Bad", "starts_at": _ts(120), "ends_at": _ts(30)
    })
    assert r.status_code == 400


def test_create_window_writes_log(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(maint.router)
    app.dependency_overrides[maint.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    win_id = c.post("/maintenance", json={
        "name": "W", "starts_at": _ts(30), "ends_at": _ts(90)
    }).json()["id"]
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM maintenance_log WHERE window_id=?", (win_id,)).fetchone()[0]
    con.close()
    assert count == 1


# ── REST: status ──────────────────────────────────────────────────────────────

def test_maintenance_status_inactive(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/maintenance/status")
    assert r.status_code == 200
    data = r.json()
    assert data["is_active"] is False
    assert data["active_window"] is None


def test_maintenance_status_active(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(maint.router)
    app.dependency_overrides[maint.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    c.post("/maintenance", json={"name": "Now", "starts_at": _ts(-10), "ends_at": _ts(60)})
    # manually set it active
    win_id = c.get("/maintenance").json()["windows"][0]["id"]
    c.post(f"/maintenance/{win_id}/activate")
    r = c.get("/maintenance/status")
    assert r.json()["is_active"] is True
    assert r.json()["counts"]["active"] == 1


# ── REST: get ─────────────────────────────────────────────────────────────────

def test_get_window_with_log(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "W", "starts_at": _ts(30), "ends_at": _ts(90)
    }).json()["id"]
    r = c.get(f"/maintenance/{win_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "W"
    assert isinstance(data["log"], list)
    assert len(data["log"]) >= 1


def test_get_window_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/maintenance/no-such-id")
    assert r.status_code == 404


# ── REST: patch ───────────────────────────────────────────────────────────────

def test_patch_window_name(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "Old", "starts_at": _ts(30), "ends_at": _ts(90)
    }).json()["id"]
    r = c.patch(f"/maintenance/{win_id}", json={"name": "New"})
    assert r.status_code == 200
    assert c.get(f"/maintenance/{win_id}").json()["name"] == "New"


def test_patch_window_no_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "X", "starts_at": _ts(30), "ends_at": _ts(90)
    }).json()["id"]
    r = c.patch(f"/maintenance/{win_id}", json={})
    assert r.status_code == 400


def test_patch_window_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.patch("/maintenance/ghost", json={"name": "Y"})
    assert r.status_code == 404


def test_patch_invalid_timestamp(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "X", "starts_at": _ts(30), "ends_at": _ts(90)
    }).json()["id"]
    r = c.patch(f"/maintenance/{win_id}", json={"starts_at": "not-a-date"})
    assert r.status_code == 400


# ── REST: delete ──────────────────────────────────────────────────────────────

def test_delete_window(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "Del", "starts_at": _ts(30), "ends_at": _ts(90)
    }).json()["id"]
    r = c.delete(f"/maintenance/{win_id}")
    assert r.status_code == 204
    assert c.get(f"/maintenance/{win_id}").status_code == 404


def test_delete_active_window_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "X", "starts_at": _ts(-10), "ends_at": _ts(60)
    }).json()["id"]
    c.post(f"/maintenance/{win_id}/activate")
    r = c.delete(f"/maintenance/{win_id}")
    assert r.status_code == 409


def test_delete_removes_log(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(maint.router)
    app.dependency_overrides[maint.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    win_id = c.post("/maintenance", json={
        "name": "X", "starts_at": _ts(30), "ends_at": _ts(90)
    }).json()["id"]
    c.delete(f"/maintenance/{win_id}")
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM maintenance_log WHERE window_id=?", (win_id,)).fetchone()[0]
    con.close()
    assert count == 0


# ── REST: lifecycle actions ───────────────────────────────────────────────────

def test_activate_window(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "X", "starts_at": _ts(-10), "ends_at": _ts(60)
    }).json()["id"]
    bus = MagicMock(); bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        r = c.post(f"/maintenance/{win_id}/activate")
    assert r.status_code == 200
    assert r.json()["status"] == "active"
    assert c.get(f"/maintenance/{win_id}").json()["status"] == "active"


def test_activate_already_active_fails(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "X", "starts_at": _ts(-10), "ends_at": _ts(60)
    }).json()["id"]
    bus = MagicMock(); bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        c.post(f"/maintenance/{win_id}/activate")
        r = c.post(f"/maintenance/{win_id}/activate")
    assert r.status_code == 409


def test_complete_window(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "X", "starts_at": _ts(-10), "ends_at": _ts(60)
    }).json()["id"]
    bus = MagicMock(); bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        c.post(f"/maintenance/{win_id}/activate")
        r = c.post(f"/maintenance/{win_id}/complete")
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


def test_complete_scheduled_window_fails(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "X", "starts_at": _ts(30), "ends_at": _ts(90)
    }).json()["id"]
    r = c.post(f"/maintenance/{win_id}/complete")
    assert r.status_code == 409


def test_cancel_scheduled_window(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "X", "starts_at": _ts(30), "ends_at": _ts(90)
    }).json()["id"]
    bus = MagicMock(); bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        r = c.post(f"/maintenance/{win_id}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_cancel_completed_window_fails(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    win_id = c.post("/maintenance", json={
        "name": "X", "starts_at": _ts(-10), "ends_at": _ts(60)
    }).json()["id"]
    bus = MagicMock(); bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        c.post(f"/maintenance/{win_id}/activate")
        c.post(f"/maintenance/{win_id}/complete")
        r = c.post(f"/maintenance/{win_id}/cancel")
    assert r.status_code == 409


def test_action_on_nonexistent_window(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.post("/maintenance/ghost/activate").status_code == 404
    assert c.post("/maintenance/ghost/complete").status_code == 404
    assert c.post("/maintenance/ghost/cancel").status_code == 404


# ── ensure_maintenance_running ────────────────────────────────────────────────

def test_ensure_maintenance_running_starts_checker(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    async def run():
        await maint.ensure_maintenance_running()
        checker = maint.get_checker()
        assert checker is not None
        await checker.stop()

    _run(run())


def test_ensure_maintenance_running_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    async def run():
        await maint.ensure_maintenance_running()
        first = maint.get_checker()
        await maint.ensure_maintenance_running()
        second = maint.get_checker()
        assert first is second
        await first.stop()

    _run(run())
