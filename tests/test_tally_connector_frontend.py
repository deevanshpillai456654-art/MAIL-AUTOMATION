from pathlib import Path


def test_tally_connector_frontend_hooks_exist():
    app_js = Path("platform/connectors-panel/frontend/app.js").read_text("utf-8")
    html = Path("platform/connectors-panel/frontend/index.html").read_text("utf-8")

    assert "function isTallyConnector" in app_js
    assert "showTallyConfigureModal" in app_js
    assert "loadTallyDashboard" in app_js
    assert "Tally Host" in app_js
    assert "LAN Discovery" in app_js
    assert "Manual Sync" in app_js
    assert "Test Connection" in app_js
    assert 'data-section="tally"' in html
    assert 'id="sec-tally"' in html
