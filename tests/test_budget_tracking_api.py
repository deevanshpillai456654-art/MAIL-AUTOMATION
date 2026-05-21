"""Tests for the budget tracking API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.budget_tracking import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_BUD = {
    "name": "Q1 Infrastructure",
    "category": "infrastructure",
    "period_start": "2026-01-01",
    "period_end": "2026-03-31",
    "amount": 50000.0,
}

def test_list_budgets_returns_structure(client):
    resp = client.get("/api/v1/budgets")
    assert resp.status_code == 200
    assert "budgets" in resp.json()

def test_create_budget_returns_id(client):
    resp = client.post("/api/v1/budgets", json=_NEW_BUD)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_budget_by_id(client):
    bud_id = client.post("/api/v1/budgets", json=_NEW_BUD).json()["id"]
    resp = client.get(f"/api/v1/budgets/{bud_id}")
    assert resp.status_code == 200

def test_patch_budget(client):
    bud_id = client.post("/api/v1/budgets", json=_NEW_BUD).json()["id"]
    resp = client.patch(f"/api/v1/budgets/{bud_id}", json={"amount": 60000.0})
    assert resp.status_code == 200

def test_delete_budget(client):
    bud_id = client.post("/api/v1/budgets", json=_NEW_BUD).json()["id"]
    resp = client.delete(f"/api/v1/budgets/{bud_id}")
    assert resp.status_code in (200, 204)

def test_budget_stats(client):
    resp = client.get("/api/v1/budgets/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_budget_entries(client):
    bud_id = client.post("/api/v1/budgets", json=_NEW_BUD).json()["id"]
    resp = client.get(f"/api/v1/budgets/{bud_id}/entries")
    assert resp.status_code == 200

def test_cost_entries(client):
    resp = client.get("/api/v1/cost_entries")
    assert resp.status_code == 200
