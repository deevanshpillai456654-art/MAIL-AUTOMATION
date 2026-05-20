"""Tests for backend/api/oncall.py"""
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

import backend.api.oncall as oc


def _run(coro):
    return asyncio.run(coro)


def _setup(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "oncall.db")
    monkeypatch.setattr(oc, "_DB_PATH", db)
    monkeypatch.setattr(oc, "_running", False)
    monkeypatch.setattr(oc, "_checker", None)
    oc._init_db()
    return db


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(oc.router)
    app.dependency_overrides[oc.require_local_auth] = lambda: "test"
    return TestClient(app, raise_server_exceptions=True)


def _ts(delta_minutes: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)).isoformat()


def _insert_schedule(db: str, *, enabled: int = 1) -> str:
    sch_id = str(uuid.uuid4())
    now = oc._now()
    con = sqlite3.connect(db)
    con.execute(
        f"INSERT INTO oncall_schedules ({','.join(oc._SCH_COLS)}) "
        f"VALUES ({','.join(['?']*len(oc._SCH_COLS))})",
        (sch_id, "Eng", "", "UTC", enabled, now, now),
    )
    con.commit()
    con.close()
    return sch_id


def _insert_slot(db: str, sch_id: str, *, starts_offset: int = -60,
                 ends_offset: int = 60, is_override: int = 0) -> str:
    slot_id = str(uuid.uuid4())
    con = sqlite3.connect(db)
    con.execute(
        f"INSERT INTO oncall_slots ({','.join(oc._SLOT_COLS)}) "
        f"VALUES ({','.join(['?']*len(oc._SLOT_COLS))})",
        (slot_id, sch_id, "Eng", "Alice", "alice@x.com",
         _ts(starts_offset), _ts(ends_offset), is_override, "", oc._now()),
    )
    con.commit()
    con.close()
    return slot_id


def _insert_escalation(db: str, sch_id: str, level: int = 1,
                        delay_minutes: int = 15) -> str:
    esc_id = str(uuid.uuid4())
    con = sqlite3.connect(db)
    con.execute(
        f"INSERT INTO oncall_escalations ({','.join(oc._ESC_COLS)}) "
        f"VALUES ({','.join(['?']*len(oc._ESC_COLS))})",
        (esc_id, sch_id, level, "Bob", "bob@x.com", "event", delay_minutes, oc._now()),
    )
    con.commit()
    con.close()
    return esc_id


# ── DB init ───────────────────────────────────────────────────────────────────

def test_init_creates_tables(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    con.close()
    assert {"oncall_schedules", "oncall_slots",
            "oncall_escalations", "oncall_notifications"} <= tables


# ── get_current_oncall ────────────────────────────────────────────────────────

def test_get_current_oncall_empty(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert oc.get_current_oncall() == []


def test_get_current_oncall_returns_active_slot(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch_id = _insert_schedule(db)
    _insert_slot(db, sch_id, starts_offset=-30, ends_offset=30)
    slots = oc.get_current_oncall()
    assert len(slots) == 1
    assert slots[0]["member_name"] == "Alice"


def test_get_current_oncall_excludes_past_slot(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch_id = _insert_schedule(db)
    _insert_slot(db, sch_id, starts_offset=-120, ends_offset=-60)
    assert oc.get_current_oncall() == []


def test_get_current_oncall_excludes_future_slot(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch_id = _insert_schedule(db)
    _insert_slot(db, sch_id, starts_offset=60, ends_offset=120)
    assert oc.get_current_oncall() == []


def test_get_current_oncall_filters_by_schedule(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch1 = _insert_schedule(db)
    sch2 = _insert_schedule(db)
    _insert_slot(db, sch1)
    _insert_slot(db, sch2)
    result = oc.get_current_oncall(schedule_id=sch1)
    assert all(s["schedule_id"] == sch1 for s in result)
    assert len(result) == 1


def test_get_current_oncall_override_first(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch_id = _insert_schedule(db)
    _insert_slot(db, sch_id, is_override=0)
    _insert_slot(db, sch_id, is_override=1)
    slots = oc.get_current_oncall(sch_id)
    assert slots[0]["is_override"] == 1


# ── _record_notification ──────────────────────────────────────────────────────

def test_record_notification_idempotent(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch_id = _insert_schedule(db)
    esc_id = _insert_escalation(db, sch_id)
    esc = {"id": esc_id, "level": 1, "contact_name": "Bob", "contact_email": ""}
    r1 = oc._record_notification("inc-1", sch_id, esc)
    r2 = oc._record_notification("inc-1", sch_id, esc)
    assert r1 is True
    assert r2 is False


def test_record_notification_different_levels_both_inserted(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch_id = _insert_schedule(db)
    esc1 = {"id": str(uuid.uuid4()), "level": 1, "contact_name": "A", "contact_email": ""}
    esc2 = {"id": str(uuid.uuid4()), "level": 2, "contact_name": "B", "contact_email": ""}
    assert oc._record_notification("inc-1", sch_id, esc1) is True
    assert oc._record_notification("inc-1", sch_id, esc2) is True


# ── _run_escalations ──────────────────────────────────────────────────────────

def test_run_escalations_emits_event_when_due(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch_id = _insert_schedule(db)
    _insert_escalation(db, sch_id, level=1, delay_minutes=10)
    # Incident created 30 minutes ago → exceeds 10-min threshold
    from datetime import datetime, timezone, timedelta
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    incident = {"id": "inc-1", "title": "Outage", "severity": "high",
                "created_at": old_ts}
    monkeypatch.setattr(oc, "_get_open_incidents", lambda: [incident])
    bus = MagicMock(); bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(oc._run_escalations())
    bus.publish.assert_awaited_once()
    event = bus.publish.call_args[0][0]
    assert event["type"] == "oncall.escalated"
    assert event["payload"]["level"] == 1


def test_run_escalations_no_event_below_threshold(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch_id = _insert_schedule(db)
    _insert_escalation(db, sch_id, level=1, delay_minutes=60)
    from datetime import datetime, timezone, timedelta
    recent_ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    incident = {"id": "inc-1", "title": "T", "severity": "high", "created_at": recent_ts}
    monkeypatch.setattr(oc, "_get_open_incidents", lambda: [incident])
    bus = MagicMock(); bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(oc._run_escalations())
    bus.publish.assert_not_awaited()


def test_run_escalations_idempotent(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch_id = _insert_schedule(db)
    _insert_escalation(db, sch_id, level=1, delay_minutes=10)
    from datetime import datetime, timezone, timedelta
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    incident = {"id": "inc-2", "title": "T", "severity": "high", "created_at": old_ts}
    monkeypatch.setattr(oc, "_get_open_incidents", lambda: [incident])
    bus = MagicMock(); bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(oc._run_escalations())
        _run(oc._run_escalations())
    assert bus.publish.await_count == 1


def test_run_escalations_skips_disabled_schedule(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    sch_id = _insert_schedule(db, enabled=0)
    _insert_escalation(db, sch_id, level=1, delay_minutes=1)
    from datetime import datetime, timezone, timedelta
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    incident = {"id": "inc-3", "title": "T", "severity": "high", "created_at": old_ts}
    monkeypatch.setattr(oc, "_get_open_incidents", lambda: [incident])
    bus = MagicMock(); bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(oc._run_escalations())
    bus.publish.assert_not_awaited()


def test_run_escalations_no_incidents_exits_early(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_schedule(db)
    monkeypatch.setattr(oc, "_get_open_incidents", lambda: [])
    bus = MagicMock(); bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(oc._run_escalations())
    bus.publish.assert_not_awaited()


# ── REST: schedules ───────────────────────────────────────────────────────────

def test_list_schedules_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/oncall/schedules")
    assert r.status_code == 200
    assert r.json()["schedules"] == []


def test_create_schedule_201(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/oncall/schedules", json={"name": "Eng"})
    assert r.status_code == 201
    assert "id" in r.json()


def test_current_oncall_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/oncall/schedules/current")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_get_schedule_with_detail(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    sch_id = c.post("/oncall/schedules", json={"name": "Ops"}).json()["id"]
    r = c.get(f"/oncall/schedules/{sch_id}")
    assert r.status_code == 200
    data = r.json()
    assert "upcoming_slots" in data
    assert "escalation_policy" in data
    assert "current_oncall" in data


def test_get_schedule_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/oncall/schedules/ghost").status_code == 404


def test_patch_schedule(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    sch_id = c.post("/oncall/schedules", json={"name": "Old"}).json()["id"]
    r = c.patch(f"/oncall/schedules/{sch_id}", json={"name": "New"})
    assert r.status_code == 200
    assert c.get(f"/oncall/schedules/{sch_id}").json()["name"] == "New"


def test_patch_schedule_no_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    sch_id = c.post("/oncall/schedules", json={"name": "X"}).json()["id"]
    assert c.patch(f"/oncall/schedules/{sch_id}", json={}).status_code == 400


def test_patch_schedule_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.patch("/oncall/schedules/ghost", json={"name": "Y"}).status_code == 404


def test_delete_schedule_cascades(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(oc.router)
    app.dependency_overrides[oc.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    sch_id = c.post("/oncall/schedules", json={"name": "Del"}).json()["id"]
    c.post("/oncall/slots", json={
        "schedule_id": sch_id, "member_name": "A",
        "starts_at": _ts(-60), "ends_at": _ts(60),
    })
    c.post("/oncall/escalations", json={
        "schedule_id": sch_id, "level": 1,
        "contact_name": "B", "delay_minutes": 15,
    })
    r = c.delete(f"/oncall/schedules/{sch_id}")
    assert r.status_code == 204
    con = sqlite3.connect(db)
    slots = con.execute("SELECT COUNT(*) FROM oncall_slots WHERE schedule_id=?", (sch_id,)).fetchone()[0]
    escs  = con.execute("SELECT COUNT(*) FROM oncall_escalations WHERE schedule_id=?", (sch_id,)).fetchone()[0]
    con.close()
    assert slots == 0
    assert escs  == 0


# ── REST: slots ───────────────────────────────────────────────────────────────

def test_create_slot_201(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    sch_id = c.post("/oncall/schedules", json={"name": "S"}).json()["id"]
    r = c.post("/oncall/slots", json={
        "schedule_id": sch_id, "member_name": "Alice",
        "starts_at": _ts(-60), "ends_at": _ts(60),
    })
    assert r.status_code == 201
    assert r.json()["member_name"] == "Alice"


def test_create_slot_end_before_start(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    sch_id = c.post("/oncall/schedules", json={"name": "S"}).json()["id"]
    r = c.post("/oncall/slots", json={
        "schedule_id": sch_id, "member_name": "A",
        "starts_at": _ts(60), "ends_at": _ts(-60),
    })
    assert r.status_code == 400


def test_create_slot_unknown_schedule(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/oncall/slots", json={
        "schedule_id": "no-such", "member_name": "A",
        "starts_at": _ts(-60), "ends_at": _ts(60),
    })
    assert r.status_code == 404


def test_delete_slot(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    sch_id  = c.post("/oncall/schedules", json={"name": "S"}).json()["id"]
    slot_id = c.post("/oncall/slots", json={
        "schedule_id": sch_id, "member_name": "A",
        "starts_at": _ts(-60), "ends_at": _ts(60),
    }).json()["id"]
    assert c.delete(f"/oncall/slots/{slot_id}").status_code == 204


# ── REST: escalations ─────────────────────────────────────────────────────────

def test_create_escalation_201(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    sch_id = c.post("/oncall/schedules", json={"name": "S"}).json()["id"]
    r = c.post("/oncall/escalations", json={
        "schedule_id": sch_id, "level": 1,
        "contact_name": "Bob", "delay_minutes": 15,
    })
    assert r.status_code == 201
    assert r.json()["level"] == 1


def test_create_escalation_duplicate_level_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    sch_id = c.post("/oncall/schedules", json={"name": "S"}).json()["id"]
    body = {"schedule_id": sch_id, "level": 1, "contact_name": "B", "delay_minutes": 15}
    c.post("/oncall/escalations", json=body)
    r = c.post("/oncall/escalations", json=body)
    assert r.status_code == 409


def test_create_escalation_invalid_level(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    sch_id = c.post("/oncall/schedules", json={"name": "S"}).json()["id"]
    r = c.post("/oncall/escalations", json={
        "schedule_id": sch_id, "level": 0,
        "contact_name": "B", "delay_minutes": 15,
    })
    assert r.status_code == 400


def test_create_escalation_unknown_schedule(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/oncall/escalations", json={
        "schedule_id": "no-such", "level": 1,
        "contact_name": "B", "delay_minutes": 15,
    })
    assert r.status_code == 404


def test_delete_escalation(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    sch_id = c.post("/oncall/schedules", json={"name": "S"}).json()["id"]
    esc_id = c.post("/oncall/escalations", json={
        "schedule_id": sch_id, "level": 1,
        "contact_name": "B", "delay_minutes": 15,
    }).json()["id"]
    assert c.delete(f"/oncall/escalations/{esc_id}").status_code == 204


# ── ensure_oncall_running ─────────────────────────────────────────────────────

def test_ensure_oncall_running_starts_checker(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    async def run():
        await oc.ensure_oncall_running()
        checker = oc.get_checker()
        assert checker is not None
        await checker.stop()
    _run(run())


def test_ensure_oncall_running_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    async def run():
        await oc.ensure_oncall_running()
        first = oc.get_checker()
        await oc.ensure_oncall_running()
        assert oc.get_checker() is first
        await first.stop()
    _run(run())


def test_ensure_oncall_running_honors_runtime_service_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_ONCALL", "false")
    _setup(tmp_path, monkeypatch)

    async def run():
        await oc.ensure_oncall_running()
        assert oc.get_checker() is None
        assert oc._running is False

    _run(run())
