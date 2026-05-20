from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "backend" / "dashboard"


def test_dashboard_oauth_setup_and_provider_guidance_present():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    assert "function startOAuthFlow" in js
    assert "function oauthStartUrlWithEmail" in js
    assert "parsed.searchParams.set('email', email)" in js
    assert "window.location.assign(target)" in js
    assert "window.open(oauthStartUrlWithEmail" not in js
    assert "Save OAuth app details" in js
    assert "function useAppPasswordFlow" in js
    assert "data-use-app-password" in js
    assert "Google OAuth can be blocked" in js
    assert "Google Cloud OAuth consent screen" in js
    assert "Enter the email address before configuring or starting OAuth." in js
    assert "Continue OAuth for entered email" in js
    assert "data-continue-oauth" in js
    assert "email_address: accountEmail" in js
    assert "Gmail uses Google OAuth" in js
    assert "Yahoo mail requires an app password" in js
    assert "Zoho supports IMAP/SMTP" in js


def test_frontend_oauth_setup_is_separate_from_start_and_sync():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    save_fn = js[js.index("async function saveInlineOAuthSetup"):js.index("async function testAccountConnection")]
    setup_fn = js[js.index("function renderOAuthSetupPanel"):js.index("function renderProviders")]
    assert "startOAuthFlow" not in save_fn
    assert "Save OAuth app details" in setup_fn
    assert "Continue OAuth for entered email" in setup_fn
    assert "updateOAuthSubmitState" in js
    assert "submit.disabled = oauthActive;" in js


def test_settings_and_admin_have_real_controls_not_empty_save_buttons():
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    assert "Classification mode" in js
    assert "Minimum confidence" in js
    assert "Webhook URL" in js
    assert "Invite user" in js
    assert "Save Permissions" in js
    assert "Create Backup Checkpoint" in js


def test_oauth_start_requires_email_before_config_lookup():
    from fastapi.testclient import TestClient
    from backend.main import app
    c = TestClient(app)
    for url in ["/api/v1/oauth/google/start", "/api/v1/oauth/microsoft/start"]:
        response = c.post(url)
        assert response.status_code == 400, f"{url} should require an email before OAuth starts"
        assert response.json()["detail"]["message"] == "Enter the email address before configuring or starting OAuth."


def test_gmail_provider_metadata_explains_google_consent_requirements():
    from backend.auth.provider_config import OAUTH_GROUPS

    notes = OAUTH_GROUPS["gmail"]["notes"]
    assert "test user" in notes
    assert "verification" in notes
