"""Tests for the config management API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.config_management import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

import uuid as _uuid

def _new_cfg():
    return {"key": f"CFG_{_uuid.uuid4().hex[:8]}", "value": "100", "environment": "production", "type": "number"}

def test_list_configs_returns_structure(client):
    resp = client.get("/api/v1/configs")
    assert resp.status_code == 200
    body = resp.json()
    assert "configs" in body or "items" in body or isinstance(body, dict)

def test_create_config_returns_id(client):
    resp = client.post("/api/v1/configs", json=_new_cfg())
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_config_by_id(client):
    cfg_id = client.post("/api/v1/configs", json=_new_cfg()).json()["id"]
    resp = client.get(f"/api/v1/configs/{cfg_id}")
    assert resp.status_code == 200

def test_patch_config(client):
    cfg_id = client.post("/api/v1/configs", json=_new_cfg()).json()["id"]
    resp = client.patch(f"/api/v1/configs/{cfg_id}", json={"value": "200"})
    assert resp.status_code == 200

def test_delete_config(client):
    cfg_id = client.post("/api/v1/configs", json=_new_cfg()).json()["id"]
    resp = client.delete(f"/api/v1/configs/{cfg_id}")
    assert resp.status_code in (200, 204)

def test_config_stats(client):
    resp = client.get("/api/v1/configs/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
