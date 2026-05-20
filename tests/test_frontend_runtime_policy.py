from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client():
    from backend.api.frontend_runtime import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_frontend_runtime_policy_includes_low_resource_flags(monkeypatch):
    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "low_resource")
    client = _client()

    resp = client.get("/api/v1/frontend/runtime-policy")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["runtime"]["profile"] == "low_resource"
    assert payload["runtime"]["ai_mode"] == "disabled"
    assert payload["runtime"]["frontend"]["minimal_animations"] is True
    assert payload["runtime"]["frontend"]["deferred_rendering"] is True
    assert payload["runtime"]["limits"]["max_workers"] == 1


def test_client_runtime_policy_exposes_rendering_budget(monkeypatch):
    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "lite")
    client = _client()

    resp = client.get("/api/v1/frontend/clients/runtime-policy")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["runtime_profile"] == "lite"
    assert payload["rendering_budget"]["deferred_rendering"] is True
    assert payload["rendering_budget"]["virtualize_lists"] is True
    assert payload["rendering_budget"]["max_visible_rows"] <= 250
