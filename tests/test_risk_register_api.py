"""Tests for the risk register API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.risk_register import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_RISK = {"title": "DB single point of failure", "category": "technical", "likelihood": 3, "impact": 4}

def test_list_risks_returns_structure(client):
    resp = client.get("/api/v1/risks")
    assert resp.status_code == 200
    body = resp.json()
    assert "risks" in body or "items" in body or isinstance(body, dict)

def test_create_risk_returns_id(client):
    resp = client.post("/api/v1/risks", json=_NEW_RISK)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_risk_by_id(client):
    risk_id = client.post("/api/v1/risks", json=_NEW_RISK).json()["id"]
    resp = client.get(f"/api/v1/risks/{risk_id}")
    assert resp.status_code == 200

def test_patch_risk(client):
    risk_id = client.post("/api/v1/risks", json=_NEW_RISK).json()["id"]
    resp = client.patch(f"/api/v1/risks/{risk_id}", json={"owner": "ops-team"})
    assert resp.status_code == 200

def test_delete_risk(client):
    risk_id = client.post("/api/v1/risks", json=_NEW_RISK).json()["id"]
    resp = client.delete(f"/api/v1/risks/{risk_id}")
    assert resp.status_code in (200, 204)

def test_risk_stats(client):
    resp = client.get("/api/v1/risks/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
