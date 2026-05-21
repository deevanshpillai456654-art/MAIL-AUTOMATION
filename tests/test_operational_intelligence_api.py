"""Tests for the operational intelligence API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.operational_intelligence import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

def test_insights_returns_structure(client):
    resp = client.get("/api/v1/intelligence/insights")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_patterns_returns_structure(client):
    resp = client.get("/api/v1/intelligence/patterns")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_anomalies_returns_structure(client):
    resp = client.get("/api/v1/intelligence/anomalies")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_health_returns_structure(client):
    resp = client.get("/api/v1/intelligence/health")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_predictions_returns_structure(client):
    resp = client.get("/api/v1/intelligence/predictions")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_recommendations_returns_structure(client):
    resp = client.get("/api/v1/intelligence/recommendations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_analyze_returns_result(client):
    resp = client.post("/api/v1/intelligence/analyze", json={"scope": "incidents", "limit": 10})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
