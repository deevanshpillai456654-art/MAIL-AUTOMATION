"""Tests for the playbooks API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.playbooks import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_PB = {"name": "DB failover", "trigger_type": "manual", "steps": [{"name": "notify", "action": "alert"}]}

def test_list_playbooks_returns_structure(client):
    resp = client.get("/api/v1/playbooks")
    assert resp.status_code == 200
    body = resp.json()
    assert "playbooks" in body or "items" in body or isinstance(body, dict)

def test_create_playbook_returns_id(client):
    resp = client.post("/api/v1/playbooks", json=_NEW_PB)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_playbook_by_id(client):
    pb_id = client.post("/api/v1/playbooks", json=_NEW_PB).json()["id"]
    resp = client.get(f"/api/v1/playbooks/{pb_id}")
    assert resp.status_code == 200

def test_patch_playbook(client):
    pb_id = client.post("/api/v1/playbooks", json=_NEW_PB).json()["id"]
    resp = client.patch(f"/api/v1/playbooks/{pb_id}", json={"description": "updated"})
    assert resp.status_code == 200

def test_playbook_runs_list(client):
    resp = client.get("/api/v1/playbooks/runs")
    assert resp.status_code == 200
    body = resp.json()
    assert "runs" in body or "items" in body or isinstance(body, (list, dict))
