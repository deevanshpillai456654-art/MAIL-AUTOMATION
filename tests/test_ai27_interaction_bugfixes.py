from __future__ import annotations
import asyncio
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "backend" / "dashboard"


def test_dashboard_buttons_and_sections_are_wired():
    html = (DASHBOARD / "index.html").read_text(encoding="utf-8")
    js = (DASHBOARD / "enterprise-ui.js").read_text(encoding="utf-8")
    assert "generateReportBtn" in html
    assert "data-admin-index" in js and "renderAdminSection" in js
    assert "renderSettings" in js and "patchForm" in js
    assert "Save & Start Sync" in html
    assert "PROVIDER_DEFAULTS" in js
    for provider in ["gmail", "outlook", "microsoft365", "yahoo", "zoho", "exchange", "imap", "custom"]:
        assert provider in js
    for handler in ["saveAccount", "startAccountSync", "reconnectAccount", "previewPatch", "submitPatch", "loadReports"]:
        assert handler in js


def test_provider_detection_returns_imap_smtp_defaults():
    from backend.api.routes import detect_mail_provider
    cases = {
        "ops@gmail.com": ("gmail", "imap.gmail.com", "smtp.gmail.com"),
        "ops@outlook.com": ("outlook", "outlook.office365.com", "smtp.office365.com"),
        "ops@yahoo.com": ("yahoo", "imap.mail.yahoo.com", "smtp.mail.yahoo.com"),
        "ops@zoho.com": ("zoho", "imap.zoho.com", "smtp.zoho.com"),
        "support@company.in": ("custom", "imap.company.in", "smtp.company.in"),
    }
    for email, expected in cases.items():
        detected = detect_mail_provider(email)
        assert detected["provider"] == expected[0]
        assert detected["imap_host"] == expected[1]
        assert detected["smtp_host"] == expected[2]
        assert detected["imap_port"] == 993
        assert detected["smtp_port"] in (465, 587)


def test_provider_detection_lives_in_dedicated_module_and_routes_reexport():
    from backend.api import routes
    from backend.api.provider_detection import detect_mail_provider, domain_from_email

    assert routes.detect_mail_provider is detect_mail_provider
    assert domain_from_email("Sales@Company.IN") == "company.in"
    assert detect_mail_provider("owner@tenant.onmicrosoft.com")["provider"] == "microsoft365"


def test_account_save_persists_without_auto_delete(tmp_path, monkeypatch):
    from backend.db.database import Database
    from backend.api import routes
    from backend.auth.imap_auth import IMAPAccountManager

    db = Database(str(tmp_path / "accounts.db"))
    routes._db = db

    def fake_validate(self, email, password, provider="imap", host=None, port=None, security=None, timeout=15):
        return {
            "ok": True,
            "status": "connected",
            "message": "IMAP login succeeded.",
            "metadata": {
                "provider": provider,
                "host": host,
                "port": port,
                "security": security,
                "supports_imap": True,
                "smtp_host": "smtp.mail.yahoo.com",
                "smtp_port": 465,
                "smtp_security": "ssl",
            },
            "mailbox_count": 5,
        }

    monkeypatch.setattr(IMAPAccountManager, "validate", fake_validate)

    payload = routes.AccountAddRequest(
        provider="yahoo",
        email="client-test@yahoo.com",
        password="app-password",
        imap_host="imap.mail.yahoo.com",
        imap_port=993,
        smtp_host="smtp.mail.yahoo.com",
        smtp_port=465,
        ssl=True,
        sync_interval=20,
    )
    result = asyncio.run(routes.add_account(payload))
    assert result["status"] == "saved"
    saved = db.get_account_by_id(result["account"]["id"])
    assert saved is not None
    assert saved["status"] == "connected"
    assert saved["reconnect_state"] == "ok"
    assert db.get_all_accounts(), "Saved accounts must remain until manual removal only"
