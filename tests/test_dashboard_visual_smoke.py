from pathlib import Path
import json

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
        "admin",
        "settings",
    ]
    assert smoke.DASHBOARD_VIEWS[0].action == "initial"
    assert smoke.DASHBOARD_VIEWS[3].action == "filter"
    assert smoke.DASHBOARD_VIEWS[3].selector == '[data-filter="scam"]'


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
