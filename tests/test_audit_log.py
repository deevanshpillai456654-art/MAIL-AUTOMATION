"""Tests for backend/api/audit_log.py"""
import asyncio
import csv
import io
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _setup(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = str(tmp_path / "audit_log.db")
    monkeypatch.setattr(al, "_DB_PATH", db_path)
    monkeypatch.setattr(al, "_subscribed", False)
    al._init_db()
    return db_path


def _client(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    from backend.auth.local_auth import require_local_auth
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(al.router, prefix="/api/v1")
    return TestClient(app)


def _seed(db_path: str, count: int = 5, severity: str = "info", event_type: str = "test.event"):
    con = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc)
    for i in range(count):
        ts = (now - timedelta(hours=i)).isoformat()
        con.execute(
            """INSERT INTO audit_entries
               (id, ts, event_type, actor, resource_type, resource_id,
                action, outcome, severity, summary)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), ts, event_type, "test", "test",
             "", "action", "ok", severity, f"Summary {i}"),
        )
    con.commit()
    con.close()


# ── _resource_type ────────────────────────────────────────────────────────────

def test_resource_type_known_prefix():
    from backend.api.audit_log import _resource_type
    assert _resource_type("alert.threshold.breach") == "alert_rule"
    assert _resource_type("threat.detected") == "threat"
    assert _resource_type("workflow.completed") == "workflow"
    assert _resource_type("webhook.failed") == "webhook"


def test_resource_type_unknown_prefix():
    from backend.api.audit_log import _resource_type
    assert _resource_type("custom.event") == "custom"


# ── _make_summary ─────────────────────────────────────────────────────────────

def test_make_summary_alert_breach():
    from backend.api.audit_log import _make_summary
    s = _make_summary("alert.threshold.breach", {
        "metric": "active_threats", "operator": ">", "threshold": 10, "value": 15,
        "message": "active_threats > 10 (current=15)"
    })
    assert "active_threats" in s


def test_make_summary_threat_detected():
    from backend.api.audit_log import _make_summary
    s = _make_summary("threat.detected", {"impersonated_brand": "PayPal", "domain": "paypa1.com"})
    assert "PayPal" in s
    assert "paypa1.com" in s


def test_make_summary_failed_event():
    from backend.api.audit_log import _make_summary
    s = _make_summary("webhook.failed", {"error": "Connection refused"})
    assert "Connection refused" in s


def test_make_summary_fallback():
    from backend.api.audit_log import _make_summary
    s = _make_summary("email.classified", {})
    assert len(s) > 0


# ── _event_to_entry ───────────────────────────────────────────────────────────

def test_event_to_entry_fields():
    from backend.api.audit_log import _event_to_entry
    event = {
        "type":       "threat.detected",
        "severity":   "high",
        "source":     "threat_scanner",
        "id":         str(uuid.uuid4()),
        "payload":    {"domain": "evil.com", "impersonated_brand": "Amazon"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    entry = _event_to_entry(event)
    assert entry["event_type"] == "threat.detected"
    assert entry["severity"] == "high"
    assert entry["actor"] == "threat_scanner"
    assert entry["resource_type"] == "threat"
    assert "Amazon" in entry["summary"]


def test_event_to_entry_failed_outcome():
    from backend.api.audit_log import _event_to_entry
    entry = _event_to_entry({"type": "webhook.failed", "payload": {}, "severity": "medium"})
    assert entry["outcome"] == "error"


def test_event_to_entry_ok_outcome():
    from backend.api.audit_log import _event_to_entry
    entry = _event_to_entry({"type": "workflow.completed", "payload": {}, "severity": "info"})
    assert entry["outcome"] == "ok"


# ── _on_event ─────────────────────────────────────────────────────────────────

def test_on_event_stores_entry(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)

    event = {
        "type":       "alert.threshold.breach",
        "severity":   "high",
        "source":     "alert_engine",
        "id":         str(uuid.uuid4()),
        "payload":    {"metric": "active_threats", "operator": ">", "threshold": 10, "value": 15,
                       "message": "active_threats > 10 (current=15)"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _run(al._on_event(event))

    con = sqlite3.connect(db_path)
    count = con.execute(
        "SELECT COUNT(*) FROM audit_entries WHERE event_type='alert.threshold.breach'"
    ).fetchone()[0]
    con.close()
    assert count == 1


def test_on_event_captures_all_types(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)

    # Audit log captures EVERY event type, unlike notifications
    for evt in ["email.classified", "workflow.completed", "agent.action", "unknown.event"]:
        _run(al._on_event({"type": evt, "payload": {}, "severity": "info", "source": "test"}))

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0]
    con.close()
    assert count == 4


def test_on_event_deduplicates_by_id(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)

    event_id = str(uuid.uuid4())
    event = {"type": "test.event", "id": event_id, "payload": {}, "severity": "info", "source": "test"}
    _run(al._on_event(event))
    _run(al._on_event(event))  # Same ID — should be deduped via INSERT OR IGNORE

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0]
    con.close()
    assert count == 1


# ── write_audit_entry ─────────────────────────────────────────────────────────

def test_write_audit_entry_direct(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)

    al.write_audit_entry(
        event_type="admin.user.created",
        actor="admin",
        action="created",
        outcome="ok",
        severity="low",
        summary="User deesa created by admin",
        resource_type="user",
        resource_id="deesa",
    )

    con = sqlite3.connect(db_path)
    row = con.execute("SELECT actor, summary FROM audit_entries LIMIT 1").fetchone()
    con.close()
    assert row[0] == "admin"
    assert "deesa" in row[1]


# ── trim to max cap ───────────────────────────────────────────────────────────

def test_trim_keeps_max_entries(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)

    # Insert more than _MAX_ENTRIES records
    con = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc)
    for i in range(al._MAX_ENTRIES + 5):
        ts = (now - timedelta(minutes=i)).isoformat()
        con.execute(
            "INSERT INTO audit_entries (id,ts,event_type,actor,resource_type,resource_id,action,outcome,severity,summary) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), ts, "test", "sys", "", "", "ev", "ok", "info", "S"),
        )
    con.commit()
    con.close()

    # Write one more — should trigger trim
    _run(al._on_event({"type": "trim.trigger", "payload": {}, "severity": "info", "source": "test"}))

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0]
    con.close()
    assert count <= al._MAX_ENTRIES


# ── 90-day pruning ────────────────────────────────────────────────────────────

def test_init_prunes_old_records(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = str(tmp_path / "audit_log.db")
    monkeypatch.setattr(al, "_DB_PATH", db_path)
    monkeypatch.setattr(al, "_subscribed", False)
    al._init_db()

    # Insert a record older than 90 days
    old_ts = (datetime.now(timezone.utc) - timedelta(days=91)).isoformat()
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO audit_entries (id,ts,event_type,actor,resource_type,resource_id,action,outcome,severity,summary) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), old_ts, "old.event", "sys", "", "", "ev", "ok", "info", "Old"),
    )
    con.commit()
    con.close()

    # Re-init prunes it
    al._init_db()
    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM audit_entries").fetchone()[0]
    con.close()
    assert count == 0


# ── REST: list ────────────────────────────────────────────────────────────────

def test_list_empty(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/audit-log")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"] == []
    assert data["total"] == 0


def test_list_returns_entries(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=7)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(al.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/audit-log?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 7
    assert len(data["entries"]) == 5


def test_list_filter_by_severity(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=4, severity="high")
    _seed(db_path, count=2, severity="info")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(al.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/audit-log?severity=high")
    assert resp.status_code == 200
    assert resp.json()["total"] == 4


def test_list_filter_by_event_type(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=3, event_type="threat.detected")
    _seed(db_path, count=5, event_type="email.classified")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(al.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/audit-log?event_type=threat.detected")
    assert resp.status_code == 200
    assert resp.json()["total"] == 3


def test_list_filter_by_q(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)
    # Seed with specific summary
    con = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    con.execute(
        "INSERT INTO audit_entries (id,ts,event_type,actor,resource_type,resource_id,action,outcome,severity,summary) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), now, "test", "sys", "", "", "ev", "ok", "info", "PayPal phishing detected"),
    )
    con.execute(
        "INSERT INTO audit_entries (id,ts,event_type,actor,resource_type,resource_id,action,outcome,severity,summary) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), now, "test", "sys", "", "", "ev", "ok", "info", "Workflow completed"),
    )
    con.commit()
    con.close()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(al.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/audit-log?q=PayPal")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_list_pagination_offset(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=10)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(al.router, prefix="/api/v1")
    client = TestClient(app)

    p1 = client.get("/api/v1/audit-log?limit=5&offset=0").json()
    p2 = client.get("/api/v1/audit-log?limit=5&offset=5").json()
    assert len(p1["entries"]) == 5
    assert len(p2["entries"]) == 5
    ids1 = {e["id"] for e in p1["entries"]}
    ids2 = {e["id"] for e in p2["entries"]}
    assert ids1.isdisjoint(ids2)


# ── REST: stats ───────────────────────────────────────────────────────────────

def test_stats_endpoint(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=4, severity="high", event_type="threat.detected")
    _seed(db_path, count=2, severity="info", event_type="email.classified")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(al.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/audit-log/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 6
    assert "last_24h" in data
    assert "by_severity" in data
    assert data["by_severity"].get("high") == 4
    assert "top_event_types" in data


# ── REST: export ──────────────────────────────────────────────────────────────

def test_export_csv(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=5)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(al.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/audit-log/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    reader = csv.DictReader(io.StringIO(resp.text))
    rows = list(reader)
    assert len(rows) == 5
    assert "event_type" in rows[0]
    assert "severity" in rows[0]


# ── REST: purge ───────────────────────────────────────────────────────────────

def test_purge_endpoint(tmp_path, monkeypatch):
    from backend.api import audit_log as al
    db_path = _setup(tmp_path, monkeypatch)

    # 2 recent + 3 old
    _seed(db_path, count=2)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    con = sqlite3.connect(db_path)
    for _ in range(3):
        con.execute(
            "INSERT INTO audit_entries (id,ts,event_type,actor,resource_type,resource_id,action,outcome,severity,summary) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), old_ts, "old", "sys", "", "", "ev", "ok", "info", "Old"),
        )
    con.commit()
    con.close()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(al.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post("/api/v1/audit-log/purge?days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["deleted"] == 3

    remaining = client.get("/api/v1/audit-log").json()
    assert remaining["total"] == 2
