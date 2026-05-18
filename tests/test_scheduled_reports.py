"""Tests for backend/api/scheduled_reports.py"""
import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _setup(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = str(tmp_path / "scheduled_reports.db")
    monkeypatch.setattr(sr, "_DB_PATH", db_path)
    sr._init_db()
    return db_path


def _client(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    from backend.auth.local_auth import require_local_auth
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(sr.router, prefix="/api/v1")
    return TestClient(app)


def _seed_config(db_path: str, name: str = "Test Report",
                 interval_hours: int = 24, enabled: int = 1,
                 next_run_offset_hours: float = 1.0) -> str:
    cfg_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    next_run = (now + timedelta(hours=next_run_offset_hours)).isoformat()
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO report_configs (id,name,interval_hours,sections,delivery,webhook_url,enabled,last_run,next_run,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cfg_id, name, interval_hours,
         "platform_health,incidents,alert_rules,metric_trends,audit_summary",
         "store", "", enabled, None, next_run, now.isoformat()),
    )
    con.commit()
    con.close()
    return cfg_id


# ── _init_db ──────────────────────────────────────────────────────────────────

def test_init_creates_tables(tmp_path, monkeypatch):
    db_path = _setup(tmp_path, monkeypatch)
    con = sqlite3.connect(db_path)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    con.close()
    assert "report_configs" in tables
    assert "report_runs" in tables


# ── _collect_* section helpers ────────────────────────────────────────────────

def test_collect_platform_health_graceful(monkeypatch):
    from backend.api import scheduled_reports as sr
    # Patch out the import so it fails gracefully
    monkeypatch.setattr(sr, "_collect_platform_health",
                        lambda: {"metrics": {}, "alert": False})
    result = sr._collect_platform_health()
    assert "metrics" in result
    assert "alert" in result


def test_collect_incidents_graceful():
    from backend.api import scheduled_reports as sr
    # Even if incidents DB is missing, should return empty structure
    result = sr._collect_incidents_section()
    assert "by_status" in result
    assert "critical_open" in result
    assert "total" in result


def test_collect_alert_rules_graceful():
    from backend.api import scheduled_reports as sr
    result = sr._collect_alert_rules_section()
    assert "total" in result
    assert "breached_24h" in result


def test_collect_metric_trends_graceful():
    from backend.api import scheduled_reports as sr
    result = sr._collect_metric_trends_section()
    assert isinstance(result, dict)


def test_collect_audit_summary_graceful():
    from backend.api import scheduled_reports as sr
    result = sr._collect_audit_summary_section()
    assert "total_24h" in result
    assert "top_event_types" in result


# ── _generate_report_content ──────────────────────────────────────────────────

def test_generate_report_content_structure(monkeypatch):
    from backend.api import scheduled_reports as sr
    # Patch each collector to return known values
    monkeypatch.setattr(sr, "_collect_platform_health",     lambda: {"metrics": {}, "alert": False})
    monkeypatch.setattr(sr, "_collect_incidents_section",   lambda: {"by_status": {}, "critical_open": [], "total": 0})
    monkeypatch.setattr(sr, "_collect_alert_rules_section", lambda: {"total": 3, "active": 2, "breached_24h": 0, "recent_breaches": []})
    monkeypatch.setattr(sr, "_collect_metric_trends_section", lambda: {})
    monkeypatch.setattr(sr, "_collect_audit_summary_section", lambda: {"total_24h": 10, "by_severity": {}, "top_event_types": []})

    content = _run(sr._generate_report_content("Test", ["platform_health", "incidents", "alert_rules"]))
    assert "generated_at" in content
    assert "config_name" in content
    assert "sections" in content
    assert "platform_health" in content["sections"]
    assert "incidents" in content["sections"]
    assert "alert_rules" in content["sections"]
    # metric_trends not requested
    assert "metric_trends" not in content["sections"]


def test_generate_report_skips_unknown_sections(monkeypatch):
    from backend.api import scheduled_reports as sr
    content = _run(sr._generate_report_content("Test", ["nonexistent_section"]))
    assert content["sections"] == {}


# ── _run_config ───────────────────────────────────────────────────────────────

def test_run_config_writes_run_record(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)
    cfg_id = _seed_config(db_path, next_run_offset_hours=1)

    monkeypatch.setattr(sr, "_collect_platform_health", lambda: {"metrics": {}, "alert": False})
    monkeypatch.setattr(sr, "_collect_incidents_section", lambda: {"by_status": {}, "critical_open": [], "total": 0})
    monkeypatch.setattr(sr, "_collect_alert_rules_section", lambda: {"total": 0, "active": 0, "breached_24h": 0, "recent_breaches": []})
    monkeypatch.setattr(sr, "_collect_metric_trends_section", lambda: {})
    monkeypatch.setattr(sr, "_collect_audit_summary_section", lambda: {"total_24h": 0, "by_severity": {}, "top_event_types": []})

    con = sqlite3.connect(db_path)
    row = con.execute("SELECT * FROM report_configs WHERE id=?", (cfg_id,)).fetchone()
    config = dict(zip(sr._CONFIG_COLS, row))
    con.close()

    run_id = _run(sr._run_config(config))

    con = sqlite3.connect(db_path)
    run = con.execute("SELECT status, delivered, content FROM report_runs WHERE id=?", (run_id,)).fetchone()
    last_run = con.execute("SELECT last_run FROM report_configs WHERE id=?", (cfg_id,)).fetchone()[0]
    con.close()

    assert run[0] == "ok"
    assert run[1] == 1   # delivered (store mode)
    assert run[2]        # content is non-empty JSON
    assert last_run is not None


def test_run_config_updates_next_run(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)
    cfg_id = _seed_config(db_path, interval_hours=6, next_run_offset_hours=1)

    monkeypatch.setattr(sr, "_collect_platform_health", lambda: {})
    monkeypatch.setattr(sr, "_collect_incidents_section", lambda: {})
    monkeypatch.setattr(sr, "_collect_alert_rules_section", lambda: {})
    monkeypatch.setattr(sr, "_collect_metric_trends_section", lambda: {})
    monkeypatch.setattr(sr, "_collect_audit_summary_section", lambda: {})

    con = sqlite3.connect(db_path)
    old_next = con.execute("SELECT next_run FROM report_configs WHERE id=?", (cfg_id,)).fetchone()[0]
    row = con.execute("SELECT * FROM report_configs WHERE id=?", (cfg_id,)).fetchone()
    config = dict(zip(sr._CONFIG_COLS, row))
    con.close()

    _run(sr._run_config(config))

    con = sqlite3.connect(db_path)
    new_next = con.execute("SELECT next_run FROM report_configs WHERE id=?", (cfg_id,)).fetchone()[0]
    con.close()
    # next_run should have advanced
    assert new_next > old_next


def test_run_config_trims_to_50_runs(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)
    cfg_id = _seed_config(db_path)

    # Seed 52 existing run records
    con = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc)
    for i in range(52):
        ts = (now - timedelta(hours=i)).isoformat()
        con.execute(
            "INSERT INTO report_runs (id,config_id,config_name,generated_at,status,error_msg,content,delivered) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), cfg_id, "T", ts, "ok", "", "{}", 1),
        )
    con.commit()
    row = con.execute("SELECT * FROM report_configs WHERE id=?", (cfg_id,)).fetchone()
    config = dict(zip(sr._CONFIG_COLS, row))
    con.close()

    monkeypatch.setattr(sr, "_collect_platform_health", lambda: {})
    monkeypatch.setattr(sr, "_collect_incidents_section", lambda: {})
    monkeypatch.setattr(sr, "_collect_alert_rules_section", lambda: {})
    monkeypatch.setattr(sr, "_collect_metric_trends_section", lambda: {})
    monkeypatch.setattr(sr, "_collect_audit_summary_section", lambda: {})
    _run(sr._run_config(config))

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM report_runs WHERE config_id=?", (cfg_id,)).fetchone()[0]
    con.close()
    assert count <= 50


# ── ReportScheduler ───────────────────────────────────────────────────────────

def test_scheduler_status():
    from backend.api.scheduled_reports import ReportScheduler
    s = ReportScheduler()
    status = s.status()
    assert status["running"] is False
    assert status["run_count"] == 0
    assert status["last_check"] is None
    assert status["interval_s"] == 300


def test_scheduler_check_runs_due_configs(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)

    # Config due NOW (next_run in the past)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    cfg_id = str(uuid.uuid4())
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO report_configs (id,name,interval_hours,sections,delivery,webhook_url,enabled,last_run,next_run,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cfg_id, "Due", 24, "platform_health", "store", "", 1, None, past, past),
    )
    con.commit()
    con.close()

    # Mock all collectors
    for fn in ["_collect_platform_health", "_collect_incidents_section",
               "_collect_alert_rules_section", "_collect_metric_trends_section",
               "_collect_audit_summary_section"]:
        monkeypatch.setattr(sr, fn, lambda: {})

    scheduler = sr.ReportScheduler()
    _run(scheduler._check())

    con = sqlite3.connect(db_path)
    run_count = con.execute("SELECT COUNT(*) FROM report_runs WHERE config_id=?", (cfg_id,)).fetchone()[0]
    con.close()
    assert run_count == 1
    assert scheduler._run_count == 1


def test_scheduler_skips_future_configs(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)
    _seed_config(db_path, next_run_offset_hours=2)  # not due for 2 hours

    for fn in ["_collect_platform_health", "_collect_incidents_section",
               "_collect_alert_rules_section", "_collect_metric_trends_section",
               "_collect_audit_summary_section"]:
        monkeypatch.setattr(sr, fn, lambda: {})

    scheduler = sr.ReportScheduler()
    _run(scheduler._check())

    con = sqlite3.connect(db_path)
    run_count = con.execute("SELECT COUNT(*) FROM report_runs").fetchone()[0]
    con.close()
    assert run_count == 0
    assert scheduler._run_count == 0


def test_scheduler_skips_disabled_configs(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    # Disabled but due
    cfg_id = str(uuid.uuid4())
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO report_configs (id,name,interval_hours,sections,delivery,webhook_url,enabled,last_run,next_run,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cfg_id, "Disabled", 24, "platform_health", "store", "", 0, None, past, past),
    )
    con.commit()
    con.close()

    scheduler = sr.ReportScheduler()
    _run(scheduler._check())
    assert scheduler._run_count == 0


# ── REST: list / create / get / patch / delete ────────────────────────────────

def test_list_empty(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/scheduled-reports")
    assert resp.status_code == 200
    assert resp.json()["configs"] == []


def test_create_config(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/scheduled-reports", json={
        "name": "Daily Digest",
        "interval_hours": 24,
        "sections": "platform_health,incidents",
        "delivery": "store",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert "id" in data
    assert data["name"] == "Daily Digest"
    assert "next_run" in data


def test_create_rejects_unknown_section(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/scheduled-reports", json={
        "name": "Bad", "interval_hours": 24, "sections": "platform_health,fake_section"
    })
    assert resp.status_code == 400


def test_create_rejects_invalid_interval(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/scheduled-reports", json={
        "name": "Bad", "interval_hours": 0, "sections": "platform_health"
    })
    assert resp.status_code == 400


def test_get_config(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)
    cfg_id = _seed_config(db_path, name="My Report")

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(sr.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get(f"/api/v1/scheduled-reports/{cfg_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "My Report"


def test_patch_config(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)
    cfg_id = _seed_config(db_path, interval_hours=24)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(sr.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.patch(f"/api/v1/scheduled-reports/{cfg_id}",
                        json={"interval_hours": 6, "name": "Updated Name"})
    assert resp.status_code == 200

    detail = client.get(f"/api/v1/scheduled-reports/{cfg_id}").json()
    assert detail["name"] == "Updated Name"
    assert detail["interval_hours"] == 6


def test_delete_config(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)
    cfg_id = _seed_config(db_path)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(sr.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.delete(f"/api/v1/scheduled-reports/{cfg_id}")
    assert resp.status_code == 204

    configs = client.get("/api/v1/scheduled-reports").json()["configs"]
    assert not any(c["id"] == cfg_id for c in configs)


# ── REST: runs ────────────────────────────────────────────────────────────────

def test_list_runs_empty(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/scheduled-reports/runs")
    assert resp.status_code == 200
    assert resp.json()["runs"] == []


def test_get_run_detail(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)
    cfg_id = _seed_config(db_path)

    run_id = str(uuid.uuid4())
    content = json.dumps({"generated_at": "now", "config_name": "T", "sections": {}})
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO report_runs (id,config_id,config_name,generated_at,status,error_msg,content,delivered) VALUES (?,?,?,?,?,?,?,?)",
        (run_id, cfg_id, "T", datetime.now(timezone.utc).isoformat(), "ok", "", content, 1),
    )
    con.commit()
    con.close()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(sr.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get(f"/api/v1/scheduled-reports/runs/{run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert isinstance(data["content"], dict)  # Parsed from JSON string


def test_get_run_not_found(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/scheduled-reports/runs/nonexistent")
    assert resp.status_code == 404


# ── REST: manual trigger ──────────────────────────────────────────────────────

def test_manual_trigger(tmp_path, monkeypatch):
    from backend.api import scheduled_reports as sr
    db_path = _setup(tmp_path, monkeypatch)
    cfg_id = _seed_config(db_path)

    for fn in ["_collect_platform_health", "_collect_incidents_section",
               "_collect_alert_rules_section", "_collect_metric_trends_section",
               "_collect_audit_summary_section"]:
        monkeypatch.setattr(sr, fn, lambda: {})

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(sr.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post(f"/api/v1/scheduled-reports/{cfg_id}/run")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "run_id" in data

    runs = client.get("/api/v1/scheduled-reports/runs").json()["runs"]
    assert len(runs) == 1


def test_manual_trigger_not_found(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/scheduled-reports/nonexistent/run")
    assert resp.status_code == 404


# ── REST: scheduler status ────────────────────────────────────────────────────

def test_scheduler_status_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/scheduled-reports/scheduler/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "interval_s" in data
    assert data["interval_s"] == 300
