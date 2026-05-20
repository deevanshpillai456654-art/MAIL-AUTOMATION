from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


def test_low_resource_profile_disables_ai_and_heavy_autostart():
    from backend.core.runtime_control import RuntimeControl

    runtime = RuntimeControl(environ={"AIO_RUNTIME_PROFILE": "low_resource"})

    assert runtime.profile == "low_resource"
    assert runtime.ai_mode == "disabled"
    assert runtime.low_resource is True
    assert runtime.limits["max_workers"] == 1
    assert runtime.frontend_flags()["minimal_animations"] is True
    assert runtime.should_autostart_service("event_bus") is True
    assert runtime.should_autostart_service("agents") is False
    assert runtime.should_autostart_service("scheduled_reports") is False


def test_runtime_service_and_agent_env_overrides_are_explicit():
    from backend.core.runtime_control import RuntimeControl

    runtime = RuntimeControl(environ={
        "AIO_RUNTIME_PROFILE": "low_resource",
        "AIO_SERVICE_AGENTS": "true",
        "AIO_AGENT_INBOX_TRIAGE": "false",
        "AIO_SERVICE_AGENTS_AUTOSTART": "true",
    })

    assert runtime.is_service_enabled("agents") is True
    assert runtime.should_autostart_service("agents") is True
    assert runtime.is_agent_enabled("inbox_triage") is False


def test_router_registry_skips_disabled_optional_routers_in_low_resource():
    from backend.app.router_registry import RouterSpec, register_api_routers
    from backend.core.runtime_control import RuntimeControl

    core_router = APIRouter()
    heavy_router = APIRouter()

    @core_router.get("/core-ping")
    async def core_ping():
        return {"ok": True}

    @heavy_router.get("/assistant-ping")
    async def assistant_ping():
        return {"ok": True}

    app = FastAPI()
    register_api_routers(
        app,
        specs=(
            RouterSpec("core", core_router),
            RouterSpec("ai_assistant", heavy_router),
        ),
        runtime=RuntimeControl(environ={"AIO_RUNTIME_PROFILE": "low_resource"}),
    )
    paths = {route.path for route in app.routes}

    assert "/api/v1/core-ping" in paths
    assert "/api/v1/assistant-ping" not in paths


def test_runtime_api_exposes_profile_services_agents_and_frontend_flags(monkeypatch):
    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "low_resource")
    monkeypatch.setenv("AIO_SERVICE_AGENTS", "false")
    from backend.api.runtime_control import router as runtime_router
    from backend.api.session import router as session_router

    app = FastAPI()
    app.include_router(session_router, prefix="/api/v1")
    app.include_router(runtime_router, prefix="/api/v1")
    client = TestClient(app)
    client.post("/api/v1/session/bootstrap")

    profile = client.get("/api/v1/runtime/profile")
    services = client.get("/api/v1/runtime/services")
    agents = client.get("/api/v1/runtime/agents")

    assert profile.status_code == 200
    payload = profile.json()
    assert payload["profile"] == "low_resource"
    assert payload["ai_mode"] == "disabled"
    assert payload["frontend"]["minimal_animations"] is True
    assert services.status_code == 200
    assert services.json()["services"]["agents"]["enabled"] is False
    assert agents.status_code == 200
    assert agents.json()["agents"]["inbox_triage"]["enabled"] is False
