import re
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "backend" / "dashboard"


class _AssetReferenceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and attrs.get("href"):
            rel = (attrs.get("rel") or "").lower()
            if "stylesheet" in rel or rel == "manifest":
                self.refs.append(("href", attrs["href"]))
        elif tag == "script" and attrs.get("src"):
            self.refs.append(("src", attrs["src"]))
        elif tag == "img" and attrs.get("src"):
            self.refs.append(("src", attrs["src"]))


class _DuplicateAttributeParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.duplicates = []

    def handle_starttag(self, tag, attrs):
        seen = set()
        for name, _ in attrs:
            if name in seen:
                self.duplicates.append((self.getpos()[0], tag, name))
            seen.add(name)


def _asset_path_for(page: Path, ref: str) -> Path | None:
    if not ref or ref.startswith(("#", "data:", "mailto:", "javascript:", "http://", "https://")):
        return None
    clean = ref.split("?")[0]
    if clean.startswith("/dashboard/"):
        return DASHBOARD / clean.removeprefix("/dashboard/")
    if clean.startswith("/"):
        return None
    return page.parent / clean


def test_dashboard_defaults_to_light_theme():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    premium_js = (DASHBOARD / "premium-ui.js").read_text(encoding="utf-8")
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    assert '<html lang="en" data-theme="light">' in html
    assert 'name="theme-color"' not in html
    assert "<!-- light theme marker: #F6F8FB -->" in html
    assert "const theme = 'light';" in premium_js
    assert 'html[data-theme="light"]' in css
    assert "--bg:          #F6F8FB;" in css
    assert "fonts.googleapis.com" not in html


def test_rendered_dashboard_classes_have_matching_styles():
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    for selector in [
        ".provider-card",
        ".provider-card.active",
        ".thread-row",
        ".thread-row.active",
        ".thread-meta",
        ".thread-summary",
        ".thread-tags",
        ".report-card > span",
        ".report-card > strong",
        ".rule-item > div:first-child",
        "#messagePreview",
        ".ai34-hero",
        ".ai34-trust-row",
        ".ai34-pulse-card",
        ".chart-strip { display: flex; align-items: flex-end; gap: 3px; height: 80px;",
    ]:
        assert selector in css


def test_report_charts_normalize_values_before_rendering():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")

    assert "const max = Math.max(...vals, 1);" in js
    assert "Math.round((Number(v) / max) * 100)" in js


def test_brand_logo_asset_and_provider_visuals_present():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    assert (DASHBOARD / "assets" / "intemo-logo.png").is_file()
    assert (DASHBOARD / "assets" / "intemo-logo-mark.png").is_file()
    assert "/dashboard/assets/intemo-logo-mark.png" in html
    assert "brand-logo-img" in html
    assert '<span class="brand-tagline">INTEGRATING MOBILITY</span>' in html
    assert "PROVIDER_LOGO_IMAGES" in js
    assert "providerLogoMarkup" in js
    assert "provider-logo-img" in css
    for provider in [
        "gmail",
        "outlook",
        "microsoft365",
        "exchange",
        "yahoo",
        "zoho",
        "yandex",
        "icloud",
        "proton",
        "fastmail",
        "aol",
        "imap",
        "custom",
    ]:
        assert (DASHBOARD / "assets" / "providers" / f"{provider}.svg").is_file()
        assert f"/dashboard/assets/providers/{provider}.svg" in js


def test_named_frontend_pages_reference_existing_local_assets():
    missing = []
    for page in [
        DASHBOARD / "index.html",
        DASHBOARD / "scam-panel.html",
    ]:
        parser = _AssetReferenceParser()
        parser.feed(page.read_text(encoding="utf-8"))
        for attr, ref in parser.refs:
            path = _asset_path_for(page, ref)
            if path is not None and not path.exists():
                missing.append(f"{page.relative_to(ROOT)} {attr}={ref} -> {path.relative_to(ROOT)}")

    assert missing == []


def test_dashboard_has_apple_touch_icon_and_valid_activity_semantics():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")

    assert 'rel="apple-touch-icon"' in html
    assert "/dashboard/assets/apple-touch-icon.png" in html
    assert (DASHBOARD / "assets" / "apple-touch-icon.png").is_file()
    assert 'id="activityList" role="feed"' not in html
    assert 'id="activityList" role="list"' in html
    assert 'class="activity-item" role="listitem"' in js
    assert 'class="notification-item" role="listitem"' in js


def test_dashboard_and_scam_panel_html_have_no_duplicate_attributes():
    duplicates = []
    for page in [DASHBOARD / "index.html", DASHBOARD / "scam-panel.html"]:
        parser = _DuplicateAttributeParser()
        parser.feed(page.read_text(encoding="utf-8"))
        duplicates.extend(
            f"{page.relative_to(ROOT)}:{line} <{tag}> duplicate {name}"
            for line, tag, name in parser.duplicates
        )

    assert duplicates == []


def test_scam_panel_templates_do_not_emit_duplicate_class_attributes():
    source = (DASHBOARD / "scam-panel.html").read_text(encoding="utf-8")

    assert not re.search(r'class="[^"]*"\s+class="', source)


def test_scam_panel_uses_external_css_and_bound_actions():
    html = (DASHBOARD / "scam-panel.html").read_text(encoding="utf-8")

    assert '<link rel="stylesheet" href="/dashboard/scam-panel.css" />' in html
    assert (DASHBOARD / "scam-panel.css").is_file()
    assert "<style" not in html.lower()
    assert "onclick=" not in html.lower()
    assert ".style." not in html


def test_scam_panel_uses_external_runtime_script():
    html = (DASHBOARD / "scam-panel.html").read_text(encoding="utf-8")

    assert '<script src="/dashboard/scam-panel.js"></script>' in html
    assert (DASHBOARD / "scam-panel.js").is_file()
    assert "<script>\n'use strict';" not in html


def test_sidebar_logo_uses_clean_mark_with_text_tagline():
    logo_path = DASHBOARD / "assets" / "intemo-logo-mark.png"
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")
    with Image.open(logo_path).convert("RGBA") as logo:
        assert logo.width >= 520
        assert logo.height <= 170

    assert ".brand-tagline {" in css
    assert "font-style: italic;" in css
    assert "letter-spacing: 0.02em;" in css


def test_provider_logos_are_readable_and_custom_domain_stays_in_grid():
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in css
    assert "grid-template-columns: 50px minmax(0, 1fr);" in css
    assert ".provider-logo-frame {\n  width: 50px;\n  height: 50px;" in css
    assert ".provider-logo-img {\n  width: 44px;\n  height: 44px;" in css
    assert '.provider-card[data-provider="custom"] {' in css
    assert "grid-column: auto;" in css
    assert 'content: "Manual setup";' not in css
    assert '.provider-card[data-provider="custom"] b {' in css
    assert "white-space: normal;" in css


def test_dashboard_subtitle_workflow_and_brand_are_encoding_clean():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    clean_subtitle = "Operational overview - mailboxes, inbox health, AI processing, and automations."
    assert clean_subtitle in html
    assert f"PAGES.dashboard = ['Dashboard', '{clean_subtitle}'];" in js

    assert "workflow-arrow" in js
    assert "&rarr;" in js
    assert "renderWorkflowSteps" in js
    assert ".workflow-arrow" in css

    assert "min-height: 116px;" in css
    assert "width: 190px;" in css


def test_workflow_marketplace_cards_do_not_stretch_to_row_height():
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    workflow_grid = re.search(r"\.wf-template-grid\s*\{(?P<body>[^}]+)\}", css, re.S)
    assert workflow_grid is not None
    assert "display: grid;" in workflow_grid.group("body")
    assert "align-items: start;" in workflow_grid.group("body")


def test_admin_panel_has_spacious_layout_styles():
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    for selector in [
        ".admin-shell {",
        ".admin-tabs {",
        ".admin-actions {",
        ".control-grid {",
        ".control-grid label {",
        ".control-grid .check {",
        "#adminContent > h3 {",
        "#adminContent > .report-cards {",
        "#adminDetail.activity-list {",
    ]:
        assert selector in css

    assert "grid-template-columns: minmax(220px, 240px) minmax(0, 1fr);" in css
    assert "max-height: calc(100vh - 190px);" in css


def test_settings_panel_has_shared_inner_spacing_for_every_tab():
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    panel_rule = re.search(r"\.settings-panel\s*\{(?P<body>[^}]+)\}", css, re.S)
    assert panel_rule is not None
    assert "padding: var(--sp-5);" in panel_rule.group("body")
    assert "display: flex;" in panel_rule.group("body")
    assert "gap: var(--sp-4);" in panel_rule.group("body")

    assert ".settings-panel > h2" in css
    assert ".settings-panel > p" in css
    assert ".settings-panel > .form-grid," in css
    assert ".settings-panel > .settings-grid {" in css
    assert re.search(r"\.settings-panel > \.form-grid,\s*\.settings-panel > \.settings-grid\s*\{[^}]*padding: 0;", css, re.S)


def test_inbox_preview_is_larger_and_attachments_are_downloadable():
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")

    assert "grid-template-columns: 176px minmax(420px, 0.85fr) minmax(520px, 1.15fr);" in css
    for selector in [
        ".attachment-list",
        ".attachment-item",
        ".attachment-meta",
        ".attachment-download",
    ]:
        assert selector in css

    assert "function renderAttachments" in js
    assert "function attachmentDownloadHref" in js
    assert "<h3>Attachments</h3>" in js
    assert "attachment-download" in js
    assert "download=\"${esc(name)}\"" in js


def test_inbox_exposes_scam_feedback_controls_and_business_presets():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    assert "applyEmailVerdict" in js
    assert 'data-email-category="Scam"' in js
    assert 'data-email-category="Normal"' in js
    assert "state.savedFilter === 'scam'" in js
    assert "Scam filter" in js
    assert "Future emails from this sender will follow this decision." in js
    assert ".scam-flow" in css
    assert ".verdict-actions" in css
    assert 'class="preset-pack-card"' in js


def test_scam_filter_empty_state_clears_stale_preview():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    css = (DASHBOARD / "enterprise-ui.css").read_text(encoding="utf-8")

    assert "function renderEmptyPreview" in js
    assert "function renderThreadEmptyState" in js
    assert "function emptyStateForFilter" in js
    assert "No scam conversations" in js
    assert "Messages marked or detected as scams will appear here." in js
    assert "No ${label} conversations" in js
    assert "Messages matching this filter will appear here." in js
    assert "state.selectedEmail = null;" in js
    assert "renderEmptyPreview(emptyTitle, emptyBody);" in js
    assert ".thread-empty-state" in css
    assert "padding: 18px var(--sp-5);" in css
    assert ".thread-empty-state small" in css
