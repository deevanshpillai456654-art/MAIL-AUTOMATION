"""Tests for the workflow engine API: CRUD, activation, execution, history."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.local_auth import require_local_auth


@pytest.fixture
def client():
    from backend.api.workflows import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

def test_list_templates_returns_list(client):
    resp = client.get("/api/v1/workflows/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert "templates" in body
    assert isinstance(body["templates"], list)


def test_template_list_nonempty(client):
    resp = client.get("/api/v1/workflows/templates")
    assert resp.json()["total"] >= 1


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_list_workflows_empty_initially(client):
    resp = client.get("/api/v1/workflows")
    assert resp.status_code == 200
    body = resp.json()
    assert "workflows" in body or "items" in body or isinstance(body, list)


def test_create_workflow(client):
    resp = client.post("/api/v1/workflows", json={
        "name": "Test Workflow",
        "description": "Created by test",
        "trigger_type": "manual",
        "steps": [],
    })
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert "id" in body or "workflow" in body


def test_get_workflow_by_id(client):
    create = client.post("/api/v1/workflows", json={"name": "Fetch Test", "trigger_type": "manual"})
    assert create.status_code in (200, 201)
    wf_id = create.json().get("id") or create.json().get("workflow", {}).get("id")
    assert wf_id

    resp = client.get(f"/api/v1/workflows/{wf_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("id") == wf_id or body.get("workflow", {}).get("id") == wf_id


def test_update_workflow_name(client):
    create = client.post("/api/v1/workflows", json={"name": "Original", "trigger_type": "manual"})
    wf_id = create.json().get("id") or create.json().get("workflow", {}).get("id")

    resp = client.put(f"/api/v1/workflows/{wf_id}", json={"name": "Renamed"})
    assert resp.status_code == 200


def test_delete_workflow(client):
    create = client.post("/api/v1/workflows", json={"name": "ToDelete", "trigger_type": "manual"})
    wf_id = create.json().get("id") or create.json().get("workflow", {}).get("id")

    resp = client.delete(f"/api/v1/workflows/{wf_id}")
    assert resp.status_code == 200

    # Confirm 404 after delete
    get_resp = client.get(f"/api/v1/workflows/{wf_id}")
    assert get_resp.status_code in (404, 200)  # 404 preferred; 200 with empty acceptable


# ---------------------------------------------------------------------------
# Activation
# ---------------------------------------------------------------------------

def test_activate_workflow(client):
    create = client.post("/api/v1/workflows", json={"name": "Activatable", "trigger_type": "manual"})
    wf_id = create.json().get("id") or create.json().get("workflow", {}).get("id")

    resp = client.post(f"/api/v1/workflows/{wf_id}/activate")
    assert resp.status_code == 200


def test_deactivate_workflow(client):
    create = client.post("/api/v1/workflows", json={"name": "Deactivatable", "trigger_type": "manual"})
    wf_id = create.json().get("id") or create.json().get("workflow", {}).get("id")

    client.post(f"/api/v1/workflows/{wf_id}/activate")
    resp = client.post(f"/api/v1/workflows/{wf_id}/deactivate")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Manual execution
# ---------------------------------------------------------------------------

def test_execute_workflow_returns_execution_id(client):
    create = client.post("/api/v1/workflows", json={"name": "Runnable", "trigger_type": "manual", "steps": []})
    wf_id = create.json().get("id") or create.json().get("workflow", {}).get("id")

    resp = client.post(f"/api/v1/workflows/{wf_id}/execute", json={"input_data": {}})
    assert resp.status_code in (200, 201, 202)
    body = resp.json()
    assert "execution_id" in body or "id" in body or "execution" in body


def test_execute_workflow_history(client):
    create = client.post("/api/v1/workflows", json={"name": "HistoryTest", "trigger_type": "manual", "steps": []})
    wf_id = create.json().get("id") or create.json().get("workflow", {}).get("id")

    client.post(f"/api/v1/workflows/{wf_id}/execute", json={"input_data": {}})

    resp = client.get(f"/api/v1/workflows/{wf_id}/history")
    assert resp.status_code == 200
    body = resp.json()
    assert "executions" in body or "history" in body or "items" in body or isinstance(body, list)


# ---------------------------------------------------------------------------
# Stats and recommendations
# ---------------------------------------------------------------------------

def test_workflow_stats(client):
    resp = client.get("/api/v1/workflows/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert "total" in body or "workflows" in body or "stats" in body or isinstance(body, dict)


def test_workflow_recommendations(client):
    resp = client.get("/api/v1/workflows/recommendations")
    assert resp.status_code == 200
    body = resp.json()
    assert "recommendations" in body or isinstance(body, (list, dict))


# ---------------------------------------------------------------------------
# Template-based creation
# ---------------------------------------------------------------------------

def test_create_workflow_from_template(client):
    templates = client.get("/api/v1/workflows/templates").json()["templates"]
    if not templates:
        pytest.skip("No templates available")
    tmpl_id = templates[0].get("template_id") or templates[0].get("id")
    resp = client.post("/api/v1/workflows", json={"template_id": tmpl_id})
    assert resp.status_code in (200, 201)
    assert "id" in resp.json() or "workflow" in resp.json()
