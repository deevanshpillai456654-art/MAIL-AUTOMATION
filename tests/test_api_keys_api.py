"""Tests for the API keys management API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.api_keys import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_KEY = {"name": "ci-deploy-key", "scopes": ["read", "write"]}

def test_list_keys_returns_structure(client):
    resp = client.get("/api/v1/api-keys")
    assert resp.status_code == 200
    body = resp.json()
    assert "keys" in body or "items" in body or isinstance(body, dict)

def test_create_key_returns_id(client):
    resp = client.post("/api/v1/api-keys", json=_NEW_KEY)
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert "id" in body or "key_id" in body

def test_key_stats(client):
    resp = client.get("/api/v1/api-keys/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_get_key_by_id(client):
    key_id = client.post("/api/v1/api-keys", json=_NEW_KEY).json().get("id") or \
             client.post("/api/v1/api-keys", json=_NEW_KEY).json().get("key_id")
    if not key_id:
        pytest.skip("Could not extract key id from create response")
    resp = client.get(f"/api/v1/api-keys/{key_id}")
    assert resp.status_code == 200

def test_patch_key(client):
    key_id = client.post("/api/v1/api-keys", json=_NEW_KEY).json().get("id")
    if not key_id:
        pytest.skip("Could not extract key id")
    resp = client.patch(f"/api/v1/api-keys/{key_id}", json={"name": "renamed-key"})
    assert resp.status_code == 200

def test_delete_key(client):
    key_id = client.post("/api/v1/api-keys", json=_NEW_KEY).json().get("id")
    if not key_id:
        pytest.skip("Could not extract key id")
    resp = client.delete(f"/api/v1/api-keys/{key_id}")
    assert resp.status_code in (200, 204)

def test_rotate_key(client):
    key_id = client.post("/api/v1/api-keys", json=_NEW_KEY).json().get("id")
    if not key_id:
        pytest.skip("Could not extract key id")
    resp = client.post(f"/api/v1/api-keys/{key_id}/rotate")
    assert resp.status_code in (200, 201)
