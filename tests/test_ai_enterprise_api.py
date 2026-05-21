"""Tests for the AI enterprise API: runtime, models, learning, inference, search."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.local_auth import require_local_auth_or_localhost


@pytest.fixture
def client():
    from backend.api.ai_enterprise import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_local_auth_or_localhost] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


def test_platform_version_returns_version(client):
    resp = client.get("/platform/version")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_runtime_status_returns_dict(client):
    resp = client.get("/ai/runtime/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_hardware_info_returns_dict(client):
    resp = client.get("/ai/hardware")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_models_returns_dict(client):
    resp = client.get("/ai/models")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_onnx_status_returns_dict(client):
    resp = client.get("/ai/onnx/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_onnx_models_returns_dict(client):
    resp = client.get("/ai/onnx/models")
    assert resp.status_code == 200
    body = resp.json()
    assert "models" in body or "status" in body


def test_backup_status_returns_dict(client):
    # backup endpoints have an inner _require_ai_admin guard; 401 is acceptable
    resp = client.get("/ai/backups/status")
    assert resp.status_code in (200, 401)
    assert isinstance(resp.json(), dict)


def test_run_backup_returns_dict(client):
    resp = client.post("/ai/backups/run")
    assert resp.status_code in (200, 401)
    assert isinstance(resp.json(), dict)


def test_run_scheduled_backup(client):
    resp = client.post("/ai/backups/scheduled/run")
    assert resp.status_code in (200, 401)


def test_learning_stats_returns_dict(client):
    resp = client.get("/ai/learning/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_learning_overrides_returns_dict(client):
    resp = client.get("/ai/learning/overrides")
    assert resp.status_code == 200


def test_learning_events_returns_dict(client):
    resp = client.get("/ai/learning/events")
    assert resp.status_code == 200


def test_learning_feedback_records(client):
    resp = client.post("/ai/learning/feedback", json={
        "message_id": "test-001",
        "original_category": "inbox",
        "correct_category": "finance",
        "feedback_type": "correction",
    })
    assert resp.status_code == 200


def test_learning_export(client):
    # has inner _require_ai_admin guard; 401 is acceptable without token
    resp = client.get("/ai/learning/export")
    assert resp.status_code in (200, 401)


def test_self_healing_status(client):
    resp = client.get("/ai/self-healing/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_infer_sync(client):
    resp = client.post("/ai/infer", json={
        "task": "classify_email",
        "payload": {"subject": "Invoice", "body": "Pay now"},
        "run_async": False,
    })
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_infer_async_returns_job_id(client):
    resp = client.post("/ai/infer", json={
        "task": "classify_email",
        "payload": {"subject": "Async"},
        "run_async": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("queued") is True or "job_id" in body


def test_queue_status(client):
    resp = client.get("/ai/queue/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_memory_upsert(client):
    resp = client.post("/ai/memory/upsert", json={
        "text": "Test email about invoices",
        "namespace": "emails",
        "metadata": {},
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "id" in body or "status" in body


def test_memory_status(client):
    resp = client.get("/ai/memory/status")
    assert resp.status_code == 200


def test_search_returns_results(client):
    resp = client.post("/ai/search", json={"query": "invoice", "top_k": 5})
    assert resp.status_code == 200
    assert "results" in resp.json()


def test_agents_returns_dict(client):
    resp = client.get("/ai/agents")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_ai_workflows_returns_dict(client):
    resp = client.get("/ai/workflows")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_governance_status(client):
    resp = client.get("/ai/governance/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_classify(client):
    resp = client.post("/ai/classify", json={"text": "Meeting at 3pm"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_extract(client):
    resp = client.post("/ai/extract", json={"text": "Email from john@acme.com"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_smart_tags(client):
    resp = client.post("/ai/tags", json={"text": "Quarterly finance report"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_priority(client):
    resp = client.post("/ai/priority", json={"text": "URGENT: Server down"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_workflow_suggest(client):
    resp = client.post("/ai/workflows/suggest", json={"text": "forward invoices to finance"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_index_record(client):
    resp = client.post("/ai/index/record", json={
        "text": "Monthly report",
        "namespace": "emails",
        "metadata": {},
    })
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_index_batch(client):
    resp = client.post("/ai/index/batch", json={
        "records": [{"text": "Email A", "metadata": {}}, {"text": "Email B", "metadata": {}}],
        "namespace": "emails",
    })
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_index_status(client):
    resp = client.get("/ai/index/status")
    assert resp.status_code == 200


def test_cache_status(client):
    resp = client.get("/ai/cache/status")
    assert resp.status_code == 200


def test_telemetry_status(client):
    resp = client.get("/ai/telemetry/status")
    assert resp.status_code == 200


def test_diagnostics_status(client):
    resp = client.get("/ai/diagnostics/status")
    assert resp.status_code == 200


def test_vector_db_status(client):
    resp = client.get("/ai/vector-db/status")
    assert resp.status_code == 200


def test_command_center(client):
    resp = client.get("/ai/command-center")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
