"""Tests for the feature flags API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.feature_flags import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

def test_list_flags_returns_structure(client):
    resp = client.get("/api/v1/flags")
    assert resp.status_code == 200
    assert "flags" in resp.json()

def test_create_flag_returns_id(client):
    resp = client.post("/api/v1/flags", json={"name": "test-feature-flag"})
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_flag_by_id(client):
    flag_id = client.post("/api/v1/flags", json={"name": "get-test-flag"}).json()["id"]
    resp = client.get(f"/api/v1/flags/{flag_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == flag_id

def test_patch_flag(client):
    flag_id = client.post("/api/v1/flags", json={"name": "patch-flag"}).json()["id"]
    resp = client.patch(f"/api/v1/flags/{flag_id}", json={"description": "updated"})
    assert resp.status_code == 200

def test_delete_flag(client):
    flag_id = client.post("/api/v1/flags", json={"name": "delete-flag"}).json()["id"]
    resp = client.delete(f"/api/v1/flags/{flag_id}")
    assert resp.status_code in (200, 204)

def test_flag_stats(client):
    resp = client.get("/api/v1/flags/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_evaluate_flag(client):
    # EvaluateBatchBody requires "keys" (list), not "flag_key"
    resp = client.post("/api/v1/flags/evaluate", json={"keys": ["nonexistent-flag"]})
    assert resp.status_code == 200

def test_flag_events(client):
    flag_id = client.post("/api/v1/flags", json={"name": "events-flag"}).json()["id"]
    resp = client.get(f"/api/v1/flags/{flag_id}/events")
    assert resp.status_code == 200

def test_flag_environments(client):
    flag_id = client.post("/api/v1/flags", json={"name": "env-flag"}).json()["id"]
    resp = client.get(f"/api/v1/flags/{flag_id}/environments")
    assert resp.status_code == 200
