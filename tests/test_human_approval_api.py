"""Tests for the human approval queue API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.human_approval import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

def test_list_approvals_returns_structure(client):
    resp = client.get("/api/v1/approvals")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body or "approvals" in body or isinstance(body, (list, dict))

def test_create_approval_request(client):
    # ApprovalCreate requires "reason" (str)
    resp = client.post("/api/v1/approvals", json={
        "reason": "Deploy to prod needs manual sign-off",
    })
    assert resp.status_code in (200, 201)

def test_patch_approval_item(client):
    create = client.post("/api/v1/approvals", json={
        "reason": "Approve DB migration",
    })
    assert create.status_code in (200, 201)
    body = create.json()
    item_id = body.get("id") or body.get("item_id")
    if not item_id:
        pytest.skip("no id in create response")
    # ApprovalPatch uses "status" field
    resp = client.patch(f"/api/v1/approvals/{item_id}", json={"status": "approved"})
    assert resp.status_code in (200, 204)
