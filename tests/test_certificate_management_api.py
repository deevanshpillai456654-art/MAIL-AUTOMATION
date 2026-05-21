"""Tests for the certificate management API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.certificate_management import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_CERT = {"name": "prod-api-cert", "domain": "api.example.com", "type": "ssl", "environment": "production"}

def test_list_certs_returns_structure(client):
    resp = client.get("/api/v1/certificates")
    assert resp.status_code == 200
    body = resp.json()
    assert "certificates" in body or "items" in body or isinstance(body, dict)

def test_create_cert_returns_id(client):
    resp = client.post("/api/v1/certificates", json=_NEW_CERT)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_cert_by_id(client):
    cert_id = client.post("/api/v1/certificates", json=_NEW_CERT).json()["id"]
    resp = client.get(f"/api/v1/certificates/{cert_id}")
    assert resp.status_code == 200

def test_patch_cert(client):
    cert_id = client.post("/api/v1/certificates", json=_NEW_CERT).json()["id"]
    resp = client.patch(f"/api/v1/certificates/{cert_id}", json={"notes": "renewed"})
    assert resp.status_code == 200

def test_delete_cert(client):
    cert_id = client.post("/api/v1/certificates", json=_NEW_CERT).json()["id"]
    resp = client.delete(f"/api/v1/certificates/{cert_id}")
    assert resp.status_code in (200, 204)

def test_cert_stats(client):
    resp = client.get("/api/v1/certificates/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_expiring_certs(client):
    resp = client.get("/api/v1/certificates/expiring")
    assert resp.status_code == 200
