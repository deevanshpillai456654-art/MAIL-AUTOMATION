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
    assert payload["ai_gateway"]["enabled"] is False
    assert payload["ai_gateway"]["ai_on_demand_only"] is True


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


def test_client_runtime_policy_can_evaluate_requested_flags(tmp_path, monkeypatch):
    import backend.api.feature_flags as ff_mod

    db_path = str(tmp_path / "ff_test.db")
    monkeypatch.setattr(ff_mod, "_DB_PATH", db_path)
    ff_mod._init_db()

    client = _client()

    flag_id = "flag-client"
    now = ff_mod._now()
    con = ff_mod._conn()
    con.execute(
        f"INSERT INTO feature_flags ({','.join(ff_mod._FLAG_COLS)}) VALUES ({','.join(['?'] * len(ff_mod._FLAG_COLS))})",
        (flag_id, "Compact Inbox", "compact_inbox", "", "active", "frontend", "", now, now),
    )
    con.execute(
        f"INSERT INTO flag_environments ({','.join(ff_mod._ENV_COLS)}) VALUES ({','.join(['?'] * len(ff_mod._ENV_COLS))})",
        ("env-client", flag_id, "production", 1, 100.0, "", now),
    )
    con.commit()
    con.close()

    resp = client.get("/api/v1/frontend/clients/runtime-policy?environment=production&tenant_id=tenant-a&flags=compact_inbox")

    assert resp.status_code == 200
    assert resp.json()["flags"]["compact_inbox"]["enabled"] is True
