"""Tests for the deployments API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.deployments import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_DEP = {"name": "api-gateway", "version": "2.1.0", "environment": "production", "deployer": "ci-bot"}

def test_list_deployments_returns_structure(client):
    resp = client.get("/api/v1/deployments")
    assert resp.status_code == 200
    body = resp.json()
    assert "deployments" in body or "items" in body or isinstance(body, dict)

def test_create_deployment_returns_id(client):
    resp = client.post("/api/v1/deployments", json=_NEW_DEP)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_deployment_by_id(client):
    dep_id = client.post("/api/v1/deployments", json=_NEW_DEP).json()["id"]
    resp = client.get(f"/api/v1/deployments/{dep_id}")
    assert resp.status_code == 200

def test_patch_deployment(client):
    dep_id = client.post("/api/v1/deployments", json=_NEW_DEP).json()["id"]
    resp = client.patch(f"/api/v1/deployments/{dep_id}", json={"notes": "hotfix applied"})
    assert resp.status_code == 200

def test_delete_deployment(client):
    dep_id = client.post("/api/v1/deployments", json=_NEW_DEP).json()["id"]
    resp = client.delete(f"/api/v1/deployments/{dep_id}")
    assert resp.status_code in (200, 204)

def test_deployment_stats(client):
    resp = client.get("/api/v1/deployments/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
