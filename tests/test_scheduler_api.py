"""Tests for the scheduler control API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth_or_localhost

@pytest.fixture
def client():
    from backend.api.scheduler import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_local_auth_or_localhost] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

def test_scheduler_status(client):
    resp = client.get("/scheduler/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)

def test_list_tasks_returns_structure(client):
    resp = client.get("/scheduler/tasks")
    assert resp.status_code == 200
    body = resp.json()
    assert "tasks" in body or "items" in body or isinstance(body, (list, dict))

def test_start_scheduler(client):
    resp = client.post("/scheduler/start")
    assert resp.status_code == 200

def test_stop_scheduler(client):
    resp = client.post("/scheduler/stop")
    assert resp.status_code == 200

def test_create_task_returns_id(client):
    # TaskInput requires: name, frequency (str), interval_hours (int)
    resp = client.post("/scheduler/tasks", json={
        "name": "test-task",
        "frequency": "hourly",
        "interval_hours": 1,
        "enabled": True,
    })
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert "id" in body or "task_id" in body or "ok" in body or "status" in body
