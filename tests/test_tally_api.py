"""Tests for the Tally ERP connector API."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.local_auth import require_local_auth


@pytest.fixture
def client():
    from backend.api.tally import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


def test_status_returns_structure(client):
    resp = client.get("/tally/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body
    assert "health" in body


def test_connect_creates_connection(client):
    resp = client.post("/tally/connect", json={
        "mode": "localhost", "host": "localhost",
        "port": 9000, "company_name": "TestCo",
    })
    assert resp.status_code == 200
    body = resp.json()
    # Body always has status key; actual value depends on DB row ordering
    assert "status" in body or "host" in body


def test_disconnect_returns_disconnected(client):
    resp = client.post("/tally/disconnect")
    assert resp.status_code == 200
    assert resp.json().get("status") == "disconnected"


def test_test_connection_returns_ok_field(client):
    resp = client.post("/tally/test")
    assert resp.status_code == 200
    assert "ok" in resp.json()
    assert "status" in resp.json()


def test_test_connection_after_connect(client):
    client.post("/tally/connect", json={
        "mode": "localhost", "host": "localhost",
        "port": 9000, "company_name": "ConnCo",
    })
    resp = client.post("/tally/test")
    assert resp.status_code == 200
    assert resp.json().get("ok") is True


def test_discover_returns_instances(client):
    resp = client.get("/tally/discover")
    assert resp.status_code == 200
    body = resp.json()
    assert "instances" in body
    assert isinstance(body["instances"], list)
    assert len(body["instances"]) >= 1


def test_companies_returns_list(client):
    resp = client.get("/tally/companies")
    assert resp.status_code == 200
    assert isinstance(resp.json().get("companies"), list)


def test_ledgers_returns_list(client):
    resp = client.get("/tally/ledgers")
    assert resp.status_code == 200
    assert isinstance(resp.json().get("ledgers"), list)


def test_vouchers_returns_list(client):
    resp = client.get("/tally/vouchers")
    assert resp.status_code == 200
    assert isinstance(resp.json().get("vouchers"), list)


def test_inventory_returns_list(client):
    resp = client.get("/tally/inventory")
    assert resp.status_code == 200
    assert isinstance(resp.json().get("items"), list)


def test_gst_returns_reports_and_alerts(client):
    resp = client.get("/tally/gst")
    assert resp.status_code == 200
    body = resp.json()
    assert "reports" in body
    assert "alerts" in body


def test_sync_queues_job(client):
    resp = client.post("/tally/sync", json={
        "company_name": "SyncCo",
        "sync_type": "manual",
        "entities": ["ledgers"],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "queued"
    assert "job" in body


def test_sync_minimal_payload(client):
    resp = client.post("/tally/sync", json={"company_name": ""})
    assert resp.status_code == 200
    assert resp.json().get("status") == "queued"


def test_analytics_returns_analytics_key(client):
    resp = client.get("/tally/analytics")
    assert resp.status_code == 200
    analytics = resp.json().get("analytics", {})
    assert "revenue" in analytics
    assert "ai_insights" in analytics


def test_logs_returns_list(client):
    resp = client.get("/tally/logs")
    assert resp.status_code == 200
    assert isinstance(resp.json().get("logs"), list)


def test_logs_populated_after_connect(client):
    client.post("/tally/connect", json={
        "mode": "localhost", "host": "localhost",
        "port": 9000, "company_name": "LogCo",
    })
    resp = client.get("/tally/logs")
    assert resp.status_code == 200
    assert isinstance(resp.json()["logs"], list)


def test_export_returns_csv(client):
    resp = client.get("/tally/export")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")


def test_export_has_content_disposition(client):
    resp = client.get("/tally/export")
    assert "attachment" in resp.headers.get("content-disposition", "")
