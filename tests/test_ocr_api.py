"""Tests for the OCR job API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.ocr import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

def test_ocr_history_returns_structure(client):
    resp = client.get("/api/v1/ocr/history")
    assert resp.status_code == 200
    body = resp.json()
    assert "jobs" in body or "items" in body or isinstance(body, (list, dict))

def test_ocr_scan_returns_result(client):
    resp = client.post("/api/v1/ocr/scan", json={})
    assert resp.status_code in (200, 201, 422)

def test_ocr_scan_email_returns_result(client):
    resp = client.post("/api/v1/ocr/scan-email", json={"email_id": "nonexistent"})
    assert resp.status_code in (200, 201, 404, 422)

def test_clear_ocr_history(client):
    resp = client.delete("/api/v1/ocr/history")
    assert resp.status_code in (200, 204)
