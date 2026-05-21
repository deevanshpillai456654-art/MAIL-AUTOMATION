"""Tests for the license management API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.license_management import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_LIC = {
    "name": "VSCode Pro", "product": "VSCode",
    "vendor": "Microsoft", "type": "subscription", "seats_total": 10,
}

def test_list_licenses_returns_structure(client):
    resp = client.get("/api/v1/licenses")
    assert resp.status_code == 200
    assert "licenses" in resp.json()

def test_create_license_returns_id(client):
    resp = client.post("/api/v1/licenses", json=_NEW_LIC)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_license_by_id(client):
    lic_id = client.post("/api/v1/licenses", json=_NEW_LIC).json()["id"]
    resp = client.get(f"/api/v1/licenses/{lic_id}")
    assert resp.status_code == 200

def test_patch_license(client):
    lic_id = client.post("/api/v1/licenses", json=_NEW_LIC).json()["id"]
    resp = client.patch(f"/api/v1/licenses/{lic_id}", json={"seats_total": 20})
    assert resp.status_code == 200

def test_delete_license(client):
    lic_id = client.post("/api/v1/licenses", json=_NEW_LIC).json()["id"]
    resp = client.delete(f"/api/v1/licenses/{lic_id}")
    assert resp.status_code in (200, 204)

def test_license_stats(client):
    resp = client.get("/api/v1/licenses/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_expiring_licenses(client):
    resp = client.get("/api/v1/licenses/expiring")
    assert resp.status_code == 200

def test_license_assignments(client):
    lic_id = client.post("/api/v1/licenses", json=_NEW_LIC).json()["id"]
    resp = client.get(f"/api/v1/licenses/{lic_id}/assignments")
    assert resp.status_code == 200

def test_license_renewals(client):
    lic_id = client.post("/api/v1/licenses", json=_NEW_LIC).json()["id"]
    resp = client.get(f"/api/v1/licenses/{lic_id}/renewals")
    assert resp.status_code == 200
