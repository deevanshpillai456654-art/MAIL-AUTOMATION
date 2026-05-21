"""Tests for the on-call scheduling API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.oncall import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_SCH = {"name": "Primary On-Call", "timezone": "UTC"}

def test_list_schedules_returns_structure(client):
    resp = client.get("/api/v1/oncall/schedules")
    assert resp.status_code == 200
    assert "schedules" in resp.json()

def test_current_oncall_returns_dict(client):
    resp = client.get("/api/v1/oncall/schedules/current")
    assert resp.status_code == 200

def test_create_schedule_returns_id(client):
    resp = client.post("/api/v1/oncall/schedules", json=_NEW_SCH)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_schedule_by_id(client):
    sch_id = client.post("/api/v1/oncall/schedules", json=_NEW_SCH).json()["id"]
    resp = client.get(f"/api/v1/oncall/schedules/{sch_id}")
    assert resp.status_code == 200

def test_patch_schedule(client):
    sch_id = client.post("/api/v1/oncall/schedules", json=_NEW_SCH).json()["id"]
    resp = client.patch(f"/api/v1/oncall/schedules/{sch_id}", json={"description": "updated"})
    assert resp.status_code == 200

def test_delete_schedule(client):
    sch_id = client.post("/api/v1/oncall/schedules", json=_NEW_SCH).json()["id"]
    resp = client.delete(f"/api/v1/oncall/schedules/{sch_id}")
    assert resp.status_code in (200, 204)
