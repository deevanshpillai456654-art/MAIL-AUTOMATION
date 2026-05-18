from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_marketplace_api_exposes_real_brand_image_urls_for_all_connectors():
    from backend.app.connector_panel_bridge import register_connector_panel
    from backend.auth.local_auth import require_local_auth

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    assert register_connector_panel(app) is True
    client = TestClient(app)

    response = client.get("/api/connector-panel/marketplace/connectors")

    assert response.status_code == 200
    connectors = response.json()
    assert connectors
    by_id = {connector["id"]: connector for connector in connectors}
    for connector in connectors:
        icon_url = connector.get("icon_url")
        assert icon_url
        assert icon_url.startswith("https://www.google.com/s2/favicons?")
    assert "domain=slack.com" in by_id["slack"]["icon_url"]
    assert "domain=openai.com" in by_id["openai"]["icon_url"]
    assert "domain=shopify.com" in by_id["shopify"]["icon_url"]


def test_connector_panel_csp_allows_colored_brand_icon_cdn():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.middleware import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/connectors-panel/")
    async def panel():
        return {"ok": True}

    response = TestClient(app).get("/connectors-panel/")

    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "img-src" in csp
    assert "https://www.google.com" in csp


def test_marketplace_descriptions_are_specific_and_actionable():
    from backend.app.connector_panel_bridge import register_connector_panel
    from backend.auth.local_auth import require_local_auth

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    assert register_connector_panel(app) is True
    client = TestClient(app)

    connectors = client.get("/api/connector-panel/marketplace/connectors").json()
    by_id = {connector["id"]: connector for connector in connectors}

    assert by_id["quickbooks"]["description"] == (
        "Sync QuickBooks Online invoices, payments, expenses, and accounts for finance handoff and reconciliation."
    )
    assert by_id["zendesk"]["description"] == (
        "Create and update Zendesk tickets, route SLA breaches, and attach customer email context to support work."
    )
    assert by_id["anthropic"]["description"] == (
        "Use Claude for long email threads, policy checks, document analysis, and structured decision support."
    )
    vague_terms = ("integration for", "automation", "intelligent")
    assert not any(term in by_id["google_gemini"]["description"].lower() for term in vague_terms)
