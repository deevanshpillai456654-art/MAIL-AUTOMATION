"""Tests for the export/import/data-deletion API."""
from __future__ import annotations

import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.local_auth import require_local_auth


@pytest.fixture
def client():
    from backend.api.export import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------

def test_export_emails_csv_returns_csv(client):
    resp = client.get("/export/emails/csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")


def test_export_emails_csv_content_disposition(client):
    resp = client.get("/export/emails/csv")
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_export_emails_json_returns_dict(client):
    resp = client.get("/export/emails/json")
    assert resp.status_code == 200
    body = resp.json()
    assert "emails" in body
    assert "count" in body
    assert isinstance(body["emails"], list)


def test_export_rules_json_returns_dict(client):
    resp = client.get("/export/rules/json")
    assert resp.status_code == 200
    body = resp.json()
    assert "rules" in body
    assert "count" in body


def test_export_feedback_json_returns_dict(client):
    resp = client.get("/export/feedback/json")
    assert resp.status_code == 200
    body = resp.json()
    assert "feedback" in body
    assert "count" in body


def test_export_all_returns_dict(client):
    resp = client.get("/export/all")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_export_emails_csv_limit_param(client):
    resp = client.get("/export/emails/csv?limit=10")
    assert resp.status_code == 200


def test_export_emails_csv_limit_out_of_range(client):
    resp = client.get("/export/emails/csv?limit=0")
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Import endpoints
# ---------------------------------------------------------------------------

def test_import_emails_json_empty_list(client):
    resp = client.post("/import/emails/json", json={"emails": []})
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body.get("status") == "success"


def test_import_rules_json_empty_list(client):
    resp = client.post("/import/rules/json", json={"rules": []})
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body.get("status") == "success"


def test_import_all_empty(client):
    resp = client.post("/import/all", json={})
    assert resp.status_code in (200, 201)
    assert resp.json().get("status") == "success"


# ---------------------------------------------------------------------------
# Data deletion
# ---------------------------------------------------------------------------

def test_delete_feedback_returns_success(client):
    resp = client.delete("/data/feedback", headers={"X-Confirm-Delete": "yes"})
    assert resp.status_code == 200
    assert resp.json().get("status") == "success"


def test_delete_rules_returns_success(client):
    resp = client.delete("/data/rules", headers={"X-Confirm-Delete": "yes"})
    assert resp.status_code == 200
    assert resp.json().get("status") == "success"


def test_delete_emails_returns_status(client):
    resp = client.delete("/data/emails", headers={"X-Confirm-Delete": "yes"})
    assert resp.status_code == 200
    body = resp.json()
    assert "status" in body


def test_delete_without_confirmation_header_rejected(client):
    resp = client.delete("/data/feedback")
    assert resp.status_code == 428
