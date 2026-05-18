from pathlib import Path


def test_main_dashboard_installed_connector_nav_is_state_driven():
    html = Path("backend/dashboard/index.html").read_text("utf-8")
    css = Path("backend/dashboard/enterprise-ui.css").read_text("utf-8")
    js = Path("backend/dashboard/enterprise-ui.js").read_text("utf-8")

    assert 'data-view="ocr" data-requires-connector="ocr_engine"' not in html
    assert "[hidden] { display: none !important; }" in css
    assert "/api/connector-panel/marketplace/connectors?tenant_id=default" in js
    assert "refreshConnectorFeatureNavigation" in js
    assert 'id="installedConnectorNav"' in html
    assert "renderInstalledConnectorNavigation" in js
    assert "data-connector-nav-id" in js
    assert "CONNECTOR_FEATURE_VIEWS" in js
    assert "ocr_engine: 'ocr'" in js
    assert "nativeConnectorIds" not in js
    assert "openConnectorFromMainNav" in js
    assert "data-requires-connector-category" in js
    assert "data-requires-active-connector" in js
    assert "connectors:changed" in js
    assert "showView('connectors')" in js


def test_connector_panel_notifies_parent_after_connector_state_changes():
    app_js = Path("platform/connectors-panel/frontend/app.js").read_text("utf-8")

    assert "function notifyParentConnectorChange()" in app_js
    assert "window.parent.postMessage({ type: 'connectors:changed' }, window.location.origin)" in app_js
    assert "notifyParentConnectorChange()" in app_js


def test_connector_panel_sidebar_sections_are_declaratively_connector_gated():
    html = Path("platform/connectors-panel/frontend/index.html").read_text("utf-8")
    app_js = Path("platform/connectors-panel/frontend/app.js").read_text("utf-8")

    assert 'id="sidebar-erp" data-requires-connector-category="erp accounting"' in html
    assert 'id="sidebar-crm" data-requires-connector-category="crm"' in html
    assert 'id="sidebar-tracking" data-requires-connector-category="tracking shipping"' in html
    assert 'id="sidebar-support" data-requires-connector-category="support"' in html
    assert 'id="sidebar-automation" data-requires-active-connector' in html
    assert 'id="sidebar-operations" data-requires-active-connector' in html
    assert "document.querySelectorAll('[data-requires-connector-category], [data-requires-active-connector]')" in app_js
    assert "saveConnectorConfig" in app_js
    assert "refreshConnectorSurfaces()" in app_js[app_js.index("async function saveConnectorConfig"):app_js.index("async function testConnector")]


def test_main_dashboard_renderer_has_no_connector_allowlist():
    marketplace = Path("platform/connectors-panel/backend/marketplace.py").read_text("utf-8")
    js = Path("backend/dashboard/enterprise-ui.js").read_text("utf-8")

    connector_ids = {
        line.split('"id": "', 1)[1].split('"', 1)[0]
        for line in marketplace.splitlines()
        if '"id": "' in line
    }

    assert len(connector_ids) >= 40
    assert ".filter(connector => connector && connector.is_installed)" in js
    assert ".filter(connector => connector.id)" in js
    assert "connector.id && connector.id !==" not in js
    assert "nativeConnectorIds" not in js
