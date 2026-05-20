"""Tests for platform_telemetry (backend/api/platform_telemetry.py)."""
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Seed helpers ──────────────────────────────────────────────────────────────

def _seed_main_db(path: str, emails: int = 0, scam: int = 0,
                  active_threats: int = 0, total_threats: int = 0):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY,
            is_read INTEGER DEFAULT 0,
            category TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS threat_lookalike_alerts (
            id INTEGER PRIMARY KEY,
            status TEXT,
            confidence_score REAL DEFAULT 50,
            impersonated_brand TEXT,
            created_at TEXT
        );
    """)
    now = datetime.now(timezone.utc).isoformat()
    for i in range(emails):
        cat = "Scam" if i < scam else "Normal"
        con.execute(
            "INSERT INTO emails (is_read, category, created_at) VALUES (?,?,?)",
            (0, cat, now),
        )
    for i in range(active_threats):
        con.execute(
            """INSERT INTO threat_lookalike_alerts
               (status, confidence_score, impersonated_brand, created_at)
               VALUES ('active', 95, 'Amazon', ?)""",
            (now,),
        )
    for i in range(max(0, total_threats - active_threats)):
        con.execute(
            """INSERT INTO threat_lookalike_alerts
               (status, confidence_score, impersonated_brand, created_at)
               VALUES ('resolved', 80, 'PayPal', ?)""",
            (now,),
        )
    con.commit()
    con.close()


def _seed_workflows_db(path: str, active: int = 2, succeeded: int = 5, failed: int = 1):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY,
            name TEXT,
            is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id TEXT PRIMARY KEY,
            workflow_id TEXT,
            status TEXT,
            duration_ms INTEGER,
            created_at TEXT
        );
    """)
    now = datetime.now(timezone.utc).isoformat()
    for i in range(active):
        con.execute("INSERT INTO workflows (id, name, is_active) VALUES (?,?,1)", (f"wf-{i}", f"WF{i}"))
    for i in range(succeeded):
        con.execute(
            "INSERT INTO workflow_executions (id, workflow_id, status, duration_ms, created_at) VALUES (?,?,?,?,?)",
            (f"ok-{i}", "wf-0", "succeeded", 1500, now),
        )
    for i in range(failed):
        con.execute(
            "INSERT INTO workflow_executions (id, workflow_id, status, duration_ms, created_at) VALUES (?,?,?,?,?)",
            (f"fail-{i}", "wf-0", "failed", 500, now),
        )
    con.commit()
    con.close()


def _seed_events_db(path: str, count: int = 10):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS operational_events (
            id TEXT PRIMARY KEY,
            type TEXT,
            created_at TEXT
        );
    """)
    now = datetime.now(timezone.utc).isoformat()
    for i in range(count):
        con.execute(
            "INSERT INTO operational_events (id, type, created_at) VALUES (?,?,?)",
            (f"ev-{i}", "email.received", now),
        )
    con.commit()
    con.close()


def _seed_actions_db(path: str, count: int = 5):
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS agent_actions (
            id TEXT PRIMARY KEY,
            agent_id TEXT,
            action_type TEXT,
            metadata TEXT,
            created_at TEXT
        );
    """)
    now = datetime.now(timezone.utc).isoformat()
    for i in range(count):
        con.execute(
            "INSERT INTO agent_actions (id, agent_id, action_type, metadata, created_at) VALUES (?,?,?,?,?)",
            (f"ac-{i}", "agent-1", "insight", "{}", now),
        )
    con.commit()
    con.close()


def _patch_all(tmp_path, monkeypatch, **kw):
    from backend.api import platform_telemetry as pt

    main_db = str(tmp_path / "main.db")
    wf_db   = str(tmp_path / "workflows.db")
    ev_db   = str(tmp_path / "events.db")
    act_db  = str(tmp_path / "actions.db")

    _seed_main_db(main_db, **{k: v for k, v in kw.items()
                               if k in ("emails", "scam", "active_threats", "total_threats")})
    _seed_workflows_db(wf_db, **{k: v for k, v in kw.items()
                                  if k in ("active", "succeeded", "failed")})
    _seed_events_db(ev_db)
    _seed_actions_db(act_db)

    monkeypatch.setattr(pt, "DB_PATH",       main_db)
    monkeypatch.setattr(pt, "_WORKFLOWS_DB", wf_db)
    monkeypatch.setattr(pt, "_EVENTS_DB",    ev_db)
    monkeypatch.setattr(pt, "_ACTIONS_DB",   act_db)


# ── Collector unit tests ──────────────────────────────────────────────────────

def test_email_metrics_empty(tmp_path, monkeypatch):
    from backend.api import platform_telemetry as pt
    main_db = str(tmp_path / "main.db")
    _seed_main_db(main_db)
    monkeypatch.setattr(pt, "DB_PATH", main_db)

    m = pt._email_metrics()
    assert m["total"] == 0
    assert m["unread"] == 0
    assert m["last_24h"] == 0
    assert m["scam_last_24h"] == 0


def test_email_metrics_with_data(tmp_path, monkeypatch):
    from backend.api import platform_telemetry as pt
    main_db = str(tmp_path / "main.db")
    _seed_main_db(main_db, emails=10, scam=3)
    monkeypatch.setattr(pt, "DB_PATH", main_db)

    m = pt._email_metrics()
    assert m["total"] == 10
    assert m["last_24h"] == 10
    assert m["scam_last_24h"] == 3


def test_security_posture_good(tmp_path, monkeypatch):
    from backend.api import platform_telemetry as pt
    main_db = str(tmp_path / "main.db")
    _seed_main_db(main_db, active_threats=0)
    monkeypatch.setattr(pt, "DB_PATH", main_db)

    m = pt._security_metrics()
    assert m["posture"] == "good"
    assert m["active_threats"] == 0


def test_security_posture_medium(tmp_path, monkeypatch):
    from backend.api import platform_telemetry as pt
    main_db = str(tmp_path / "main.db")
    _seed_main_db(main_db, active_threats=5)
    monkeypatch.setattr(pt, "DB_PATH", main_db)

    m = pt._security_metrics()
    assert m["posture"] == "medium"


def test_security_posture_critical(tmp_path, monkeypatch):
    from backend.api import platform_telemetry as pt
    main_db = str(tmp_path / "main.db")
    _seed_main_db(main_db, active_threats=25)
    monkeypatch.setattr(pt, "DB_PATH", main_db)

    m = pt._security_metrics()
    assert m["posture"] == "critical"
    assert m["active_threats"] == 25


def test_workflow_success_rate(tmp_path, monkeypatch):
    from backend.api import platform_telemetry as pt
    wf_db = str(tmp_path / "workflows.db")
    _seed_workflows_db(wf_db, succeeded=8, failed=2)
    monkeypatch.setattr(pt, "_WORKFLOWS_DB", wf_db)

    m = pt._workflow_metrics()
    assert m["success_rate_24h"] == 80.0
    assert m["sla_ok"] is True


def test_workflow_100pct_when_no_executions(tmp_path, monkeypatch):
    from backend.api import platform_telemetry as pt
    wf_db = str(tmp_path / "workflows.db")
    _seed_workflows_db(wf_db, succeeded=0, failed=0)
    monkeypatch.setattr(pt, "_WORKFLOWS_DB", wf_db)

    m = pt._workflow_metrics()
    assert m["success_rate_24h"] == 100.0


def test_event_bus_metrics(tmp_path, monkeypatch):
    from backend.api import platform_telemetry as pt
    ev_db = str(tmp_path / "events.db")
    _seed_events_db(ev_db, count=15)
    monkeypatch.setattr(pt, "_EVENTS_DB", ev_db)

    m = pt._event_bus_metrics()
    assert m["total_events"] == 15
    assert m["events_last_24h"] == 15


def test_compute_overall_health_healthy():
    from backend.api.platform_telemetry import _compute_overall_health

    emails    = {"unread": 0,   "last_24h": 10, "last_1h": 1,  "scam_last_24h": 0}
    security  = {"posture": "good",  "active_threats": 0,  "threats_last_24h": 0}
    workflows = {"success_rate_24h": 100.0, "sla_ok": True}
    agents    = {"running_agents": 4, "total_agents": 4}

    h = _compute_overall_health(emails, security, workflows, agents)
    assert h["overall"] >= 80
    assert h["status"] == "healthy"
    assert "components" in h


def test_compute_overall_health_critical():
    from backend.api.platform_telemetry import _compute_overall_health

    emails    = {"unread": 100, "last_24h": 200, "last_1h": 50, "scam_last_24h": 20}
    security  = {"posture": "critical", "active_threats": 25, "threats_last_24h": 10}
    workflows = {"success_rate_24h": 20.0, "sla_ok": False}
    agents    = {"running_agents": 0, "total_agents": 4}

    h = _compute_overall_health(emails, security, workflows, agents)
    assert h["status"] in ("degraded", "critical")
    assert 0 <= h["overall"] <= 100


def test_compute_overall_health_uses_enabled_agents_not_total_registered():
    from backend.api.platform_telemetry import _compute_overall_health

    emails    = {"unread": 0, "last_24h": 10, "last_1h": 1, "scam_last_24h": 0}
    security  = {"posture": "good", "active_threats": 0, "threats_last_24h": 0}
    workflows = {"success_rate_24h": 100.0, "sla_ok": True}
    agents    = {"running_agents": 1, "enabled_agents": 1, "disabled_agents": 5, "total_agents": 6}

    h = _compute_overall_health(emails, security, workflows, agents)

    assert h["components"]["agents"]["score"] == 100


def test_summary_agent_metric_alert_uses_enabled_agents(tmp_path, monkeypatch):
    from backend.api import platform_telemetry as pt

    def fake_agent_metrics():
        return {
            "total_agents": 6,
            "enabled_agents": 1,
            "disabled_agents": 5,
            "running_agents": 1,
            "total_actions": 0,
            "anomalies_24h": 0,
            "insights_24h": 0,
        }

    monkeypatch.setattr(pt, "_agent_metrics", fake_agent_metrics)
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/telemetry/summary")

    assert resp.status_code == 200
    agent_m = next(m for m in resp.json()["metrics"] if m["id"] == "agents_running")
    assert agent_m["unit"] == "/1 enabled"
    assert agent_m["alert"] is False


# ── REST endpoint tests ───────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch, **kw):
    from backend.api import platform_telemetry as pt
    from backend.auth.local_auth import require_local_auth

    _patch_all(tmp_path, monkeypatch, **kw)

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(pt.router, prefix="/api/v1")
    return TestClient(app)


def test_telemetry_full_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, emails=10, active_threats=2)
    resp = client.get("/api/v1/telemetry")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("health", "email", "security", "workflows", "event_bus", "agents", "timestamp"):
        assert key in data, f"missing key: {key}"


def test_telemetry_full_has_reconciler_and_scheduler(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/telemetry")
    assert resp.status_code == 200
    data = resp.json()
    assert "reconciler" in data
    assert "scheduler" in data


def test_telemetry_summary_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, emails=5, active_threats=0)
    resp = client.get("/api/v1/telemetry/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "health_score" in data
    assert "health_status" in data
    assert "metrics" in data
    assert len(data["metrics"]) == 4


def test_summary_metric_ids(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/telemetry/summary")
    assert resp.status_code == 200
    ids = {m["id"] for m in resp.json()["metrics"]}
    assert ids == {"email_volume", "active_threats", "workflow_success", "agents_running"}


def test_summary_alert_flag_for_threats(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, active_threats=15)
    resp = client.get("/api/v1/telemetry/summary")
    assert resp.status_code == 200
    threat_m = next(m for m in resp.json()["metrics"] if m["id"] == "active_threats")
    assert threat_m["alert"] is True
    assert threat_m["value"] == 15


def test_health_score_is_int_0_to_100(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/telemetry/summary")
    assert resp.status_code == 200
    score = resp.json()["health_score"]
    assert isinstance(score, int)
    assert 0 <= score <= 100


def test_summary_health_status_valid_values(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/telemetry/summary")
    assert resp.status_code == 200
    status = resp.json()["health_status"]
    assert status in ("healthy", "degraded", "critical")
