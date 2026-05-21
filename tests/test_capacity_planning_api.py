"""Tests for the capacity planning API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.capacity_planning import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_RES = {"name": "prod-cpu", "type": "cpu", "unit": "cores", "total_capacity": 64.0}

def test_list_resources_returns_structure(client):
    resp = client.get("/api/v1/capacity/resources")
    assert resp.status_code == 200
    body = resp.json()
    assert "resources" in body or "items" in body or isinstance(body, dict)

def test_create_resource_returns_id(client):
    resp = client.post("/api/v1/capacity/resources", json=_NEW_RES)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_resource_by_id(client):
    res_id = client.post("/api/v1/capacity/resources", json=_NEW_RES).json()["id"]
    resp = client.get(f"/api/v1/capacity/resources/{res_id}")
    assert resp.status_code == 200

def test_patch_resource(client):
    res_id = client.post("/api/v1/capacity/resources", json=_NEW_RES).json()["id"]
    resp = client.patch(f"/api/v1/capacity/resources/{res_id}", json={"total_capacity": 128.0})
    assert resp.status_code == 200

def test_delete_resource(client):
    res_id = client.post("/api/v1/capacity/resources", json=_NEW_RES).json()["id"]
    resp = client.delete(f"/api/v1/capacity/resources/{res_id}")
    assert resp.status_code in (200, 204)

def test_resource_stats(client):
    resp = client.get("/api/v1/capacity/resources/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
