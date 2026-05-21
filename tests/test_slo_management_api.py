"""Tests for the SLO management API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.slo_management import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_SLO = {
    "name": "API Availability",
    "service": "api-gateway",
    "target_pct": 99.9,
    "time_window": "rolling_30d",
}

def test_list_slos_returns_structure(client):
    resp = client.get("/api/v1/slos")
    assert resp.status_code == 200
    assert "slos" in resp.json()

def test_create_slo_returns_id(client):
    resp = client.post("/api/v1/slos", json=_NEW_SLO)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_slo_by_id(client):
    slo_id = client.post("/api/v1/slos", json=_NEW_SLO).json()["id"]
    resp = client.get(f"/api/v1/slos/{slo_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == slo_id

def test_patch_slo(client):
    slo_id = client.post("/api/v1/slos", json=_NEW_SLO).json()["id"]
    resp = client.patch(f"/api/v1/slos/{slo_id}", json={"target_pct": 99.5})
    assert resp.status_code == 200

def test_delete_slo(client):
    slo_id = client.post("/api/v1/slos", json=_NEW_SLO).json()["id"]
    resp = client.delete(f"/api/v1/slos/{slo_id}")
    assert resp.status_code in (200, 204)

def test_slo_stats(client):
    resp = client.get("/api/v1/slos/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_slo_measurements(client):
    slo_id = client.post("/api/v1/slos", json=_NEW_SLO).json()["id"]
    resp = client.get(f"/api/v1/slos/{slo_id}/measurements")
    assert resp.status_code == 200

def test_add_measurement(client):
    slo_id = client.post("/api/v1/slos", json=_NEW_SLO).json()["id"]
    # MeasurementCreate uses "actual_pct" not "value_pct"
    resp = client.post(f"/api/v1/slos/{slo_id}/measurements", json={"actual_pct": 99.95})
    assert resp.status_code in (200, 201)
