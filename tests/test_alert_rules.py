"""Tests for the alert rules engine (backend/api/alert_rules.py)."""
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _setup_dbs(tmp_path, monkeypatch):
    """Patch all DB paths to tmp_path and initialise."""
    from backend.api import alert_rules as ar

    db_path = str(tmp_path / "alert_rules.db")
    main_db = str(tmp_path / "main.db")
    wf_db   = str(tmp_path / "workflows.db")

    monkeypatch.setattr(ar, "_DB_PATH",      db_path)
    monkeypatch.setattr(ar, "DB_PATH",       main_db)
    monkeypatch.setattr(ar, "_WORKFLOWS_DB", wf_db)

    ar._init_db()

    # Seed minimal tables so metric collection doesn't fail
    for path, ddl in [
        (main_db, """
            CREATE TABLE IF NOT EXISTS emails (id INTEGER PRIMARY KEY, is_read INTEGER DEFAULT 0, category TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS threat_lookalike_alerts (id INTEGER PRIMARY KEY, status TEXT, created_at TEXT);
        """),
        (wf_db, """
            CREATE TABLE IF NOT EXISTS workflows (id TEXT PRIMARY KEY, is_active INTEGER DEFAULT 1);
            CREATE TABLE IF NOT EXISTS workflow_executions (id TEXT PRIMARY KEY, workflow_id TEXT, status TEXT, created_at TEXT);
        """),
    ]:
        con = sqlite3.connect(path)
        con.executescript(ddl)
        con.commit()
        con.close()

    return db_path


def _client(tmp_path, monkeypatch):
    from backend.api import alert_rules as ar
    from backend.auth.local_auth import require_local_auth

    _setup_dbs(tmp_path, monkeypatch)

    # Patch event bus emit so rule breaches don't try to start the event loop
    async def _noop(*a, **kw):
        return "fake-id"
    monkeypatch.setattr("backend.api.event_bus.emit", _noop)

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(ar.router, prefix="/api/v1")
    return TestClient(app)


# ── _eval_condition unit tests ────────────────────────────────────────────────

def test_eval_condition_gt():
    from backend.api.alert_rules import _eval_condition
    assert _eval_condition(11.0, ">", 10.0) is True
    assert _eval_condition(10.0, ">", 10.0) is False


def test_eval_condition_lt():
    from backend.api.alert_rules import _eval_condition
    assert _eval_condition(5.0, "<", 10.0) is True
    assert _eval_condition(10.0, "<", 10.0) is False


def test_eval_condition_gte():
    from backend.api.alert_rules import _eval_condition
    assert _eval_condition(10.0, ">=", 10.0) is True
    assert _eval_condition(11.0, ">=", 10.0) is True
    assert _eval_condition(9.0,  ">=", 10.0) is False


def test_eval_condition_lte():
    from backend.api.alert_rules import _eval_condition
    assert _eval_condition(10.0, "<=", 10.0) is True
    assert _eval_condition(9.0,  "<=", 10.0) is True
    assert _eval_condition(11.0, "<=", 10.0) is False


def test_eval_condition_eq():
    from backend.api.alert_rules import _eval_condition
    assert _eval_condition(10.0, "==", 10.0) is True
    assert _eval_condition(10.1, "==", 10.0) is False


# ── CRUD REST tests ───────────────────────────────────────────────────────────

def test_list_rules_empty(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/alert-rules")
    assert resp.status_code == 200
    data = resp.json()
    assert data["rules"] == []
    assert data["count"] == 0


def test_create_rule(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/alert-rules", json={
        "name":         "High Threat Alert",
        "metric":       "active_threats",
        "operator":     ">",
        "threshold":    10.0,
        "severity":     "high",
        "cooldown_min": 30,
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "High Threat Alert"
    assert data["metric"] == "active_threats"
    assert data["operator"] == ">"
    assert data["threshold"] == 10.0
    assert data["is_active"] is True


def test_create_rule_invalid_metric(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/alert-rules", json={
        "name": "Bad", "metric": "not_a_metric", "operator": ">", "threshold": 0,
    })
    assert resp.status_code == 400


def test_create_rule_invalid_operator(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/alert-rules", json={
        "name": "Bad", "metric": "active_threats", "operator": "!=", "threshold": 0,
    })
    assert resp.status_code == 400


def test_get_rule(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/alert-rules", json={
        "name": "GetMe", "metric": "health_score", "operator": "<", "threshold": 50.0,
    }).json()
    resp = client.get(f"/api/v1/alert-rules/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_rule_not_found(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/alert-rules/no-such-id")
    assert resp.status_code == 404


def test_update_rule(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/alert-rules", json={
        "name": "Before", "metric": "active_threats", "operator": ">", "threshold": 5.0,
    }).json()
    resp = client.patch(f"/api/v1/alert-rules/{created['id']}", json={"name": "After", "threshold": 15.0})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "After"
    assert data["threshold"] == 15.0


def test_disable_rule(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/alert-rules", json={
        "name": "Disable", "metric": "running_agents", "operator": "<", "threshold": 3.0,
    }).json()
    resp = client.patch(f"/api/v1/alert-rules/{created['id']}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_delete_rule(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/alert-rules", json={
        "name": "ToDel", "metric": "scam_last_24h", "operator": ">", "threshold": 5.0,
    }).json()
    resp = client.delete(f"/api/v1/alert-rules/{created['id']}")
    assert resp.status_code == 204
    assert client.get("/api/v1/alert-rules").json()["count"] == 0


def test_list_metrics_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/alert-rules/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "metrics" in data
    ids = {m["id"] for m in data["metrics"]}
    assert "active_threats" in ids
    assert "health_score" in ids


def test_status_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/alert-rules/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "metrics" in data
    assert "rules" in data
    assert "run_count" in data


def test_status_includes_rule_evaluation(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/v1/alert-rules", json={
        "name": "EvalTest", "metric": "active_threats", "operator": ">", "threshold": 999.0,
    })
    resp = client.get("/api/v1/alert-rules/status")
    assert resp.status_code == 200
    rules = resp.json()["rules"]
    assert len(rules) == 1
    assert rules[0]["rule_name"] == "EvalTest"
    assert rules[0]["breached"] is False  # threshold 999, current=0


# ── Evaluator unit tests ──────────────────────────────────────────────────────

def test_ensure_alert_rules_running_honors_runtime_service_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_ALERT_RULES", "false")
    from backend.api import alert_rules as ar
    _setup_dbs(tmp_path, monkeypatch)

    class FakeEngine:
        def __init__(self):
            self.started = False

        async def start(self):
            self.started = True

    fake = FakeEngine()
    monkeypatch.setattr(ar, "_engine", fake)

    _run(ar.ensure_alert_rules_running())

    assert fake.started is False


def test_tick_fires_breach(tmp_path, monkeypatch):
    from backend.api import alert_rules as ar

    _setup_dbs(tmp_path, monkeypatch)

    # Seed 15 active threats so active_threats=15 > 10 breaches
    con = sqlite3.connect(str(tmp_path / "main.db"))
    now = datetime.now(timezone.utc).isoformat()
    for i in range(15):
        con.execute("INSERT INTO threat_lookalike_alerts (status, created_at) VALUES ('active', ?)", (now,))
    con.commit()
    con.close()

    # Create rule
    rule_con = sqlite3.connect(str(tmp_path / "alert_rules.db"))
    now = datetime.now(timezone.utc).isoformat()
    rule_con.execute(
        """INSERT INTO alert_rules (id, name, metric, operator, threshold, severity, cooldown_min, is_active, created_at, updated_at)
           VALUES ('r1','HighThreats','active_threats','>',10,'high',30,1,?,?)""",
        (now, now),
    )
    rule_con.commit()
    rule_con.close()

    breached = []

    async def _fake_fire(rule_id, rule_name, metric, operator, threshold, value, severity):
        breached.append(rule_id)

    async def _scenario():
        engine = ar.AlertRulesEngine()
        monkeypatch.setattr(engine, "_fire_breach", _fake_fire)
        await engine._tick()

    _run(_scenario())
    assert "r1" in breached


def test_tick_respects_cooldown(tmp_path, monkeypatch):
    from backend.api import alert_rules as ar

    _setup_dbs(tmp_path, monkeypatch)

    con = sqlite3.connect(str(tmp_path / "main.db"))
    for i in range(15):
        con.execute("INSERT INTO threat_lookalike_alerts (status, created_at) VALUES ('active', ?)",
                    (datetime.now(timezone.utc).isoformat(),))
    con.commit()
    con.close()

    now = datetime.now(timezone.utc).isoformat()
    recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()

    rule_con = sqlite3.connect(str(tmp_path / "alert_rules.db"))
    rule_con.execute(
        """INSERT INTO alert_rules (id, name, metric, operator, threshold, severity, cooldown_min, is_active, created_at, updated_at)
           VALUES ('r2','CD','active_threats','>',10,'high',30,1,?,?)""",
        (now, now),
    )
    # Mark as breached 5 minutes ago — within the 30-minute cooldown
    rule_con.execute(
        "INSERT INTO alert_rule_state (rule_id, last_breach, breach_count) VALUES ('r2', ?, 1)",
        (recent,),
    )
    rule_con.commit()
    rule_con.close()

    breached = []

    async def _fake_fire(*a, **kw):
        breached.append(True)

    async def _scenario():
        engine = ar.AlertRulesEngine()
        monkeypatch.setattr(engine, "_fire_breach", _fake_fire)
        await engine._tick()

    _run(_scenario())
    assert len(breached) == 0   # suppressed by cooldown
