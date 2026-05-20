"""Tests for backend/api/problem_management.py"""
from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.problem_management as pm_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "pm_test.db")
    monkeypatch.setattr(pm_mod, "_DB_PATH", db_path)

    # Reinitialise DB against the temp file
    pm_mod._init_db()

    # Override auth
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(pm_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"title": "Test problem", "priority": "medium", **kwargs}
    r = c.post("/api/v1/problems", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, pr_id, status, **kwargs):
    r = c.post(f"/api/v1/problems/{pr_id}/transition", json={"status": status, **kwargs})
    return r


# ── CRUD ─────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, title="DB timeouts", priority="high", category="database", owner="sre-team")
    pr_id = d["id"]
    assert d["status"] == "open"

    r = c.get(f"/api/v1/problems/{pr_id}")
    assert r.status_code == 200
    p = r.json()
    assert p["title"] == "DB timeouts"
    assert p["priority"] == "high"
    assert p["category"] == "database"
    assert p["owner"] == "sre-team"
    assert p["status"] == "open"
    assert p["resolved_at"] is None


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="First")
    _create(c, title="Second")
    r = c.get("/api/v1/problems")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    titles = {p["title"] for p in d["problems"]}
    assert "First" in titles and "Second" in titles


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, title="A")
    _create(c, title="B")
    _transition(c, d1["id"], "investigating")

    r = c.get("/api/v1/problems?status=investigating")
    assert r.json()["total"] == 1
    assert r.json()["problems"][0]["id"] == d1["id"]


def test_list_filter_by_priority(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="Low one", priority="low")
    _create(c, title="Critical one", priority="critical")
    r = c.get("/api/v1/problems?priority=critical")
    assert r.json()["total"] == 1
    assert r.json()["problems"][0]["priority"] == "critical"


def test_list_search(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="Database timeout issue")
    _create(c, title="Network latency spike")
    r = c.get("/api/v1/problems?q=database")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, title=f"Problem {i}")
    r = c.get("/api/v1/problems?limit=3&offset=0")
    d = r.json()
    assert d["total"] == 5
    assert len(d["problems"]) == 3
    r2 = c.get("/api/v1/problems?limit=3&offset=3")
    assert len(r2.json()["problems"]) == 2


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    pr_id = d["id"]
    r = c.patch(f"/api/v1/problems/{pr_id}", json={
        "title": "Updated Title", "priority": "critical", "owner": "new-owner"
    })
    assert r.status_code == 200
    p = c.get(f"/api/v1/problems/{pr_id}").json()
    assert p["title"] == "Updated Title"
    assert p["priority"] == "critical"
    assert p["owner"] == "new-owner"


def test_delete_removes_problem(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    pr_id = d["id"]
    r = c.delete(f"/api/v1/problems/{pr_id}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/problems/{pr_id}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/problems/no-such-id").status_code == 404


def test_invalid_priority_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/problems", json={"title": "X", "priority": "enormous"})
    assert r.status_code == 400


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_open_to_investigating(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "investigating")
    assert r.status_code == 200
    assert c.get(f"/api/v1/problems/{d['id']}").json()["status"] == "investigating"


def test_transition_to_known_error(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "investigating")
    r = _transition(c, d["id"], "known_error")
    assert r.status_code == 200
    assert c.get(f"/api/v1/problems/{d['id']}").json()["status"] == "known_error"


def test_transition_to_resolved_sets_resolved_at(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "investigating")
    _transition(c, d["id"], "resolved")
    p = c.get(f"/api/v1/problems/{d['id']}").json()
    assert p["status"] == "resolved"
    assert p["resolved_at"] is not None


def test_transition_to_closed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "investigating")
    _transition(c, d["id"], "resolved")
    _transition(c, d["id"], "closed")
    assert c.get(f"/api/v1/problems/{d['id']}").json()["status"] == "closed"


def test_closed_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "investigating")
    _transition(c, d["id"], "resolved")
    _transition(c, d["id"], "closed")
    r = _transition(c, d["id"], "open")
    assert r.status_code == 400


def test_direct_open_to_closed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "closed")
    assert r.status_code == 200
    assert c.get(f"/api/v1/problems/{d['id']}").json()["status"] == "closed"


def test_reopen_from_resolved(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "investigating")
    _transition(c, d["id"], "resolved")
    r = _transition(c, d["id"], "open")
    assert r.status_code == 200
    p = c.get(f"/api/v1/problems/{d['id']}").json()
    assert p["status"] == "open"
    assert p["resolved_at"] is None


def test_invalid_transition_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "resolved")
    assert r.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "nonexistent_status")
    assert r.status_code == 400


def test_transition_nonexistent_problem_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-such-id", "investigating")
    assert r.status_code == 404


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/problems/stats")
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_stats_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c)
    d2 = _create(c)
    _transition(c, d1["id"], "investigating")
    r = c.get("/api/v1/problems/stats")
    d = r.json()
    assert d["total"] == 2
    by_status = {x["status"]: x["count"] for x in d["by_status"]}
    assert by_status.get("investigating", 0) == 1
    assert by_status.get("open", 0) == 1


def test_stats_by_priority(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, priority="critical")
    _create(c, priority="high")
    _create(c, priority="critical")
    r = c.get("/api/v1/problems/stats")
    by_priority = {x["priority"]: x["count"] for x in r.json()["by_priority"]}
    assert by_priority.get("critical", 0) == 2
    assert by_priority.get("high", 0) == 1


# ── Incident linking ──────────────────────────────────────────────────────────

def test_link_and_list_incidents(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    pr_id = d["id"]
    r = c.post(f"/api/v1/problems/{pr_id}/incidents", json={"incident_id": "INC-001"})
    assert r.status_code == 201
    r2 = c.get(f"/api/v1/problems/{pr_id}/incidents")
    assert r2.status_code == 200
    incidents = r2.json().get("incidents", r2.json())
    assert any(i["incident_id"] == "INC-001" for i in incidents)


def test_link_multiple_incidents(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    pr_id = d["id"]
    c.post(f"/api/v1/problems/{pr_id}/incidents", json={"incident_id": "INC-001"})
    c.post(f"/api/v1/problems/{pr_id}/incidents", json={"incident_id": "INC-002"})
    r = c.get(f"/api/v1/problems/{pr_id}/incidents")
    incidents = r.json().get("incidents", r.json())
    assert len(incidents) == 2


def test_duplicate_incident_link_returns_409(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    pr_id = d["id"]
    c.post(f"/api/v1/problems/{pr_id}/incidents", json={"incident_id": "INC-001"})
    r = c.post(f"/api/v1/problems/{pr_id}/incidents", json={"incident_id": "INC-001"})
    assert r.status_code == 409


def test_unlink_incident(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    pr_id = d["id"]
    c.post(f"/api/v1/problems/{pr_id}/incidents", json={"incident_id": "INC-001"})
    r = c.delete(f"/api/v1/problems/{pr_id}/incidents/INC-001")
    assert r.status_code in (200, 204)
    incidents = c.get(f"/api/v1/problems/{pr_id}/incidents").json().get("incidents", [])
    assert not any(i["incident_id"] == "INC-001" for i in incidents)


def test_unlink_nonexistent_incident_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/problems/{d['id']}/incidents/NO-SUCH")
    assert r.status_code == 404


# ── Timeline ──────────────────────────────────────────────────────────────────

def test_timeline_seeded_on_create(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.get(f"/api/v1/problems/{d['id']}/timeline")
    assert r.status_code == 200
    tl = r.json().get("timeline", r.json())
    assert len(tl) >= 1


def test_add_timeline_entry(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/problems/{d['id']}/timeline", json={
        "event_type": "note", "note": "Checked server logs", "author": "alice"
    })
    assert r.status_code == 201
    tl = c.get(f"/api/v1/problems/{d['id']}/timeline").json().get("timeline", [])
    assert any(e["note"] == "Checked server logs" for e in tl)


def test_invalid_event_type_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/problems/{d['id']}/timeline", json={
        "event_type": "invented_type", "note": "X"
    })
    assert r.status_code == 400


def test_timeline_status_change_on_transition(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "investigating", note="Starting investigation")
    tl = c.get(f"/api/v1/problems/{d['id']}/timeline").json().get("timeline", [])
    types = [e["event_type"] for e in tl]
    assert "status_change" in types


def test_root_cause_patch_adds_timeline(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    c.patch(f"/api/v1/problems/{d['id']}", json={"root_cause": "Memory leak in worker"})
    tl = c.get(f"/api/v1/problems/{d['id']}/timeline").json().get("timeline", [])
    types = [e["event_type"] for e in tl]
    assert "root_cause_updated" in types


def test_workaround_patch_adds_timeline(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    c.patch(f"/api/v1/problems/{d['id']}", json={"workaround": "Restart worker every hour"})
    tl = c.get(f"/api/v1/problems/{d['id']}/timeline").json().get("timeline", [])
    types = [e["event_type"] for e in tl]
    assert "workaround_updated" in types


# ── Cascade delete ────────────────────────────────────────────────────────────

def test_delete_cascades_incidents_and_timeline(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    pr_id = d["id"]
    c.post(f"/api/v1/problems/{pr_id}/incidents", json={"incident_id": "INC-X"})
    c.post(f"/api/v1/problems/{pr_id}/timeline", json={"event_type": "note", "note": "Keep"})
    c.delete(f"/api/v1/problems/{pr_id}")
    # Problem is gone
    assert c.get(f"/api/v1/problems/{pr_id}").status_code == 404
    # Data is fully removed (no orphan records)
    import sqlite3
    con = sqlite3.connect(pm_mod._DB_PATH)
    inc_count = con.execute("SELECT COUNT(*) FROM problem_incidents WHERE problem_id=?", (pr_id,)).fetchone()[0]
    tl_count  = con.execute("SELECT COUNT(*) FROM problem_timeline WHERE problem_id=?",  (pr_id,)).fetchone()[0]
    con.close()
    assert inc_count == 0
    assert tl_count  == 0


# ── Resolved_at lifecycle ──────────────────────────────────────────────────────

def test_resolved_at_set_on_resolve(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "investigating")
    _transition(c, d["id"], "resolved")
    p = c.get(f"/api/v1/problems/{d['id']}").json()
    assert p["resolved_at"] is not None


def test_resolved_at_cleared_on_reopen(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "investigating")
    _transition(c, d["id"], "resolved")
    _transition(c, d["id"], "open")
    p = c.get(f"/api/v1/problems/{d['id']}").json()
    assert p["resolved_at"] is None


def test_resolved_at_set_on_closed_from_open(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "closed")
    p = c.get(f"/api/v1/problems/{d['id']}").json()
    assert p["resolved_at"] is not None
