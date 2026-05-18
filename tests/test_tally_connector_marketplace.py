from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_tally_connector_is_available_in_accounting_marketplace():
    from backend.app.connector_panel_bridge import register_connector_panel
    from backend.auth.local_auth import require_local_auth

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    assert register_connector_panel(app) is True
    client = TestClient(app)

    response = client.get("/api/connector-panel/marketplace/connectors")

    assert response.status_code == 200
    connectors = {item["id"]: item for item in response.json()}
    tally = connectors["tally"]
    assert tally["name"] == "Tally"
    assert tally["category"] == "accounting"
    assert tally["supports_api_key"] is True
    assert tally["supports_webhook"] is True
    assert tally["queue_enabled"] is True
    assert "tally.voucher.created" in tally["events"]
    assert "tally.gst.mismatch" in tally["events"]
    assert "domain=tallysolutions.com" in tally["icon_url"]
    assert "TallyPrime" in tally["description"]


def test_tally_plugin_manifest_exists():
    from pathlib import Path
    import json

    manifest = Path("platform/connectors-panel/plugins/tally/plugin.json")
    module = Path("platform/connectors-panel/plugins/tally/module.py")

    data = json.loads(manifest.read_text("utf-8"))
    assert data["name"] == "tally_connector"
    assert data["category"] == "accounting"
    assert data["supports_api_key"] is True
    assert module.exists()
