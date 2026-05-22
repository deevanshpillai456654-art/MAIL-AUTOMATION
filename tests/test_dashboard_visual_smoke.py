from pathlib import Path
import json
import os

from PIL import Image


def test_dashboard_visual_smoke_plan_covers_core_views_and_scam_filter():
    from scripts import dashboard_visual_smoke as smoke

    names = [view.name for view in smoke.DASHBOARD_VIEWS]

    assert names == [
        "dashboard",
        "accounts",
        "inbox",
        "scam",
        "ai",
        "automations",
        "templates",
        "reports",
        "connectors",
        "workflows",
        "agents",
        "command",
        "admin",
        "settings",
    ]
    assert smoke.DASHBOARD_VIEWS[0].action == "initial"
    assert smoke.DASHBOARD_VIEWS[3].action == "filter"
    assert smoke.DASHBOARD_VIEWS[3].selector == '[data-filter="scam"]'


def test_dashboard_exposes_stable_scam_filter_chip_for_visual_smoke():
    html = Path("backend/dashboard/index.html").read_text(encoding="utf-8")
    js = Path("backend/dashboard/enterprise-ui.js").read_text(encoding="utf-8")

    assert 'data-filter="scam"' in html
    assert 'data-filter="scam"' in js
    assert "Scam" in js


def test_dashboard_visual_smoke_nav_selectors_target_primary_sidebar_buttons():
    from scripts import dashboard_visual_smoke as smoke

    for view in smoke.DASHBOARD_VIEWS:
        if view.action == "nav":
            assert view.selector.startswith(".main-nav > button.nav-btn")
            assert ".nav-nested" not in view.selector


def test_dashboard_visual_smoke_output_paths_are_stable(tmp_path):
    from scripts import dashboard_visual_smoke as smoke

    path = smoke.screenshot_path(tmp_path, "inbox/scam", "desktop 1440x900")

    assert path == tmp_path / "desktop-1440x900" / "inbox-scam.png"


def test_dashboard_visual_smoke_requires_playwright_with_clear_message(monkeypatch):
    from scripts import dashboard_visual_smoke as smoke

    assert smoke.SERVICE_STARTUP_WAIT_SECONDS >= 90
    assert "--lifespan" in smoke.SERVICE_START_COMMAND
    assert "off" in smoke.SERVICE_START_COMMAND
    assert 'wait_until="domcontentloaded"' in Path("scripts/dashboard_visual_smoke.py").read_text(encoding="utf-8")
    assert 'wait_until="networkidle"' not in Path("scripts/dashboard_visual_smoke.py").read_text(encoding="utf-8")

    def missing_import(name):
        raise ImportError("missing")

    monkeypatch.setattr(smoke.importlib, "import_module", missing_import)

    try:
        smoke.load_sync_playwright()
    except RuntimeError as exc:
        assert "Playwright is required" in str(exc)
        assert "pip install playwright" in str(exc)
        assert "python -m playwright install chromium" in str(exc)
    else:
        raise AssertionError("Expected missing Playwright to raise RuntimeError")


def test_dashboard_visual_smoke_disables_font_ready_wait_for_offline_screenshots():
    from scripts import dashboard_visual_smoke  # noqa: F401

    assert os.environ.get("PW_TEST_SCREENSHOT_NO_FONTS_READY") == "1"


def test_dashboard_visual_smoke_manifest_lists_generated_screenshots(tmp_path):
    from scripts import dashboard_visual_smoke as smoke

    records = [
        smoke.CaptureRecord("dashboard", "desktop", Path("dashboard.png")),
        smoke.CaptureRecord("accounts", "desktop", Path("accounts.png")),
    ]

    manifest = smoke.write_manifest(tmp_path, "http://127.0.0.1:4597/dashboard", records)

    assert manifest == tmp_path / "manifest.json"
    content = manifest.read_text(encoding="utf-8")
    assert '"base_url": "http://127.0.0.1:4597/dashboard"' in content
    assert '"view": "dashboard"' in content
    assert '"path": "dashboard.png"' in content


def test_package_exposes_dashboard_visual_smoke_command():
    package = json.loads(Path("package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["visual:smoke"] == "python -B scripts/dashboard_visual_smoke.py"


def test_dashboard_visual_smoke_rejects_blank_screenshots(tmp_path):
    from scripts import dashboard_visual_smoke as smoke

    blank = tmp_path / "blank.png"
    Image.new("RGB", (1440, 900), "white").save(blank)

    try:
        smoke.validate_screenshot(blank)
    except RuntimeError as exc:
        assert "blank" in str(exc)
    else:
        raise AssertionError("Expected blank screenshot to be rejected")
