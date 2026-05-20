"""Runtime policy tests for the 16 ITSM/operations/security services
added in the second wave of service-policy registrations."""
from __future__ import annotations

from fastapi import APIRouter, FastAPI
from backend.app.router_registry import RouterSpec, register_api_routers
from backend.core.runtime_control import RuntimeControl


# ── Service policies exist for all 16 new services ────────────────────────────

_NEW_SERVICES = [
    ("runbooks",             "runbooks"),
    ("change_management",    "change_management"),
    ("problem_management",   "problem_management"),
    ("service_catalog",      "service_catalog"),
    ("deployments",          "deployments"),
    ("asset_management",     "asset_management"),
    ("knowledge_base",       "knowledge_base"),
    ("capacity_planning",    "capacity_planning"),
    ("vendor_management",    "vendor_management"),
    ("feature_flags",        "feature_flags"),
    ("budget_tracking",      "budget_tracking"),
    ("license_management",   "license_management"),
    ("config_management",    "config_management"),
    ("certificate_management", "certificate_management"),
    ("risk_register",        "risk_register"),
    ("slo_management",       "slo_management"),
]


def test_all_new_services_have_policies():
    from backend.core.runtime_control import SERVICE_POLICIES
    for service_id, router_name in _NEW_SERVICES:
        assert service_id in SERVICE_POLICIES, f"Missing service policy: {service_id}"
        policy = SERVICE_POLICIES[service_id]
        assert policy.router_name == router_name, (
            f"{service_id}: expected router_name={router_name!r}, got {policy.router_name!r}"
        )


def test_new_services_enabled_in_standard_profile():
    rt = RuntimeControl(environ={"AIO_RUNTIME_PROFILE": "standard"})
    for service_id, _ in _NEW_SERVICES:
        assert rt.is_service_enabled(service_id), f"{service_id} should be enabled in standard profile"


def test_new_services_enabled_in_enterprise_profile():
    rt = RuntimeControl(environ={"AIO_RUNTIME_PROFILE": "enterprise"})
    for service_id, _ in _NEW_SERVICES:
        assert rt.is_service_enabled(service_id), f"{service_id} should be enabled in enterprise profile"


def test_most_new_services_disabled_in_low_resource():
    rt = RuntimeControl(environ={"AIO_RUNTIME_PROFILE": "low_resource"})
    # feature_flags and config_management are lightweight essentials — stay on
    always_on = {"feature_flags", "config_management"}
    for service_id, _ in _NEW_SERVICES:
        if service_id in always_on:
            assert rt.is_service_enabled(service_id), f"{service_id} should stay on in low_resource"
        else:
            assert not rt.is_service_enabled(service_id), (
                f"{service_id} should be disabled in low_resource"
            )


def test_env_override_re_enables_service_in_low_resource():
    rt = RuntimeControl(environ={
        "AIO_RUNTIME_PROFILE": "low_resource",
        "AIO_SERVICE_RUNBOOKS": "true",
    })
    assert rt.is_service_enabled("runbooks") is True


def test_env_override_disables_service_in_standard():
    rt = RuntimeControl(environ={
        "AIO_RUNTIME_PROFILE": "standard",
        "AIO_SERVICE_RISK_REGISTER": "false",
    })
    assert rt.is_service_enabled("risk_register") is False


# ── Router toggle via register_api_routers ────────────────────────────────────

def _make_spec(name: str) -> tuple[RouterSpec, str]:
    r = APIRouter()
    endpoint_path = f"/{name}-ping"

    @r.get(endpoint_path)
    async def _ping():
        return {"ok": True}

    return RouterSpec(name, r), f"/api/v1{endpoint_path}"


def test_routers_are_skipped_in_low_resource_by_default():
    """Operations routers should not be registered under low_resource."""
    rt = RuntimeControl(environ={"AIO_RUNTIME_PROFILE": "low_resource"})
    specs = []
    paths = {}
    for service_id, _ in _NEW_SERVICES:
        spec, path = _make_spec(service_id)
        specs.append(spec)
        paths[service_id] = path

    app = FastAPI()
    register_api_routers(app, specs=specs, runtime=rt)
    registered = {route.path for route in app.routes}

    always_on = {"feature_flags", "config_management"}
    for service_id, _ in _NEW_SERVICES:
        if service_id in always_on:
            assert paths[service_id] in registered, f"{service_id} router should be registered in low_resource"
        else:
            assert paths[service_id] not in registered, (
                f"{service_id} router should be skipped in low_resource"
            )


def test_all_new_routers_registered_in_standard():
    rt = RuntimeControl(environ={"AIO_RUNTIME_PROFILE": "standard"})
    specs = []
    paths = {}
    for service_id, _ in _NEW_SERVICES:
        spec, path = _make_spec(service_id)
        specs.append(spec)
        paths[service_id] = path

    app = FastAPI()
    register_api_routers(app, specs=specs, runtime=rt)
    registered = {route.path for route in app.routes}

    for service_id in paths:
        assert paths[service_id] in registered, f"{service_id} router should be registered in standard"


def test_individual_disable_via_env_skips_router():
    rt = RuntimeControl(environ={
        "AIO_RUNTIME_PROFILE": "standard",
        "AIO_SERVICE_SLO_MANAGEMENT": "false",
    })
    spec, path = _make_spec("slo_management")
    app = FastAPI()
    register_api_routers(app, specs=[spec], runtime=rt)
    registered = {route.path for route in app.routes}
    assert path not in registered


def test_individual_enable_via_env_allows_low_resource_router():
    rt = RuntimeControl(environ={
        "AIO_RUNTIME_PROFILE": "low_resource",
        "AIO_SERVICE_KNOWLEDGE_BASE": "true",
    })
    spec, path = _make_spec("knowledge_base")
    app = FastAPI()
    register_api_routers(app, specs=[spec], runtime=rt)
    registered = {route.path for route in app.routes}
    assert path in registered


# ── Module status endpoint reflects new services ─────────────────────────────

def test_module_status_includes_new_services(monkeypatch):
    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "standard")
    from backend.api.runtime_control import router as runtime_router
    from backend.api.session import router as session_router
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(session_router, prefix="/api/v1")
    app.include_router(runtime_router, prefix="/api/v1")
    client = TestClient(app)
    client.post("/api/v1/session/bootstrap")

    resp = client.get("/api/v1/runtime/services")
    assert resp.status_code == 200
    services = resp.json()["services"]

    for service_id, _ in _NEW_SERVICES:
        assert service_id in services, f"service {service_id!r} missing from /runtime/services"
        assert services[service_id]["enabled"] is True
