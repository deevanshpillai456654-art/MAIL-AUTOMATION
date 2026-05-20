"""Tests for backend/api/incidents.py"""
import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _setup(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = str(tmp_path / "incidents.db")
    monkeypatch.setattr(im, "_DB_PATH", db_path)
    monkeypatch.setattr(im, "_subscribed", False)
    im._init_db()
    return db_path


def _client(tmp_path, monkeypatch):
    from backend.api import incidents as im
    from backend.auth.local_auth import require_local_auth
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    return TestClient(app)


def _make_breach_event(rule_id: str = "rule-1", metric: str = "active_threats",
                       severity: str = "high") -> dict:
    return {
        "type":       "alert.threshold.breach",
        "severity":   severity,
        "source":     "alert_engine",
        "id":         str(uuid.uuid4()),
        "payload": {
            "rule_id":    rule_id,
            "rule_name":  "Test Rule",
            "metric":     metric,
            "operator":   ">",
            "threshold":  10,
            "value":      15,
            "message":    f"{metric} > 10 (current=15)",
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


# ── _create_incident ──────────────────────────────────────────────────────────

def test_create_incident_writes_to_db(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)

    im._create_incident(title="Test Incident", severity="high", source="test")

    con = sqlite3.connect(db_path)
    row = con.execute("SELECT title, status, severity FROM incidents LIMIT 1").fetchone()
    con.close()
    assert row[0] == "Test Incident"
    assert row[1] == "open"
    assert row[2] == "high"


def test_create_incident_adds_timeline_entry(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)

    result = im._create_incident(title="T1", severity="medium", source="test")

    con = sqlite3.connect(db_path)
    tl = con.execute(
        "SELECT action FROM incident_timeline WHERE incident_id=?", (result["id"],)
    ).fetchone()
    con.close()
    assert tl[0] == "created"


# ── _on_breach ────────────────────────────────────────────────────────────────

def test_on_breach_creates_incident(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)

    _run(im._on_breach(_make_breach_event()))

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    con.close()
    assert count == 1


def test_on_breach_deduplicates_open(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)

    event = _make_breach_event(rule_id="rule-dup")
    _run(im._on_breach(event))
    _run(im._on_breach(event))  # Second breach — same rule still open

    con = sqlite3.connect(db_path)
    inc_count = con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    tl_count  = con.execute("SELECT COUNT(*) FROM incident_timeline WHERE action='repeated_breach'").fetchone()[0]
    con.close()
    # Only one incident, but a repeated_breach timeline entry
    assert inc_count == 1
    assert tl_count == 1


def test_on_breach_creates_new_after_resolve(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)

    event = _make_breach_event(rule_id="rule-cycle")
    _run(im._on_breach(event))

    # Resolve the incident
    con = sqlite3.connect(db_path)
    inc_id = con.execute("SELECT id FROM incidents LIMIT 1").fetchone()[0]
    con.execute("UPDATE incidents SET status='resolved' WHERE id=?", (inc_id,))
    con.commit()
    con.close()

    # Next breach should create a new incident
    _run(im._on_breach(event))

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
    con.close()
    assert count == 2


def test_on_breach_sets_severity_and_metric(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)

    _run(im._on_breach(_make_breach_event(metric="scam_last_24h", severity="critical")))

    con = sqlite3.connect(db_path)
    row = con.execute("SELECT severity, metric FROM incidents LIMIT 1").fetchone()
    con.close()
    assert row[0] == "critical"
    assert row[1] == "scam_last_24h"


# ── _add_timeline ─────────────────────────────────────────────────────────────

def test_incident_manager_does_not_subscribe_when_service_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_INCIDENTS", "false")
    from backend.api import event_bus
    from backend.api import incidents as im
    _setup(tmp_path, monkeypatch)

    class FakeBus:
        def __init__(self):
            self.subscribed = []

        def subscribe(self, event_type, handler):
            self.subscribed.append((event_type, handler))

    fake_bus = FakeBus()
    monkeypatch.setattr(event_bus, "get_event_bus", lambda: fake_bus)

    im.ensure_incident_manager_running()

    assert fake_bus.subscribed == []
    assert im._subscribed is False


def test_add_timeline_entry(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)

    result = im._create_incident(title="T", severity="low", source="test")
    im._add_timeline(result["id"], actor="analyst", action="commented", note="Looking into this")

    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT action, actor, note FROM incident_timeline WHERE incident_id=?",
        (result["id"],),
    ).fetchall()
    con.close()
    actions = {r[0] for r in rows}
    assert "created" in actions
    assert "commented" in actions


# ── REST: list ────────────────────────────────────────────────────────────────

def test_list_empty(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/incidents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["incidents"] == []
    assert data["total"] == 0


def test_list_returns_incidents(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    for i in range(4):
        im._create_incident(title=f"Inc {i}", severity="medium", source="test")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/incidents")
    assert resp.status_code == 200
    assert resp.json()["total"] == 4


def test_list_filter_by_status(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    im._create_incident(title="Open",     severity="high",   source="test")
    r2 = im._create_incident(title="Resolved", severity="medium", source="test")
    # Mark one resolved
    con = sqlite3.connect(db_path)
    con.execute("UPDATE incidents SET status='resolved' WHERE id=?", (r2["id"],))
    con.commit()
    con.close()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/incidents?status=open")
    assert resp.json()["total"] == 1


# ── REST: create ──────────────────────────────────────────────────────────────

def test_create_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/incidents", json={
        "title": "DB connection pool exhausted",
        "description": "All DB connections in use",
        "severity": "critical",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "open"
    assert data["severity"] == "critical"


# ── REST: stats ───────────────────────────────────────────────────────────────

def test_stats_endpoint(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    im._create_incident(title="A", severity="high",   source="test")
    im._create_incident(title="B", severity="medium", source="test")
    r3 = im._create_incident(title="C", severity="low", source="test")
    con = sqlite3.connect(db_path)
    con.execute("UPDATE incidents SET status='resolved' WHERE id=?", (r3["id"],))
    con.commit()
    con.close()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/incidents/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert data["by_status"].get("open") == 2
    assert data["by_status"].get("resolved") == 1


# ── REST: detail ──────────────────────────────────────────────────────────────

def test_get_incident_detail(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    result = im._create_incident(title="Detail Test", severity="high", source="test")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get(f"/api/v1/incidents/{result['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["incident"]["title"] == "Detail Test"
    assert isinstance(data["timeline"], list)
    assert any(t["action"] == "created" for t in data["timeline"])


def test_get_incident_not_found(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/incidents/nonexistent-id")
    assert resp.status_code == 404


# ── REST: acknowledge ─────────────────────────────────────────────────────────

def test_acknowledge_endpoint(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    result = im._create_incident(title="Ack Test", severity="medium", source="test")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post(f"/api/v1/incidents/{result['id']}/acknowledge")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    detail = client.get(f"/api/v1/incidents/{result['id']}").json()
    assert detail["incident"]["status"] == "acknowledged"
    assert detail["incident"]["acknowledged_at"] is not None
    assert any(t["action"] == "acknowledged" for t in detail["timeline"])


def test_acknowledge_already_resolved_fails(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    result = im._create_incident(title="Resolved", severity="low", source="test")
    con = sqlite3.connect(db_path)
    con.execute("UPDATE incidents SET status='resolved' WHERE id=?", (result["id"],))
    con.commit()
    con.close()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post(f"/api/v1/incidents/{result['id']}/acknowledge")
    assert resp.status_code == 404


# ── REST: resolve ─────────────────────────────────────────────────────────────

def test_resolve_endpoint(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    result = im._create_incident(title="Resolve Test", severity="high", source="test")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post(f"/api/v1/incidents/{result['id']}/resolve")
    assert resp.status_code == 200

    detail = client.get(f"/api/v1/incidents/{result['id']}").json()
    assert detail["incident"]["status"] == "resolved"
    assert detail["incident"]["resolved_at"] is not None


def test_resolve_acknowledged_works(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    result = im._create_incident(title="Ack→Resolve", severity="medium", source="test")
    con = sqlite3.connect(db_path)
    con.execute("UPDATE incidents SET status='acknowledged' WHERE id=?", (result["id"],))
    con.commit()
    con.close()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post(f"/api/v1/incidents/{result['id']}/resolve")
    assert resp.status_code == 200


# ── REST: comment ─────────────────────────────────────────────────────────────

def test_comment_endpoint(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    result = im._create_incident(title="Comment Test", severity="low", source="test")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post(
        f"/api/v1/incidents/{result['id']}/comment",
        json={"note": "Investigating the root cause now"},
    )
    assert resp.status_code == 200

    detail = client.get(f"/api/v1/incidents/{result['id']}").json()
    comments = [t for t in detail["timeline"] if t["action"] == "commented"]
    assert len(comments) == 1
    assert "root cause" in comments[0]["note"]


def test_comment_empty_note_rejected(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    result = im._create_incident(title="T", severity="low", source="test")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post(f"/api/v1/incidents/{result['id']}/comment", json={"note": "  "})
    assert resp.status_code == 400


# ── REST: patch ───────────────────────────────────────────────────────────────

def test_patch_assigned_to(tmp_path, monkeypatch):
    from backend.api import incidents as im
    db_path = _setup(tmp_path, monkeypatch)
    result = im._create_incident(title="Patch Test", severity="medium", source="test")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(im.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.patch(
        f"/api/v1/incidents/{result['id']}",
        json={"assigned_to": "oncall-engineer"},
    )
    assert resp.status_code == 200

    detail = client.get(f"/api/v1/incidents/{result['id']}").json()
    assert detail["incident"]["assigned_to"] == "oncall-engineer"
