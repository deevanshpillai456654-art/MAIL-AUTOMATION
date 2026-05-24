import logging
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware


def test_api_router_registry_exposes_expected_domains():
    from backend.app.router_registry import API_ROUTER_SPECS

    names = {spec.name for spec in API_ROUTER_SPECS}

    assert len(API_ROUTER_SPECS) >= 28
    for name in {
        "core",
        "oauth",
        "rules",
        "security",
        "ai_enterprise",
        "enterprise_reports",
        "enterprise_admin",
        "threat_intelligence",
        "ai_assistant",
    }:
        assert name in names


def test_register_api_routers_preserves_public_api_paths():
    from backend.app.router_registry import register_api_routers

    app = FastAPI()
    register_api_routers(app)
    paths = {route.path for route in app.routes}

    for path in {
        "/api/v1/health",
        "/api/v1/rules",
        "/api/v1/security/status",
        "/api/v1/ai/runtime/status",
        "/api/v1/reports/summary",
        "/api/v1/admin/overview",
        "/api/v1/assistant/issues",
    }:
        assert path in paths


def test_static_route_registry_exposes_public_dashboard_pages():
    from backend.app.static_mounts import STATIC_PAGE_ROUTE_PATHS, resolve_dashboard_paths

    paths = resolve_dashboard_paths()

    assert paths.dashboard.exists()
    assert paths.dashboard.name == "dashboard"
    for path in {
        "/dashboard",
        "/assistant",
        "/setup",
        "/ai",
        "/ai-automation",
        "/ai-command-center.js",
        "/admin",
        "/security",
        "/taskpane.html",
        "/favicon.ico",
        "/",
    }:
        assert path in STATIC_PAGE_ROUTE_PATHS


def test_register_static_dashboard_routes_preserves_public_pages():
    from backend.app.static_mounts import register_static_dashboard_routes

    app = FastAPI()
    register_static_dashboard_routes(app)
    paths = {route.path for route in app.routes}

    for path in {
        "/dashboard",
        "/assistant",
        "/setup",
        "/ai",
        "/ai-automation",
        "/ai-command-center.js",
        "/admin",
        "/security",
        "/taskpane.html",
        "/favicon.ico",
        "/",
    }:
        assert path in paths


def test_register_static_dashboard_routes_mounts_ai_automation_frontend_and_api():
    from backend.app.static_mounts import register_static_dashboard_routes

    app = FastAPI()
    register_static_dashboard_routes(app)
    paths = {route.path for route in app.routes}

    assert "/ai-automation" in paths
    assert "/api/ai-automation/" in paths
    assert "/api/ai-automation/workflows/" in paths


def test_lifespan_factory_returns_context_manager_callable():
    from backend.app.lifespan import create_lifespan

    lifespan = create_lifespan(
        project_root=Path.cwd(),
        logger=logging.getLogger("tests.app_composition"),
    )
    context = lifespan(FastAPI())

    assert callable(lifespan)
    assert hasattr(context, "__aenter__")
    assert hasattr(context, "__aexit__")


def test_build_cors_settings_preserves_local_and_production_rules():
    from backend.app.middleware import build_cors_settings

    local = build_cors_settings(
        api_port=4597,
        configured_origins=[],
        is_production=False,
    )
    production = build_cors_settings(
        api_port=4597,
        configured_origins=["*", "https://console.example.com"],
        is_production=True,
    )

    assert local.allow_origins == [
        "http://127.0.0.1",
        "http://localhost",
        "http://127.0.0.1:4597",
        "http://localhost:4597",
    ]
    assert local.allow_origin_regex is not None
    assert "chrome-extension" in local.allow_origin_regex
    assert "localhost" in local.allow_origin_regex
    assert production.allow_origins == ["https://console.example.com"]
    assert production.allow_origin_regex is None


def test_register_app_middlewares_adds_transport_and_security_stack():
    from backend.api.middleware import RequestIDMiddleware
    from backend.app.middleware import register_app_middlewares

    app = FastAPI()
    register_app_middlewares(app)
    middleware_classes = {entry.cls for entry in app.user_middleware}

    assert CORSMiddleware in middleware_classes
    assert GZipMiddleware in middleware_classes
    assert RequestIDMiddleware in middleware_classes


def test_configure_logging_is_idempotent_for_service_log(tmp_path):
    from backend.app.logging_config import configure_logging

    logger = logging.getLogger("tests.app_composition.logging")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    log_file = configure_logging(tmp_path, "INFO", root_logger=logger)
    configure_logging(tmp_path, "DEBUG", root_logger=logger)

    service_file_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == log_file
    ]
    stream_handlers = [
        handler
        for handler in logger.handlers
        if type(handler) is logging.StreamHandler
    ]

    assert log_file == tmp_path / "service.log"
    assert log_file.parent.exists()
    assert logger.level == logging.DEBUG
    assert len(service_file_handlers) == 1
    assert len(stream_handlers) == 1

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def test_select_port_preserves_environment_override_and_writes_discovery(monkeypatch):
    from backend.app.launcher import select_port

    writes = []
    fake_config = SimpleNamespace(API_PORT=4597, API_HOST="127.0.0.1")
    fake_port_manager = SimpleNamespace(find_available_port=lambda: 4600)
    fake_discovery = SimpleNamespace(
        write_discovery=lambda port, host: writes.append((port, host))
    )
    monkeypatch.setenv("API_PORT", "4597")

    selected = select_port(fake_config, fake_port_manager, fake_discovery)

    assert selected == 4597
    assert fake_config.API_PORT == 4597
    assert writes == [(4597, "127.0.0.1")]


def test_select_port_uses_available_port_without_environment_override(monkeypatch):
    from backend.app.launcher import select_port

    writes = []
    fake_config = SimpleNamespace(API_PORT=4597, API_HOST="127.0.0.1")
    fake_port_manager = SimpleNamespace(find_available_port=lambda: 4600)
    fake_discovery = SimpleNamespace(
        write_discovery=lambda port, host: writes.append((port, host))
    )
    monkeypatch.delenv("API_PORT", raising=False)

    selected = select_port(fake_config, fake_port_manager, fake_discovery)

    assert selected == 4600
    assert fake_config.API_PORT == 4600
    assert writes == [(4600, "127.0.0.1")]
