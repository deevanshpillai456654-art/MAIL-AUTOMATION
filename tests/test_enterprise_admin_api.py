"""Tests for the enterprise admin overview API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth_or_localhost

@pytest.fixture
def client():
    from backend.api.enterprise_admin import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_local_auth_or_localhost] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

def test_admin_overview(client):
    resp = client.get("/admin/overview")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_admin_audit(client):
    resp = client.get("/admin/audit")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
