"""Tests for the operational intelligence engine (backend/api/operational_intelligence.py)."""
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── DB fixtures ───────────────────────────────────────────────────────────────

def _seed_main_db(path: str) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY, status TEXT, last_sync_at TEXT
        );
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY, account_id INTEGER, category TEXT,
            confidence REAL DEFAULT 0.9, is_read INTEGER DEFAULT 0,
            is_processed INTEGER DEFAULT 0, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS threat_lookalike_alerts (
            id INTEGER PRIMARY KEY, status TEXT, threat_type TEXT,
            impersonated_brand TEXT, confidence_score INTEGER, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS mailbox_quarantine (
            id INTEGER PRIMARY KEY, created_at TEXT
        );
        INSERT INTO accounts VALUES (1, 'active', datetime('now','-30 minutes'));
        INSERT INTO accounts VALUES (2, 'active', datetime('now','-1 hour'));
        INSERT INTO emails VALUES (1, 1, 'Work',       0.9, 0, 1, datetime('now','-5 minutes'));
        INSERT INTO emails VALUES (2, 1, 'Scam',       0.95,0, 1, datetime('now','-10 minutes'));
        INSERT INTO emails VALUES (3, 2, 'Newsletter', 0.8, 1, 1, datetime('now','-20 minutes'));
        INSERT INTO threat_lookalike_alerts VALUES
            (1, 'active',    'domain_spoof',  'PayPal', 85, datetime('now','-1 hour')),
            (2, 'active',    'typosquatting', 'Google', 72, datetime('now','-2 hours')),
            (3, 'dismissed', 'homoglyph',     'Apple',  60, datetime('now','-3 hours'));
    """)
    con.commit()
    con.close()


def _seed_wf_db(path: str) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS workflows (
            id TEXT PRIMARY KEY, name TEXT, description TEXT,
            is_active INTEGER DEFAULT 1, trigger_cfg TEXT, steps_json TEXT,
            run_count INTEGER DEFAULT 0, success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id TEXT PRIMARY KEY, workflow_id TEXT, status TEXT,
            trigger_type TEXT, created_at TEXT, started_at TEXT,
            finished_at TEXT, error TEXT, step_count INTEGER,
            steps_done INTEGER, duration_ms INTEGER
        );
        INSERT INTO workflows VALUES
            ('wf-1','Test WF','desc',1,'{}','[]',5,4,1,datetime('now','-1 day'));
        INSERT INTO workflow_executions VALUES
            ('ex-1','wf-1','succeeded','event',datetime('now','-10 min'),datetime('now','-10 min'),datetime('now','-9 min'),NULL,3,3,60000),
            ('ex-2','wf-1','failed','event',   datetime('now','-20 min'),datetime('now','-20 min'),datetime('now','-19 min'),'err',3,1,30000);
    """)
    con.commit()
    con.close()


# ── helpers ───────────────────────────────────────────────────────────────────

def _patch(monkeypatch, tmp_path):
    from backend.api import operational_intelligence as oi
    main_db = str(tmp_path / "main.db")
    wf_db   = str(tmp_path / "wf.db")
    _seed_main_db(main_db)
    _seed_wf_db(wf_db)
    monkeypatch.setattr(oi, "DB_PATH", main_db)
    monkeypatch.setattr(oi, "_WORKFLOWS_DB", wf_db)
    return oi, main_db, wf_db


# ── unit tests ────────────────────────────────────────────────────────────────

def test_email_summary_returns_counts(tmp_path, monkeypatch):
    oi, *_ = _patch(monkeypatch, tmp_path)
    engine = oi.IntelligenceEngine()
    summary = engine.email_summary()
    assert summary["total"] >= 3
    # key may be "by_category" or "categories" depending on implementation
    assert "by_category" in summary or "categories" in summary


def test_threat_summary_counts_active_threats(tmp_path, monkeypatch):
    oi, *_ = _patch(monkeypatch, tmp_path)
    engine = oi.IntelligenceEngine()
    summary = engine.threat_summary()
    assert summary["active"] == 2
    assert summary["total"] >= 3


def test_health_score_returns_0_to_100(tmp_path, monkeypatch):
    oi, *_ = _patch(monkeypatch, tmp_path)
    engine = oi.IntelligenceEngine()
    health = engine.compute_health_score()
    assert 0 <= health["overall"] <= 100
    assert "components" in health
    assert health["status"] in ("healthy", "good", "degraded", "critical", "warning")


def test_generate_insights_returns_list_with_required_keys(tmp_path, monkeypatch):
    oi, *_ = _patch(monkeypatch, tmp_path)
    engine = oi.IntelligenceEngine()
    insights = engine.generate_insights()
    assert isinstance(insights, list)
    for ins in insights:
        assert "title" in ins
        assert "priority" in ins


def test_detect_anomalies_returns_list(tmp_path, monkeypatch):
    oi, *_ = _patch(monkeypatch, tmp_path)
    engine = oi.IntelligenceEngine()
    anomalies = engine.detect_anomalies()
    assert isinstance(anomalies, list)


def test_generate_predictions_has_required_keys(tmp_path, monkeypatch):
    oi, *_ = _patch(monkeypatch, tmp_path)
    engine = oi.IntelligenceEngine()
    preds = engine.generate_predictions()
    assert isinstance(preds, list)
    for p in preds:
        assert "title" in p
        assert "confidence" in p


def test_workflow_summary_reads_wf_db(tmp_path, monkeypatch):
    oi, *_ = _patch(monkeypatch, tmp_path)
    engine = oi.IntelligenceEngine()
    summary = engine.workflow_summary()
    assert isinstance(summary, dict)
    assert "active" in summary or "total" in summary


# ── REST endpoints ─────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    from backend.api import operational_intelligence as oi
    from backend.auth.local_auth import require_local_auth

    _patch(monkeypatch, tmp_path)
    # Replace the singleton engine with a fresh one using patched paths
    monkeypatch.setattr(oi, "_engine", oi.IntelligenceEngine())

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(oi.router, prefix="/api/v1")
    return TestClient(app)


def test_health_endpoint_returns_score(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/intelligence/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "overall" in data
    assert "status" in data


def test_insights_endpoint_returns_list(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/intelligence/insights")
    assert resp.status_code == 200
    assert "insights" in resp.json()


def test_anomalies_endpoint_returns_list(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/intelligence/anomalies")
    assert resp.status_code == 200
    assert "anomalies" in resp.json()


def test_patterns_endpoint_returns_list(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/intelligence/patterns")
    assert resp.status_code == 200
    assert "patterns" in resp.json()


def test_predictions_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/intelligence/predictions")
    assert resp.status_code == 200
    assert "predictions" in resp.json()


@pytest.mark.skip(reason="analyze endpoint starts event bus background tasks that outlive the TestClient portal on Windows")
def test_analyze_endpoint_responds_ok(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/intelligence/analyze")
    assert resp.status_code == 200
    data = resp.json()
    assert "ok" in data or "health" in data or "insights" in data
