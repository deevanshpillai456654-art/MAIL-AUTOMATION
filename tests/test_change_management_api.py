"""Tests for the change management API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.change_management import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_CR = {"title": "Deploy v2.0", "change_type": "normal", "risk_level": "low"}

def test_list_changes_returns_structure(client):
    resp = client.get("/api/v1/changes")
    assert resp.status_code == 200
    assert "changes" in resp.json()

def test_create_change_returns_id(client):
    resp = client.post("/api/v1/changes", json=_NEW_CR)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_change_by_id(client):
    cr_id = client.post("/api/v1/changes", json=_NEW_CR).json()["id"]
    resp = client.get(f"/api/v1/changes/{cr_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == cr_id

def test_patch_change(client):
    cr_id = client.post("/api/v1/changes", json=_NEW_CR).json()["id"]
    resp = client.patch(f"/api/v1/changes/{cr_id}", json={"description": "updated"})
    assert resp.status_code == 200

def test_delete_change(client):
    cr_id = client.post("/api/v1/changes", json=_NEW_CR).json()["id"]
    resp = client.delete(f"/api/v1/changes/{cr_id}")
    assert resp.status_code in (200, 204)

def test_change_stats(client):
    resp = client.get("/api/v1/changes/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_change_approvals_list(client):
    cr_id = client.post("/api/v1/changes", json=_NEW_CR).json()["id"]
    resp = client.get(f"/api/v1/changes/{cr_id}/approvals")
    assert resp.status_code == 200

def test_add_approval(client):
    cr_id = client.post("/api/v1/changes", json=_NEW_CR).json()["id"]
    resp = client.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice", "decision": "approved"})
    assert resp.status_code in (200, 201)
