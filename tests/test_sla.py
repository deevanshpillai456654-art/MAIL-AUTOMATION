"""Tests for backend/api/sla.py"""
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

import backend.api.sla as sla


def _run(coro):
    return asyncio.run(coro)


def _setup(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "sla.db")
    monkeypatch.setattr(sla, "_DB_PATH", db)
    monkeypatch.setattr(sla, "_running", False)
    monkeypatch.setattr(sla, "_checker", None)
    sla._init_db()
    return db


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(sla.router)
    app.dependency_overrides[sla.require_local_auth] = lambda: "test"
    return TestClient(app, raise_server_exceptions=True)


def _insert_policy(db_path: str, *, severity="", response_minutes=60,
                   resolve_minutes=240, enabled=1) -> str:
    pol_id = str(uuid.uuid4())
    now = sla._now()
    con = sqlite3.connect(db_path)
    con.execute(
        f"INSERT INTO sla_policies ({','.join(sla._POLICY_COLS)}) "
        f"VALUES ({','.join(['?']*len(sla._POLICY_COLS))})",
        (pol_id, "Test Policy", severity, response_minutes, resolve_minutes,
         enabled, now, now),
    )
    con.commit()
    con.close()
    return pol_id


def _insert_breach(db_path: str, policy_id: str, incident_id: str,
                   breach_type: str = "response") -> str:
    breach_id = str(uuid.uuid4())
    now = sla._now()
    con = sqlite3.connect(db_path)
    con.execute(
        f"INSERT OR IGNORE INTO sla_breaches ({','.join(sla._BREACH_COLS)}) "
        f"VALUES ({','.join(['?']*len(sla._BREACH_COLS))})",
        (breach_id, policy_id, "Test Policy", incident_id, "Inc Title",
         "high", breach_type, now, 0, now),
    )
    con.commit()
    con.close()
    return breach_id


# ── DB init ───────────────────────────────────────────────────────────────────

def test_init_creates_tables(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    con.close()
    assert "sla_policies" in tables
    assert "sla_breaches" in tables


# ── _minutes_elapsed ──────────────────────────────────────────────────────────

def test_minutes_elapsed_returns_float():
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    elapsed = sla._minutes_elapsed(old)
    assert 29 < elapsed < 31


def test_minutes_elapsed_bad_input_returns_zero():
    assert sla._minutes_elapsed("not-a-date") == 0.0


# ── _insert_breach idempotency ────────────────────────────────────────────────

def test_insert_breach_returns_true_on_first(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    pol_id = _insert_policy(db)
    policy = {"id": pol_id, "name": "P"}
    incident = {"id": "inc-1", "title": "T", "severity": "high"}
    result = sla._insert_breach(policy, incident, "response")
    assert result is True


def test_insert_breach_returns_false_on_duplicate(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    pol_id = _insert_policy(db)
    policy = {"id": pol_id, "name": "P"}
    incident = {"id": "inc-1", "title": "T", "severity": "high"}
    sla._insert_breach(policy, incident, "response")
    result = sla._insert_breach(policy, incident, "response")
    assert result is False


def test_insert_breach_different_types_both_inserted(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    pol_id = _insert_policy(db)
    policy = {"id": pol_id, "name": "P"}
    incident = {"id": "inc-1", "title": "T", "severity": "high"}
    r1 = sla._insert_breach(policy, incident, "response")
    r2 = sla._insert_breach(policy, incident, "resolve")
    assert r1 and r2


# ── _check_sla ────────────────────────────────────────────────────────────────

def _fake_incident(status="open", minutes_ago=120, severity="high") -> dict:
    from datetime import datetime, timezone, timedelta
    created = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {"id": str(uuid.uuid4()), "title": "Test Inc",
            "severity": severity, "status": status, "created_at": created}


def test_check_sla_creates_response_breach(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    pol_id = _insert_policy(db, response_minutes=30, resolve_minutes=120)
    incident = _fake_incident(status="open", minutes_ago=60)
    monkeypatch.setattr(sla, "_fetch_open_incidents", lambda: [incident])
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        with patch("backend.api.incidents._add_timeline"):
            _run(sla._check_sla())
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM sla_breaches WHERE breach_type='response'").fetchone()[0]
    con.close()
    assert count == 1


def test_check_sla_creates_resolve_breach(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    pol_id = _insert_policy(db, response_minutes=30, resolve_minutes=60)
    incident = _fake_incident(status="acknowledged", minutes_ago=90)
    monkeypatch.setattr(sla, "_fetch_open_incidents", lambda: [incident])
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        with patch("backend.api.incidents._add_timeline"):
            _run(sla._check_sla())
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM sla_breaches WHERE breach_type='resolve'").fetchone()[0]
    con.close()
    assert count == 1


def test_check_sla_severity_filter_matches(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_policy(db, severity="critical", response_minutes=30, resolve_minutes=120)
    incident = _fake_incident(status="open", minutes_ago=60, severity="high")
    monkeypatch.setattr(sla, "_fetch_open_incidents", lambda: [incident])
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(sla._check_sla())
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM sla_breaches").fetchone()[0]
    con.close()
    assert count == 0


def test_check_sla_no_breach_within_limit(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_policy(db, response_minutes=120, resolve_minutes=480)
    incident = _fake_incident(status="open", minutes_ago=30)
    monkeypatch.setattr(sla, "_fetch_open_incidents", lambda: [incident])
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(sla._check_sla())
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM sla_breaches").fetchone()[0]
    con.close()
    assert count == 0


def test_check_sla_idempotent(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_policy(db, response_minutes=30, resolve_minutes=120)
    incident = _fake_incident(status="open", minutes_ago=60)
    monkeypatch.setattr(sla, "_fetch_open_incidents", lambda: [incident])
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        with patch("backend.api.incidents._add_timeline"):
            _run(sla._check_sla())
            _run(sla._check_sla())
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM sla_breaches WHERE breach_type='response'").fetchone()[0]
    con.close()
    assert count == 1


def test_check_sla_emits_event_on_breach(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_policy(db, response_minutes=30, resolve_minutes=120)
    incident = _fake_incident(status="open", minutes_ago=60)
    monkeypatch.setattr(sla, "_fetch_open_incidents", lambda: [incident])
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        with patch("backend.api.incidents._add_timeline"):
            _run(sla._check_sla())
    bus.publish.assert_awaited_once()
    event = bus.publish.call_args[0][0]
    assert event["type"] == "sla.breach"
    assert event["payload"]["breach_type"] == "response"


def test_check_sla_no_policies_exits_early(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    called = []
    monkeypatch.setattr(sla, "_fetch_open_incidents", lambda: (called.append(1) or []))
    _run(sla._check_sla())
    assert not called


def test_check_sla_no_incidents_exits_early(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    _insert_policy(db, response_minutes=30, resolve_minutes=120)
    monkeypatch.setattr(sla, "_fetch_open_incidents", lambda: [])
    bus = MagicMock()
    bus.publish = AsyncMock()
    with patch("backend.api.event_bus.get_event_bus", return_value=bus):
        _run(sla._check_sla())
    bus.publish.assert_not_awaited()


# ── REST: policies list ───────────────────────────────────────────────────────

def test_list_policies_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/sla/policies")
    assert r.status_code == 200
    assert r.json()["policies"] == []


def test_list_policies_returns_item(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/sla/policies", json={"name": "My SLA", "response_minutes": 60, "resolve_minutes": 240})
    r = c.get("/sla/policies")
    items = r.json()["policies"]
    assert len(items) == 1
    assert items[0]["name"] == "My SLA"


# ── REST: create policy ───────────────────────────────────────────────────────

def test_create_policy_201(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/sla/policies", json={
        "name": "P1", "response_minutes": 60, "resolve_minutes": 240
    })
    assert r.status_code == 201
    assert "id" in r.json()


def test_create_policy_invalid_severity(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/sla/policies", json={
        "name": "bad", "severity": "super", "response_minutes": 60, "resolve_minutes": 240
    })
    assert r.status_code == 400


def test_create_policy_resolve_must_exceed_response(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/sla/policies", json={
        "name": "bad", "response_minutes": 120, "resolve_minutes": 60
    })
    assert r.status_code == 400


def test_create_policy_equal_resolve_response_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/sla/policies", json={
        "name": "bad", "response_minutes": 60, "resolve_minutes": 60
    })
    assert r.status_code == 400


def test_create_policy_response_out_of_range(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/sla/policies", json={
        "name": "bad", "response_minutes": 0, "resolve_minutes": 60
    })
    assert r.status_code == 400


# ── REST: get policy ──────────────────────────────────────────────────────────

def test_get_policy(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pol_id = c.post("/sla/policies", json={"name": "X", "response_minutes": 30, "resolve_minutes": 120}).json()["id"]
    r = c.get(f"/sla/policies/{pol_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "X"
    assert "recent_breaches" in data


def test_get_policy_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/sla/policies/nonexistent")
    assert r.status_code == 404


# ── REST: policy stats ────────────────────────────────────────────────────────

def test_policy_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/sla/policies/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total_policies"] == 0
    assert data["open_breaches"] == 0


def test_policy_stats_counts(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(sla.router)
    app.dependency_overrides[sla.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    c.post("/sla/policies", json={"name": "P1", "response_minutes": 30, "resolve_minutes": 120})
    c.post("/sla/policies", json={"name": "P2", "response_minutes": 60, "resolve_minutes": 240, "enabled": False})
    r = c.get("/sla/policies/stats")
    data = r.json()
    assert data["total_policies"] == 2
    assert data["enabled_policies"] == 1


# ── REST: patch policy ────────────────────────────────────────────────────────

def test_patch_policy_name(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pol_id = c.post("/sla/policies", json={"name": "Old", "response_minutes": 30, "resolve_minutes": 120}).json()["id"]
    r = c.patch(f"/sla/policies/{pol_id}", json={"name": "New"})
    assert r.status_code == 200
    assert c.get(f"/sla/policies/{pol_id}").json()["name"] == "New"


def test_patch_policy_no_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pol_id = c.post("/sla/policies", json={"name": "X", "response_minutes": 30, "resolve_minutes": 120}).json()["id"]
    r = c.patch(f"/sla/policies/{pol_id}", json={})
    assert r.status_code == 400


def test_patch_policy_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.patch("/sla/policies/ghost", json={"name": "Y"})
    assert r.status_code == 404


def test_patch_invalid_severity(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pol_id = c.post("/sla/policies", json={"name": "X", "response_minutes": 30, "resolve_minutes": 120}).json()["id"]
    r = c.patch(f"/sla/policies/{pol_id}", json={"severity": "badvalue"})
    assert r.status_code == 400


# ── REST: delete policy ───────────────────────────────────────────────────────

def test_delete_policy(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    pol_id = c.post("/sla/policies", json={"name": "Del", "response_minutes": 30, "resolve_minutes": 120}).json()["id"]
    r = c.delete(f"/sla/policies/{pol_id}")
    assert r.status_code == 204
    assert c.get(f"/sla/policies/{pol_id}").status_code == 404


def test_delete_also_removes_breaches(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(sla.router)
    app.dependency_overrides[sla.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    pol_id = c.post("/sla/policies", json={"name": "X", "response_minutes": 30, "resolve_minutes": 120}).json()["id"]
    _insert_breach(db, pol_id, "inc-1", "response")
    c.delete(f"/sla/policies/{pol_id}")
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM sla_breaches WHERE policy_id=?", (pol_id,)).fetchone()[0]
    con.close()
    assert count == 0


# ── REST: breaches ────────────────────────────────────────────────────────────

def test_list_breaches_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/sla/breaches")
    assert r.status_code == 200
    assert r.json()["breaches"] == []
    assert r.json()["total"] == 0


def test_list_breaches_returns_item(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(sla.router)
    app.dependency_overrides[sla.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    pol_id = c.post("/sla/policies", json={"name": "P", "response_minutes": 30, "resolve_minutes": 120}).json()["id"]
    _insert_breach(db, pol_id, "inc-abc", "response")
    r = c.get("/sla/breaches")
    assert r.json()["total"] == 1
    assert r.json()["breaches"][0]["incident_id"] == "inc-abc"


def test_list_breaches_filter_by_type(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(sla.router)
    app.dependency_overrides[sla.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    pol_id = c.post("/sla/policies", json={"name": "P", "response_minutes": 30, "resolve_minutes": 120}).json()["id"]
    _insert_breach(db, pol_id, "inc-1", "response")
    _insert_breach(db, pol_id, "inc-1", "resolve")
    r = c.get("/sla/breaches?breach_type=response")
    items = r.json()["breaches"]
    assert all(b["breach_type"] == "response" for b in items)


# ── REST: status ──────────────────────────────────────────────────────────────

def test_sla_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/sla/status")
    assert r.status_code == 200
    data = r.json()
    assert "total_breaches" in data
    assert "checker_running" in data
    assert data["checker_running"] is False


# ── ensure_sla_running ────────────────────────────────────────────────────────

def test_ensure_sla_running_starts_checker(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    async def run():
        await sla.ensure_sla_running()
        checker = sla.get_checker()
        assert checker is not None
        await checker.stop()

    _run(run())


def test_ensure_sla_running_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    async def run():
        await sla.ensure_sla_running()
        first = sla.get_checker()
        await sla.ensure_sla_running()
        second = sla.get_checker()
        assert first is second
        await first.stop()

    _run(run())
