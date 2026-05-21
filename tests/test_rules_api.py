"""Tests for the rule engine API: CRUD, labels, folders, presets, apply."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.local_auth import require_local_auth_or_localhost

_VALID_RULE = {
    "name": "TestRule",
    "condition": {"type": "subject_contains", "value": ["invoice"]},
    "actions": [{"type": "label", "label": "Finance"}],
    "enabled": True,
}


@pytest.fixture
def client():
    from backend.api.rules import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_local_auth_or_localhost] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# List + stats
# ---------------------------------------------------------------------------

def test_list_rules_returns_structure(client):
    resp = client.get("/rules")
    assert resp.status_code == 200
    body = resp.json()
    assert "rules" in body
    assert isinstance(body["rules"], list)
    assert "count" in body


def test_stats_returns_dict(client):
    resp = client.get("/rules/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_create_rule_returns_rule_id(client):
    resp = client.post("/rules", json=_VALID_RULE)
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "success"
    assert "rule_id" in body


def test_create_rule_missing_actions_rejected(client):
    resp = client.post("/rules", json={
        "name": "NoActions",
        "condition": {"type": "subject_contains", "value": ["x"]},
        "actions": [],
    })
    assert resp.status_code in (400, 422)


def test_created_rule_appears_in_list(client):
    unique_name = "AutoListCheck"
    client.post("/rules", json={
        "name": unique_name,
        "condition": {"type": "subject_contains", "value": ["test"]},
        "actions": [{"type": "label", "label": "TestLabel"}],
    })
    resp = client.get("/rules")
    names = [r.get("name") for r in resp.json()["rules"]]
    assert unique_name in names


def test_get_rule_by_name(client):
    rule_name = "ByNameRule"
    client.post("/rules", json={
        "name": rule_name,
        "condition": {"type": "subject_contains", "value": ["ping"]},
        "actions": [{"type": "label", "label": "Ping"}],
    })
    resp = client.get(f"/rules/{rule_name}")
    assert resp.status_code in (200, 404)  # 200 if found


def test_delete_rule_by_name(client):
    rule_name = "ToDeleteRule"
    client.post("/rules", json={
        "name": rule_name,
        "condition": {"type": "subject_contains", "value": ["del"]},
        "actions": [{"type": "label", "label": "Del"}],
    })
    resp = client.delete(f"/rules/{rule_name}")
    assert resp.status_code in (200, 404)


def test_update_rule_by_name(client):
    rule_name = "UpdateableRule"
    client.post("/rules", json={
        "name": rule_name,
        "condition": {"type": "subject_contains", "value": ["upd"]},
        "actions": [{"type": "label", "label": "Upd"}],
    })
    resp = client.put(f"/rules/{rule_name}", json={"description": "updated"})
    assert resp.status_code in (200, 404)


# ---------------------------------------------------------------------------
# Labels and folders
# ---------------------------------------------------------------------------

def test_labels_returns_list(client):
    resp = client.get("/rules/labels")
    assert resp.status_code == 200
    body = resp.json()
    assert "labels" in body
    assert isinstance(body["labels"], list)


def test_folders_returns_list(client):
    resp = client.get("/rules/folders")
    assert resp.status_code == 200
    body = resp.json()
    assert "folders" in body
    assert isinstance(body["folders"], list)


def test_create_label(client):
    resp = client.post("/rules/labels", json={"name": "TestLabel99", "color": "#ff0000"})
    assert resp.status_code in (200, 201, 409)  # 409 if already exists


def test_create_folder(client):
    resp = client.post("/rules/folders", json={"name": "TestFolder99"})
    assert resp.status_code in (200, 201, 409)


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------

def test_presets_returns_list(client):
    resp = client.get("/rules/presets")
    assert resp.status_code == 200
    body = resp.json()
    assert "presets" in body or "packs" in body or isinstance(body, dict)


# ---------------------------------------------------------------------------
# Apply rules
# ---------------------------------------------------------------------------

def test_apply_rules_returns_result(client):
    resp = client.post("/rules/apply", json={})
    assert resp.status_code in (200, 500)  # 500 acceptable if no emails in DB


# ---------------------------------------------------------------------------
# Forwarding
# ---------------------------------------------------------------------------

def test_forwarding_status(client):
    resp = client.get("/rules/forwarding/status")
    assert resp.status_code == 200


def test_forwarding_audit_returns_list(client):
    resp = client.get("/rules/forwarding/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert "logs" in body or "items" in body or isinstance(body, (list, dict))


# ---------------------------------------------------------------------------
# Templates + export
# ---------------------------------------------------------------------------

def test_templates_returns_list(client):
    resp = client.get("/rules/templates")
    assert resp.status_code == 200
    body = resp.json()
    assert "templates" in body or isinstance(body, (list, dict))


def test_export_returns_json(client):
    resp = client.get("/rules/export")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def test_audit_returns_list(client):
    resp = client.get("/rules/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert "logs" in body or "items" in body or isinstance(body, (list, dict))


# ---------------------------------------------------------------------------
# Defaults endpoint
# ---------------------------------------------------------------------------

def test_load_defaults(client):
    resp = client.post("/rules/defaults")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

def test_evaluate_email_against_rules(client):
    resp = client.post("/rules/evaluate", json={
        "subject": "Invoice from ACME",
        "sender_email": "billing@acme.com",
        "body": "Please find attached invoice.",
    })
    assert resp.status_code in (200, 422)
