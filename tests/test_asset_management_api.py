"""Tests for the asset management API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.asset_management import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_ASSET = {"name": "prod-db-01", "type": "database", "environment": "production"}

def test_list_assets_returns_structure(client):
    resp = client.get("/api/v1/assets")
    assert resp.status_code == 200
    assert "assets" in resp.json()

def test_create_asset_returns_id(client):
    resp = client.post("/api/v1/assets", json=_NEW_ASSET)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_asset_by_id(client):
    asset_id = client.post("/api/v1/assets", json=_NEW_ASSET).json()["id"]
    resp = client.get(f"/api/v1/assets/{asset_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == asset_id

def test_patch_asset(client):
    asset_id = client.post("/api/v1/assets", json=_NEW_ASSET).json()["id"]
    resp = client.patch(f"/api/v1/assets/{asset_id}", json={"owner": "ops-team"})
    assert resp.status_code == 200

def test_delete_asset(client):
    asset_id = client.post("/api/v1/assets", json=_NEW_ASSET).json()["id"]
    resp = client.delete(f"/api/v1/assets/{asset_id}")
    assert resp.status_code in (200, 204)

def test_asset_stats(client):
    resp = client.get("/api/v1/assets/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_asset_relationships(client):
    asset_id = client.post("/api/v1/assets", json=_NEW_ASSET).json()["id"]
    resp = client.get(f"/api/v1/assets/{asset_id}/relationships")
    assert resp.status_code == 200

def test_asset_events(client):
    asset_id = client.post("/api/v1/assets", json=_NEW_ASSET).json()["id"]
    resp = client.get(f"/api/v1/assets/{asset_id}/events")
    assert resp.status_code == 200
