"""Tests for the service catalog API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.service_catalog import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_SVC = {"name": "Payment API", "status": "operational", "tier": "tier1", "owner": "payments-team"}

def test_list_services_returns_structure(client):
    resp = client.get("/api/v1/services")
    assert resp.status_code == 200
    body = resp.json()
    assert "services" in body or "items" in body or isinstance(body, dict)

def test_create_service_returns_id(client):
    resp = client.post("/api/v1/services", json=_NEW_SVC)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_service_by_id(client):
    svc_id = client.post("/api/v1/services", json=_NEW_SVC).json()["id"]
    resp = client.get(f"/api/v1/services/{svc_id}")
    assert resp.status_code == 200

def test_patch_service(client):
    svc_id = client.post("/api/v1/services", json=_NEW_SVC).json()["id"]
    resp = client.patch(f"/api/v1/services/{svc_id}", json={"status": "degraded"})
    assert resp.status_code == 200

def test_delete_service(client):
    svc_id = client.post("/api/v1/services", json=_NEW_SVC).json()["id"]
    resp = client.delete(f"/api/v1/services/{svc_id}")
    assert resp.status_code in (200, 204)

def test_service_stats(client):
    resp = client.get("/api/v1/services/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
