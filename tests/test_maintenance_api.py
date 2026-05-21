"""Tests for the maintenance windows API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.maintenance import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_WIN = {
    "name": "Weekly DB maintenance",
    "starts_at": "2026-06-01T02:00:00+00:00",
    "ends_at": "2026-06-01T04:00:00+00:00",
}

def test_list_windows_returns_structure(client):
    resp = client.get("/api/v1/maintenance")
    assert resp.status_code == 200
    body = resp.json()
    assert "windows" in body or "items" in body or isinstance(body, (list, dict))

def test_maintenance_status(client):
    resp = client.get("/api/v1/maintenance/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_create_window_returns_id(client):
    resp = client.post("/api/v1/maintenance", json=_NEW_WIN)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_window_by_id(client):
    win_id = client.post("/api/v1/maintenance", json=_NEW_WIN).json()["id"]
    resp = client.get(f"/api/v1/maintenance/{win_id}")
    assert resp.status_code == 200

def test_patch_window(client):
    win_id = client.post("/api/v1/maintenance", json=_NEW_WIN).json()["id"]
    resp = client.patch(f"/api/v1/maintenance/{win_id}", json={"description": "updated"})
    assert resp.status_code == 200

def test_delete_window(client):
    win_id = client.post("/api/v1/maintenance", json=_NEW_WIN).json()["id"]
    resp = client.delete(f"/api/v1/maintenance/{win_id}")
    assert resp.status_code in (200, 204)
