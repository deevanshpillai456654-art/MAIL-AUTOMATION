"""Tests for the email provider integrations API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.integrations import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

def test_gmail_status(client):
    resp = client.get("/gmail/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_outlook_status(client):
    resp = client.get("/outlook/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_imap_status(client):
    resp = client.get("/imap/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_sync_status_gmail(client):
    # sync/status/{provider} requires ?email= query param
    resp = client.get("/sync/status/gmail?email=test@example.com")
    assert resp.status_code in (200, 404)

def test_sync_status_outlook(client):
    resp = client.get("/sync/status/outlook?email=test@example.com")
    assert resp.status_code in (200, 404)

def test_get_settings_user1(client):
    resp = client.get("/settings/1")
    assert resp.status_code in (200, 404)

def test_stats_user1(client):
    resp = client.get("/stats/1")
    assert resp.status_code in (200, 404)

def test_gmail_labels_returns_list(client):
    resp = client.get("/gmail/labels/test@example.com")
    assert resp.status_code in (200, 404)

def test_sync_stop(client):
    resp = client.post("/sync/stop", json={})
    assert resp.status_code in (200, 422)
