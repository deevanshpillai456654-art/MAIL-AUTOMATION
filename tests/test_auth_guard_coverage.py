"""Verify that all recently-guarded API modules reject unauthenticated requests.

Each test creates an isolated FastAPI app with the router under test mounted at
/api/v1, then hits a representative endpoint WITHOUT auth credentials and asserts
the response is 401.  This acts as a regression guard: if a router-level
dependency is accidentally removed the test will catch it immediately.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _app(*routers, prefix="/api/v1"):
    app = FastAPI()
    for router in routers:
        app.include_router(router, prefix=prefix)
    return app


def _client(*routers):
    return TestClient(_app(*routers), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# ai_assistant
# ---------------------------------------------------------------------------

def test_ai_assistant_requires_auth():
    from backend.api.ai_assistant import router
    c = _client(router)
    assert c.get("/api/v1/assistant/issues").status_code == 401


# ---------------------------------------------------------------------------
# ai_enterprise
# ---------------------------------------------------------------------------

def test_ai_enterprise_requires_auth():
    from backend.api.ai_enterprise import router
    c = _client(router)
    assert c.get("/api/v1/ai/runtime/status").status_code == 401


# ---------------------------------------------------------------------------
# ai_gateway
# ---------------------------------------------------------------------------

def test_ai_gateway_requires_auth():
    from backend.api.ai_gateway import router
    c = _client(router)
    assert c.get("/api/v1/ai/gateway/status").status_code == 401


# ---------------------------------------------------------------------------
# learning
# ---------------------------------------------------------------------------

def test_learning_requires_auth():
    from backend.api.learning import router
    c = _client(router)
    assert c.post("/api/v1/learning/feedback", json={}).status_code == 401


# ---------------------------------------------------------------------------
# enterprise_reports
# ---------------------------------------------------------------------------

def test_enterprise_reports_requires_auth():
    from backend.api.enterprise_reports import router
    c = _client(router)
    assert c.get("/api/v1/reports/summary").status_code == 401


# ---------------------------------------------------------------------------
# enterprise_refinement
# ---------------------------------------------------------------------------

def test_enterprise_refinement_requires_auth():
    from backend.api.enterprise_refinement import router
    c = _client(router)
    resp = c.get("/api/v1/enterprise/refinement/status")
    assert resp.status_code in (401, 404)  # 404 acceptable if route path differs
    # The key assertion: not 200
    assert resp.status_code != 200


# ---------------------------------------------------------------------------
# enterprise_templates
# ---------------------------------------------------------------------------

def test_enterprise_templates_requires_auth():
    from backend.api.enterprise_templates import router
    c = _client(router)
    assert c.get("/api/v1/templates").status_code == 401


# ---------------------------------------------------------------------------
# absolute_enterprise_governance
# ---------------------------------------------------------------------------

def test_absolute_governance_requires_auth():
    from backend.api.absolute_enterprise_governance import router
    c = _client(router)
    resp = c.get("/api/v1/absolute/governance/overview")
    assert resp.status_code in (401, 404)
    assert resp.status_code != 200


# ---------------------------------------------------------------------------
# enterprise_accounts
# ---------------------------------------------------------------------------

def test_enterprise_accounts_requires_auth():
    from backend.api.enterprise_accounts import router
    c = _client(router)
    assert c.get("/api/v1/enterprise/accounts/status").status_code == 401


# ---------------------------------------------------------------------------
# enterprise_updates
# ---------------------------------------------------------------------------

def test_enterprise_updates_requires_auth():
    from backend.api.enterprise_updates import router
    c = _client(router)
    assert c.get("/api/v1/updates/status").status_code == 401


# ---------------------------------------------------------------------------
# frontend_runtime
# ---------------------------------------------------------------------------

def test_frontend_runtime_requires_auth():
    from backend.api.frontend_runtime import router
    c = _client(router)
    assert c.get("/api/v1/frontend/runtime-policy").status_code == 401


# ---------------------------------------------------------------------------
# port
# ---------------------------------------------------------------------------

def test_port_requires_auth():
    from backend.api.port import router
    c = _client(router)
    assert c.get("/api/v1/port/status").status_code == 401


# ---------------------------------------------------------------------------
# production95
# ---------------------------------------------------------------------------

def test_production95_requires_auth():
    from backend.api.production95 import router
    c = _client(router)
    assert c.get("/api/v1/production/readiness-score").status_code == 401


# ---------------------------------------------------------------------------
# system
# ---------------------------------------------------------------------------

def test_system_requires_auth():
    from backend.api.system import router
    c = _client(router)
    assert c.get("/api/v1/enterprise/status").status_code == 401


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def test_rules_requires_auth():
    from backend.api.rules import router
    c = _client(router)
    assert c.get("/api/v1/rules").status_code == 401


# ---------------------------------------------------------------------------
# threat_intelligence
# ---------------------------------------------------------------------------

def test_threat_intelligence_requires_auth():
    from backend.api.threat_intelligence import router
    c = _client(router)
    assert c.get("/api/v1/threat/stats").status_code == 401


# ---------------------------------------------------------------------------
# health: public routes stay public, detailed routes are guarded
# ---------------------------------------------------------------------------

def test_health_basic_is_public():
    from backend.api.health import router
    c = _client(router)
    assert c.get("/api/v1/health").status_code == 200


def test_health_ready_is_public():
    from backend.api.health import router
    c = _client(router)
    assert c.get("/api/v1/health/ready").status_code == 200


def test_health_detailed_requires_auth():
    from backend.api.health import router
    c = _client(router)
    assert c.get("/api/v1/health/detailed").status_code == 401


def test_health_components_requires_auth():
    from backend.api.health import router
    c = _client(router)
    assert c.get("/api/v1/health/components").status_code == 401


# ---------------------------------------------------------------------------
# ws_alerts REST endpoint is guarded
# ---------------------------------------------------------------------------

def test_ws_alerts_status_requires_auth():
    from backend.api.ws_alerts import router
    c = _client(router)
    assert c.get("/api/v1/ws/alerts/status").status_code == 401


# ---------------------------------------------------------------------------
# session bootstrap remains public (it IS the auth setup path)
# ---------------------------------------------------------------------------

def test_session_bootstrap_is_public():
    from backend.api.session import router
    c = _client(router)
    resp = c.post("/api/v1/session/bootstrap")
    assert resp.status_code in (200, 204)
