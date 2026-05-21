"""Tests for the SLA policies API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.sla import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_POL = {"name": "P1 Critical", "severity": "critical", "response_minutes": 15, "resolve_minutes": 60}

def test_list_policies_returns_structure(client):
    resp = client.get("/api/v1/sla/policies")
    assert resp.status_code == 200
    body = resp.json()
    assert "policies" in body or "items" in body or isinstance(body, dict)

def test_create_policy_returns_id(client):
    resp = client.post("/api/v1/sla/policies", json=_NEW_POL)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_policy_by_id(client):
    pol_id = client.post("/api/v1/sla/policies", json=_NEW_POL).json()["id"]
    resp = client.get(f"/api/v1/sla/policies/{pol_id}")
    assert resp.status_code == 200

def test_policy_stats(client):
    resp = client.get("/api/v1/sla/policies/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_sla_status(client):
    resp = client.get("/api/v1/sla/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_sla_breaches(client):
    resp = client.get("/api/v1/sla/breaches")
    assert resp.status_code == 200
