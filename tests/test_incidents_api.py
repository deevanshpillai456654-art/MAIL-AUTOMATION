"""Tests for the incidents API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.incidents import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_INC = {"title": "Test Incident", "severity": "medium", "description": "Test"}

def test_list_incidents_returns_structure(client):
    resp = client.get("/api/v1/incidents")
    assert resp.status_code == 200
    assert "incidents" in resp.json()

def test_create_incident_returns_id(client):
    resp = client.post("/api/v1/incidents", json=_NEW_INC)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_incident_by_id(client):
    inc_id = client.post("/api/v1/incidents", json=_NEW_INC).json()["id"]
    resp = client.get(f"/api/v1/incidents/{inc_id}")
    assert resp.status_code == 200
    # response is {"incident": {...}, "timeline": [...]}
    body = resp.json()
    inc = body.get("incident") or body
    assert inc.get("id") == inc_id

def test_patch_incident(client):
    inc_id = client.post("/api/v1/incidents", json=_NEW_INC).json()["id"]
    # patch accepts assigned_to or status — not raw description
    resp = client.patch(f"/api/v1/incidents/{inc_id}", json={"assigned_to": "ops-team"})
    assert resp.status_code == 200

def test_acknowledge_incident(client):
    inc_id = client.post("/api/v1/incidents", json=_NEW_INC).json()["id"]
    resp = client.post(f"/api/v1/incidents/{inc_id}/acknowledge")
    assert resp.status_code == 200

def test_resolve_incident(client):
    inc_id = client.post("/api/v1/incidents", json=_NEW_INC).json()["id"]
    resp = client.post(f"/api/v1/incidents/{inc_id}/resolve")
    assert resp.status_code == 200

def test_comment_on_incident(client):
    inc_id = client.post("/api/v1/incidents", json=_NEW_INC).json()["id"]
    # CommentBody uses "note" field, not "text"
    resp = client.post(f"/api/v1/incidents/{inc_id}/comment", json={"note": "investigating"})
    assert resp.status_code == 200

def test_incident_stats(client):
    resp = client.get("/api/v1/incidents/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
