"""Tests for backend/api/metric_snapshots.py"""
import asyncio
import sqlite3
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _setup(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = str(tmp_path / "metric_snapshots.db")
    monkeypatch.setattr(ms, "_DB_PATH", db_path)
    ms._init_db()
    return db_path


def _client(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    from backend.auth.local_auth import require_local_auth
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(ms.router, prefix="/api/v1")
    return TestClient(app)


def _seed_snapshots(db_path: str, metric: str, values: list, hours_ago_start: int = 24):
    con = sqlite3.connect(db_path)
    for i, v in enumerate(values):
        ts = (datetime.now(timezone.utc) - timedelta(hours=hours_ago_start - i)).isoformat()
        con.execute(
            "INSERT INTO metric_snapshots (metric, value, recorded_at) VALUES (?,?,?)",
            (metric, v, ts),
        )
    con.commit()
    con.close()


# ── _init_db ──────────────────────────────────────────────────────────────────

def test_init_creates_table(tmp_path, monkeypatch):
    db_path = _setup(tmp_path, monkeypatch)
    con = sqlite3.connect(db_path)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    con.close()
    assert "metric_snapshots" in tables


def test_init_prunes_old_records(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = str(tmp_path / "metric_snapshots.db")
    monkeypatch.setattr(ms, "_DB_PATH", db_path)
    ms._init_db()

    # Insert a record older than 30 days
    old_ts = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO metric_snapshots (metric, value, recorded_at) VALUES (?,?,?)",
                ("health_score", 99.0, old_ts))
    con.commit()
    con.close()

    # Re-init should prune it
    ms._init_db()
    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0]
    con.close()
    assert count == 0


# ── _write_snapshot ───────────────────────────────────────────────────────────

def test_write_snapshot_inserts_known_metrics(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = _setup(tmp_path, monkeypatch)

    ms._write_snapshot({"active_threats": 5.0, "health_score": 88.0, "unknown_metric": 99.0})

    con = sqlite3.connect(db_path)
    rows = con.execute("SELECT metric, value FROM metric_snapshots ORDER BY metric").fetchall()
    con.close()
    metrics = {r[0]: r[1] for r in rows}
    assert "active_threats" in metrics
    assert "health_score" in metrics
    assert "unknown_metric" not in metrics


def test_write_snapshot_trims_to_720(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = _setup(tmp_path, monkeypatch)

    # Seed 725 records for one metric
    con = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc)
    for i in range(725):
        ts = (now - timedelta(hours=i)).isoformat()
        con.execute("INSERT INTO metric_snapshots (metric, value, recorded_at) VALUES (?,?,?)",
                    ("active_threats", float(i), ts))
    con.commit()
    con.close()

    # Write a new snapshot — this should trigger the per-metric trim
    ms._write_snapshot({"active_threats": 0.0})

    con = sqlite3.connect(db_path)
    count = con.execute(
        "SELECT COUNT(*) FROM metric_snapshots WHERE metric='active_threats'"
    ).fetchone()[0]
    con.close()
    assert count <= 720


# ── _query_history ────────────────────────────────────────────────────────────

def test_query_history_returns_data(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = _setup(tmp_path, monkeypatch)
    _seed_snapshots(db_path, "health_score", [70.0, 75.0, 80.0], hours_ago_start=3)

    rows = ms._query_history("health_score", hours=24)
    assert len(rows) == 3
    assert all("ts" in r and "value" in r for r in rows)


def test_query_history_respects_hours_window(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = _setup(tmp_path, monkeypatch)

    # 3 recent + 3 old (beyond 2-hour window)
    _seed_snapshots(db_path, "active_threats", [1.0, 2.0, 3.0], hours_ago_start=1)
    _seed_snapshots(db_path, "active_threats", [9.0, 9.0, 9.0], hours_ago_start=100)

    rows = ms._query_history("active_threats", hours=2)
    assert len(rows) == 3
    assert all(r["value"] <= 3.0 for r in rows)


def test_query_history_empty_for_unknown_metric(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    _setup(tmp_path, monkeypatch)
    rows = ms._query_history("nonexistent", hours=24)
    assert rows == []


# ── _sparkline_data ───────────────────────────────────────────────────────────

def test_sparkline_data_returns_all_metrics(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = _setup(tmp_path, monkeypatch)
    _seed_snapshots(db_path, "health_score", [85.0, 90.0], hours_ago_start=2)

    data = ms._sparkline_data(hours=24)
    assert set(data.keys()) == set(ms._METRICS)
    assert len(data["health_score"]) == 2
    assert data["active_threats"] == []


# ── MetricRecorder ────────────────────────────────────────────────────────────

def test_recorder_status(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    _setup(tmp_path, monkeypatch)
    recorder = ms.MetricRecorder()
    status = recorder.status()
    assert status["running"] is False
    assert status["run_count"] == 0
    assert status["last_record"] is None
    assert status["interval_s"] == 3600


def test_recorder_record_writes_snapshot(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = _setup(tmp_path, monkeypatch)

    # Patch _take_snapshot to return known values
    monkeypatch.setattr(ms, "_take_snapshot", lambda: {"active_threats": 7.0, "health_score": 91.0})

    recorder = ms.MetricRecorder()
    _run(recorder._record())

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0]
    con.close()
    assert count == 2
    assert recorder.status()["run_count"] == 1
    assert recorder.status()["last_record"] is not None


def test_recorder_no_write_on_empty_metrics(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = _setup(tmp_path, monkeypatch)

    monkeypatch.setattr(ms, "_take_snapshot", lambda: {})

    recorder = ms.MetricRecorder()
    _run(recorder._record())

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM metric_snapshots").fetchone()[0]
    con.close()
    assert count == 0
    assert recorder.status()["run_count"] == 0


# ── REST endpoints ────────────────────────────────────────────────────────────

def test_history_endpoint_empty(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/metric-snapshots/history")
    assert resp.status_code == 200
    data = resp.json()
    assert "history" in data
    assert "hours" in data
    # All metrics present, all empty
    from backend.api.metric_snapshots import _METRICS
    for m in _METRICS:
        assert data["history"].get(m) == []


def test_history_endpoint_single_metric(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = _setup(tmp_path, monkeypatch)
    _seed_snapshots(db_path, "scam_last_24h", [3.0, 5.0, 2.0], hours_ago_start=3)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(ms.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/metric-snapshots/history?metric=scam_last_24h&hours=24")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["history"]["scam_last_24h"]) == 3


def test_history_endpoint_ignores_unknown_metric(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/metric-snapshots/history?metric=fake_metric")
    assert resp.status_code == 200
    assert resp.json()["history"] == {}


def test_sparklines_endpoint(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    db_path = _setup(tmp_path, monkeypatch)
    _seed_snapshots(db_path, "health_score", [80.0, 85.0, 90.0], hours_ago_start=3)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(ms.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/metric-snapshots/sparklines")
    assert resp.status_code == 200
    data = resp.json()
    assert "sparklines" in data
    hs = data["sparklines"]["health_score"]
    assert hs["count"] == 3
    assert hs["last"] == 90.0
    assert hs["min"] == 80.0
    assert hs["max"] == 90.0
    assert len(hs["values"]) == 3


def test_sparklines_endpoint_empty_metric(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/metric-snapshots/sparklines")
    assert resp.status_code == 200
    data = resp.json()
    at = data["sparklines"]["active_threats"]
    assert at["count"] == 0
    assert at["values"] == []


def test_status_endpoint(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/metric-snapshots/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "run_count" in data
    assert "interval_s" in data
    assert data["interval_s"] == 3600


def test_force_record_endpoint(tmp_path, monkeypatch):
    from backend.api import metric_snapshots as ms
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(ms, "_take_snapshot", lambda: {"active_threats": 2.0})

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(ms.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post("/api/v1/metric-snapshots/record")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
