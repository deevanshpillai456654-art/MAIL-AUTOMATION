"""Tests for the security status API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth_or_localhost

@pytest.fixture
def client():
    from backend.api.security import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth_or_localhost] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

def test_security_status(client):
    resp = client.get("/api/v1/security/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_local_runtime(client):
    resp = client.get("/api/v1/security/local-runtime")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_recent_audit(client):
    resp = client.get("/api/v1/security/audit/recent")
    assert resp.status_code == 200

def test_attack_surface(client):
    resp = client.get("/api/v1/security/attack-surface")
    assert resp.status_code == 200

def test_request_signing_example(client):
    resp = client.get("/api/v1/security/request-signing/example")
    assert resp.status_code == 200
