import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "backend" / "dashboard"
CONNECTORS = ROOT / "platform" / "connectors-panel" / "frontend"
AI_AUTOMATION = ROOT / "platform" / "ai-automation" / "frontend"


class _IdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attrs_map = dict(attrs)
        if attrs_map.get("id"):
            self.ids.append((attrs_map["id"], self.getpos()[0]))


def _function_body(source: str, name: str) -> str:
    start = source.index(f"function {name}")
    brace = source.index("{", start)
    depth = 0
    for pos in range(brace, len(source)):
        if source[pos] == "{":
            depth += 1
        elif source[pos] == "}":
            depth -= 1
            if depth == 0:
                return source[start:pos + 1]
    raise AssertionError(f"Could not extract function {name}")


def test_inbox_desktop_layout_is_not_overridden_to_two_columns():
    hybrid_css = (DASHBOARD / "hybrid-theme.css").read_text(encoding="utf-8")

    assert ".inbox-layout" in hybrid_css
    assert ".inbox-layout {\n  display: grid;\n  grid-template-columns: 320px 1fr;" not in hybrid_css
    assert ".inbox-layout { grid-template-columns: 280px 1fr; }" not in hybrid_css
    assert "minmax(420px, 0.85fr)" in hybrid_css
    assert "minmax(520px, 1.15fr)" in hybrid_css


def test_dashboard_static_ids_are_unique_and_sidebar_symbol_buttons_are_named():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    parser = _IdParser()
    parser.feed(html)
    duplicate_ids = sorted(id_value for id_value, count in Counter(id_value for id_value, _ in parser.ids).items() if count > 1)

    assert duplicate_ids == []
    assert 'id="sidebarCreateFolderBtn" type="button" aria-label="Create folder"' in html
    assert 'id="sidebarCreateLabelBtn" type="button" aria-label="Create label"' in html
    assert 'id="sloFormWindow" aria-label="SLO reporting window"' in html
    assert 'id="sloTransitionStatus" aria-label="SLO transition status"' in html


def test_rule_lifecycle_hides_samples_and_actions_are_wired():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")

    assert "function isSampleRule" in js
    assert ".filter(rule => !isSampleRule(rule))" in js
    assert 'data-rule-action="pause"' in js
    assert 'data-rule-action="duplicate"' in js
    assert 'data-rule-action="archive"' in js
    assert "handleRuleLifecycleAction" in js


def test_rule_simulation_does_not_create_real_rule_from_unsaved_draft():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    body = _function_body(js, "simulateRule")

    assert "api('/api/v1/rules', {method:'POST'" not in body
    assert "/api/v1/rules/simulate-draft" in body


def test_connector_panel_modal_controls_are_accessible_and_encoding_clean():
    app_js = (CONNECTORS / "app.js").read_text(encoding="utf-8")

    assert "Ã" not in app_js
    assert "â" not in app_js
    assert "�" not in app_js
    unnamed_close_buttons = re.findall(r'<button class="modal-close"(?![^>]*(?:aria-label|title))[^>]*>', app_js)
    assert unnamed_close_buttons == []
    assert '<select id="tallyMode" aria-label="Connection method" title="Connection method">' in app_js
    assert '<select id="tallySyncInterval" aria-label="Sync interval" title="Sync interval">' in app_js


def test_dashboard_navigation_clears_stale_toasts_between_views():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    show_view = _function_body(js, "showView")

    assert "function clearToasts" in js
    assert "clearToasts();" in show_view


def test_frontend_static_pages_do_not_use_fake_hash_links_or_mojibake():
    checked = [
        DASHBOARD / "setup.html",
        DASHBOARD / "setup.js",
        DASHBOARD / "enterprise-ui.js",
        CONNECTORS / "index.html",
    ]
    for path in checked:
        source = path.read_text(encoding="utf-8")
        assert 'href="#"' not in source, path
        for marker in ("\u00e2\u02c6", "\u00e2\u20ac", "\u00c3", "\ufffd"):
            assert marker not in source, path


def test_frontend_sources_have_no_mojibake_markers():
    checked_roots = [DASHBOARD, CONNECTORS, AI_AUTOMATION]
    markers = ("\u00e2", "\u00c3", "\u00c2", "\u00f0", "\ufffd")
    offenders = []
    for root in checked_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".css", ".html", ".js"}:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            if any(marker in source for marker in markers):
                offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_connector_panel_uses_intemo_branding_and_real_logo():
    html = (CONNECTORS / "index.html").read_text(encoding="utf-8")
    css = (CONNECTORS / "styles.css").read_text(encoding="utf-8")

    assert "MailPilot" not in html
    assert "Enterprise OS" not in html
    assert "<title>INTEMO - Connector Operations</title>" in html
    assert 'src="/dashboard/assets/intemo-logo-mark.png"' in html
    assert "sidebar-brand-logo" in css


def test_frontend_surfaces_do_not_show_legacy_mailpilot_branding():
    offenders = []
    for root in [DASHBOARD, CONNECTORS, AI_AUTOMATION]:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".html", ".js", ".css"}:
                continue
            if "MailPilot" in path.read_text(encoding="utf-8", errors="replace"):
                offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []


def test_connector_marketplace_api_copy_uses_intemo_branding():
    marketplace = (ROOT / "platform" / "connectors-panel" / "backend" / "marketplace.py").read_text(encoding="utf-8")
    router = (ROOT / "platform" / "connectors-panel" / "backend" / "router.py").read_text(encoding="utf-8")

    assert "MailPilot" not in marketplace
    assert "MailPilot" not in router
    assert '"author": "INTEMO"' in marketplace


def test_generated_dashboard_select_controls_have_accessible_names():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    unnamed_selects = re.findall(r"<select(?![^>]*(?:aria-label|aria-labelledby|title))[^>]*>", js)

    assert unnamed_selects == []


def test_static_frontend_select_controls_have_accessible_names():
    offenders = []
    for path in [
        DASHBOARD / "index.html",
        CONNECTORS / "index.html",
        AI_AUTOMATION / "index.html",
    ]:
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"<select(?![^>]*(?:aria-label|aria-labelledby|title))[^>]*>", source):
            offenders.append(f"{path.relative_to(ROOT).as_posix()}:{source[:match.start()].count(chr(10)) + 1}")

    assert offenders == []


def test_ai_automation_navigation_uses_real_controls_and_brand_logo():
    html = (AI_AUTOMATION / "index.html").read_text(encoding="utf-8")
    css = (AI_AUTOMATION / "styles.css").read_text(encoding="utf-8")

    assert '<img class="logo-img" src="/dashboard/assets/intemo-logo-mark.png" alt="INTEMO"' in html
    assert '<div class="logo-icon">' not in html
    assert '<div class="nav-item' not in html
    assert '<button class="nav-item active" type="button" data-page="dashboard" aria-current="page">' in html
    assert '<button class="tab active" type="button" data-settings-tab="general">' in html
    assert ".logo-img" in css


def test_ai_automation_navigation_tracks_current_page_for_accessibility():
    html = (AI_AUTOMATION / "index.html").read_text(encoding="utf-8")
    js = (AI_AUTOMATION / "app.js").read_text(encoding="utf-8")

    assert '<button class="nav-item active" type="button" data-page="dashboard" aria-current="page">' in html
    assert "removeAttribute('aria-current')" in js
    assert "setAttribute('aria-current', 'page')" in js


def test_ai_automation_generated_markup_uses_css_classes_not_inline_style_attributes():
    js = (AI_AUTOMATION / "app.js").read_text(encoding="utf-8")

    assert " style=" not in js
    assert ".style.cssText" not in js


def test_advanced_admin_views_have_page_metadata():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")

    for page_key, title in {
        "licenses": "Licenses",
        "budgets": "Budgets",
        "vendors": "Vendors",
        "assets": "Resources",
    }.items():
        assert f"PAGES.{page_key} " in js or f"PAGES['{page_key}']" in js
        assert title in js


def test_advanced_admin_table_rows_match_visible_headers():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")

    assert "renderEmptyRow(tbody, { colspan: 9, title: 'No risks found' })" in js
    assert "<td>${r.likelihood||'-'}</td><td>${r.impact||'-'}</td>" in js
    assert "<td><span class=\"badge ${r.risk_level==='critical'" in js
    assert "<td>${_esc(r.owner||'-')}</td>" in js

    for name in ("certificates", "configs", "licenses", "budgets"):
        assert re.search(r"title\s*:\s*'No " + re.escape(name) + r" found'", js)
    assert "r.days_until_expiry!=null?r.days_until_expiry:'-'" in js
    assert "r.auto_renew?'Yes':'No'" in js
    assert "r.version_count||1" in js
    assert "r.seats_used||0" in js
    assert "r.utilization_pct!=null?r.utilization_pct.toFixed(1)+'%':'0.0%'" in js


def test_sidebar_uses_full_brand_logo_not_square_icon_treatment():
    css = (DASHBOARD / "hybrid-theme.css").read_text(encoding="utf-8")

    assert ".brand-block-branded .brand-logo-wrap" in css
    assert "background: transparent;" in css
    assert "width: min(188px, 100%);" in css
    assert ".brand-block-branded .brand-logo-img" in css


def test_advanced_navigation_uses_calm_business_labels():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")

    assert 'data-view="risks"        type="button" data-role-min="workspace_admin">Risk Overview</button>' in html
    assert 'data-view="certificates" type="button" data-role-min="workspace_admin">Secure Access</button>' in html
    assert 'data-view="configs"      type="button" data-role-min="workspace_admin">Workspace Settings</button>' in html
    assert "Workspace Config" not in html


def test_frontend_css_does_not_use_negative_letter_spacing():
    checked_roots = [DASHBOARD, CONNECTORS, AI_AUTOMATION]
    offenders = []
    for root in checked_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".css", ".html", ".js"}:
                continue
            source = path.read_text(encoding="utf-8", errors="replace")
            if re.search(r"letter-spacing\s*:\s*-", source):
                offenders.append(path.relative_to(ROOT).as_posix())

    assert offenders == []
