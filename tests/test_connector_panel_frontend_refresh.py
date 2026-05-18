from pathlib import Path


def test_uninstall_refreshes_all_connector_panel_surfaces():
    app_js = Path("platform/connectors-panel/frontend/app.js").read_text("utf-8")

    start = app_js.index("async function uninstallConnector")
    end = app_js.index("//", start)
    body = app_js[start:end]

    assert "refreshConnectorSurfaces()" in body
    assert "loadInstalled()" in app_js
    assert "loadMarketplace()" in app_js
    assert "loadDashboard()" in app_js
    assert "updateSidebarVisibility" in app_js

