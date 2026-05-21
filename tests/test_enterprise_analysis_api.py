"""Tests for the enterprise analysis API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth_or_localhost

@pytest.fixture
def client():
    from backend.api.enterprise_analysis import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_local_auth_or_localhost] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

def test_analysis_capabilities(client):
    resp = client.get("/analysis/capabilities")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_analyze_email(client):
    resp = client.post("/analysis/email", json={
        "subject": "Invoice #1234 from ACME",
        "body": "Please find attached the invoice.",
        "sender": "billing@acme.com",
    })
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_simulate_analysis(client):
    resp = client.post("/analysis/simulate", json={"scenario": "high_volume"})
    assert resp.status_code in (200, 422)
