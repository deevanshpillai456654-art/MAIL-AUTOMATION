from pathlib import Path


def test_main_dashboard_ocr_nav_is_connector_gated():
    html = Path("backend/dashboard/index.html").read_text("utf-8")
    css = Path("backend/dashboard/enterprise-ui.css").read_text("utf-8")
    js = Path("backend/dashboard/enterprise-ui.js").read_text("utf-8")

    assert 'data-view="ocr" data-requires-connector="ocr_engine"' in html
    assert 'hidden aria-hidden="true"' in html
    assert "[hidden] { display: none !important; }" in css
    assert "/api/connector-panel/marketplace/connectors?tenant_id=default" in js
    assert "refreshConnectorFeatureNavigation" in js
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
