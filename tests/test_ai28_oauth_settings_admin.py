from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "backend" / "dashboard"


def test_dashboard_oauth_setup_and_provider_guidance_present():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    assert "function startOAuthFlow" in js
    assert "Save OAuth & Continue" in js
    assert "Gmail uses Google OAuth" in js
    assert "Yahoo mail requires an app password" in js
    assert "Zoho supports IMAP/SMTP" in js


def test_settings_and_admin_have_real_controls_not_empty_save_buttons():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    assert "Classification mode" in js
    assert "Minimum confidence" in js
    assert "Webhook URL" in js
    assert "Invite user" in js
    assert "Save Permissions" in js
    assert "Create Backup Checkpoint" in js


def test_oauth_missing_config_returns_428():
    from fastapi.testclient import TestClient
    from backend.main import app
    c = TestClient(app)
    for url in ["/api/v1/oauth/google/start", "/api/v1/oauth/microsoft/start"]:
        response = c.post(url)
        assert response.status_code == 428, f"{url} should return 428 when no credentials configured"
