"""Tests for the vendor management API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.vendor_management import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_VENDOR = {"name": "ACME Corp", "category": "software"}

def test_list_vendors_returns_structure(client):
    resp = client.get("/api/v1/vendors")
    assert resp.status_code == 200
    body = resp.json()
    assert "vendors" in body and "total" in body

def test_create_vendor_returns_id(client):
    resp = client.post("/api/v1/vendors", json=_NEW_VENDOR)
    assert resp.status_code == 201
    assert "id" in resp.json()

def test_created_vendor_appears_in_list(client):
    client.post("/api/v1/vendors", json={"name": "ListVendor", "category": "cloud"})
    resp = client.get("/api/v1/vendors", params={"q": "ListVendor"})
    names = [v["name"] for v in resp.json()["vendors"]]
    assert "ListVendor" in names

def test_get_vendor_by_id(client):
    vid = client.post("/api/v1/vendors", json={"name": "GetTest", "category": "hardware"}).json()["id"]
    resp = client.get(f"/api/v1/vendors/{vid}")
    assert resp.status_code == 200
    assert resp.json()["id"] == vid

def test_patch_vendor(client):
    vid = client.post("/api/v1/vendors", json={"name": "PatchMe", "category": "consulting"}).json()["id"]
    resp = client.patch(f"/api/v1/vendors/{vid}", json={"notes": "updated"})
    assert resp.status_code == 200

def test_delete_vendor(client):
    vid = client.post("/api/v1/vendors", json={"name": "DelMe", "category": "support"}).json()["id"]
    resp = client.delete(f"/api/v1/vendors/{vid}")
    assert resp.status_code in (200, 204)

def test_vendor_stats_returns_dict(client):
    resp = client.get("/api/v1/vendors/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_expiring_vendors(client):
    resp = client.get("/api/v1/vendors/expiring")
    assert resp.status_code == 200

def test_vendor_contacts(client):
    vid = client.post("/api/v1/vendors", json={"name": "ContactVen", "category": "other"}).json()["id"]
    resp = client.get(f"/api/v1/vendors/{vid}/contacts")
    assert resp.status_code == 200

def test_create_vendor_invalid_category(client):
    resp = client.post("/api/v1/vendors", json={"name": "X", "category": "invalid_cat"})
    assert resp.status_code in (400, 422)
