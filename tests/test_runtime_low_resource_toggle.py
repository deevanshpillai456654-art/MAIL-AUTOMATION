"""Tests for the Low Resource Mode runtime toggle endpoints."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.core.runtime_control as rc_mod


@pytest.fixture(autouse=True)
def clean_overrides():
    rc_mod._runtime_overrides.clear()
    yield
    rc_mod._runtime_overrides.clear()


def _make_client():
    from backend.api.runtime_control import router
    from backend.api.session import router as session_router

    app = FastAPI()
    app.include_router(session_router, prefix="/api/v1")
    app.include_router(router, prefix="/api/v1")

    client = TestClient(app)
    client.post("/api/v1/session/bootstrap")
    return client


def test_get_low_resource_mode_default():
    client = _make_client()
    resp = client.get("/api/v1/runtime/low-resource-mode")
    assert resp.status_code == 200
    data = resp.json()
    assert "enabled" in data
    assert "profile" in data
    assert data["enabled"] is False


def test_enable_low_resource_mode():
    client = _make_client()
    resp = client.post("/api/v1/runtime/low-resource-mode", json={"enabled": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is True
    assert data["profile"] == "low_resource"
    assert data["snapshot"]["ai_mode"] == "disabled"
    assert data["snapshot"]["limits"]["max_workers"] == 1


def test_disable_low_resource_mode_after_enabling():
    client = _make_client()
    client.post("/api/v1/runtime/low-resource-mode", json={"enabled": True})
    resp = client.post("/api/v1/runtime/low-resource-mode", json={"enabled": False})
    assert resp.status_code == 200
    data = resp.json()
    assert data["enabled"] is False
    assert data["profile"] == "standard"


def test_override_does_not_persist_across_module_reset(monkeypatch):
    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "standard")
    client = _make_client()
    client.post("/api/v1/runtime/low-resource-mode", json={"enabled": True})
    assert rc_mod._runtime_overrides.get("AIO_LOW_RESOURCE_MODE") == "true"

    rc_mod._runtime_overrides.clear()
    rt = rc_mod.get_runtime_control()
    assert rt.profile == "standard"


def test_get_reflects_toggle_state():
    client = _make_client()
    client.post("/api/v1/runtime/low-resource-mode", json={"enabled": True})
    resp = client.get("/api/v1/runtime/low-resource-mode")
    assert resp.json()["enabled"] is True
