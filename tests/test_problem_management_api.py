"""Tests for the problem management API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.problem_management import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_PR = {"title": "DB performance degradation", "priority": "high"}

def test_list_problems_returns_structure(client):
    resp = client.get("/api/v1/problems")
    assert resp.status_code == 200
    assert "problems" in resp.json()

def test_create_problem_returns_id(client):
    resp = client.post("/api/v1/problems", json=_NEW_PR)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_problem_by_id(client):
    pr_id = client.post("/api/v1/problems", json=_NEW_PR).json()["id"]
    resp = client.get(f"/api/v1/problems/{pr_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == pr_id

def test_patch_problem(client):
    pr_id = client.post("/api/v1/problems", json=_NEW_PR).json()["id"]
    resp = client.patch(f"/api/v1/problems/{pr_id}", json={"root_cause": "index missing"})
    assert resp.status_code == 200

def test_delete_problem(client):
    pr_id = client.post("/api/v1/problems", json=_NEW_PR).json()["id"]
    resp = client.delete(f"/api/v1/problems/{pr_id}")
    assert resp.status_code in (200, 204)

def test_problem_stats(client):
    resp = client.get("/api/v1/problems/stats")
    assert resp.status_code == 200

def test_problem_timeline(client):
    pr_id = client.post("/api/v1/problems", json=_NEW_PR).json()["id"]
    resp = client.get(f"/api/v1/problems/{pr_id}/timeline")
    assert resp.status_code == 200

def test_problem_incidents_sub(client):
    pr_id = client.post("/api/v1/problems", json=_NEW_PR).json()["id"]
    resp = client.get(f"/api/v1/problems/{pr_id}/incidents")
    assert resp.status_code == 200
