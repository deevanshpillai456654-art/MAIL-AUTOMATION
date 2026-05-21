"""Tests for the VS Code extension connection API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.connection import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

def test_extension_status(client):
    resp = client.get("/extension/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_extension_ports(client):
    resp = client.get("/extension/ports")
    assert resp.status_code == 200

def test_extension_discover(client):
    resp = client.get("/extension/discover")
    assert resp.status_code == 200

def test_extension_handshake(client):
    # HandshakeRequest needs client_id, client_type, version, timestamp (int)
    resp = client.post("/extension/handshake", json={
        "client_id": "test-vscode",
        "client_type": "vscode",
        "version": "1.0.0",
        "timestamp": 1700000000,
    })
    assert resp.status_code in (200, 401, 403)

def test_extension_heartbeat(client):
    resp = client.post("/extension/heartbeat", json={"client_id": "test-vscode"})
    assert resp.status_code in (200, 401, 404, 422)
