from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]


def test_oauth_start_uses_v1_callback_url(monkeypatch):
    import backend.config as config
    monkeypatch.setattr(config, "GMAIL_CLIENT_ID", "unit-test-client-id", raising=False)
    monkeypatch.setattr(config, "GMAIL_CLIENT_SECRET", "unit-test-client-secret", raising=False)
    from fastapi.testclient import TestClient
    from backend.main import app
    c = TestClient(app)
    r = c.post("/api/v1/oauth/google/start", json={"email": "user@gmail.com"})
    assert r.status_code == 200
    data = r.json()
    assert data["configured"] is True
    qs = parse_qs(urlparse(data["auth_url"]).query)
    assert qs["redirect_uri"][0].endswith("/api/v1/oauth/google/callback")
    assert "login_hint" not in qs
    assert {"consent", "select_account"}.issubset(set(qs["prompt"][0].split()))
    assert qs["max_age"][0] == "0"
    expiry = datetime.fromisoformat(data["expires_at"])
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    assert (expiry - datetime.now(timezone.utc)).total_seconds() > 25 * 60


def test_microsoft_oauth_start_forces_account_selection(monkeypatch):
    import backend.config as config
    monkeypatch.setattr(config, "OUTLOOK_CLIENT_ID", "unit-test-client-id", raising=False)
    monkeypatch.setattr(config, "OUTLOOK_CLIENT_SECRET", "unit-test-client-secret", raising=False)
    monkeypatch.setattr(config, "OUTLOOK_TENANT_ID", "common", raising=False)
    from fastapi.testclient import TestClient
    from backend.main import app
    c = TestClient(app)
    r = c.post("/api/v1/oauth/microsoft/start", json={"email": "second@company.com"})
    assert r.status_code == 200
    qs = parse_qs(urlparse(r.json()["auth_url"]).query)
    assert "login_hint" not in qs
    assert qs["prompt"][0] == "select_account"


def test_google_oauth_get_start_redirect_uses_account_chooser_without_login_hint(monkeypatch):
    import backend.config as config
    monkeypatch.setattr(config, "GMAIL_CLIENT_ID", "unit-test-client-id", raising=False)
    monkeypatch.setattr(config, "GMAIL_CLIENT_SECRET", "unit-test-client-secret", raising=False)
    from fastapi.testclient import TestClient
    from backend.main import app

    response = TestClient(app).get(
        "/api/v1/oauth/google/start?email=second@gmail.com",
        follow_redirects=False,
    )

    assert response.status_code in {302, 307}
    qs = parse_qs(urlparse(response.headers["location"]).query)
    assert "login_hint" not in qs
    assert {"consent", "select_account"}.issubset(set(qs["prompt"][0].split()))
    assert qs["max_age"][0] == "0"


def test_auth_strategy_oauth_start_url_encodes_requested_email():
    from backend.auth.universal_auth_engine import UniversalEmailAuthEngine

    url = UniversalEmailAuthEngine().oauth_start_url("gmail", "first+sales@gmail.com")

    assert url == "/api/v1/oauth/google/start?email=first%2Bsales%40gmail.com"


def test_google_callback_rejects_profile_email_that_does_not_match_requested_oauth_email(monkeypatch, tmp_path):
    from backend.auth import routes as auth_routes
    from backend.auth.local_auth import get_local_token
    from backend.auth.providers.google import GoogleOAuthProvider
    from backend.db.database import Database
    from fastapi.testclient import TestClient
    from backend.main import app

    db = Database(str(tmp_path / "oauth-mismatch.db"))
    monkeypatch.setattr(auth_routes, "_db", db)
    db.create_oauth_state(
        provider="gmail",
        state="state-second",
        code_verifier="verifier-second",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
        expires_at="2999-01-01T00:00:00",
        requested_email="second@gmail.com",
    )
    monkeypatch.setattr(
        GoogleOAuthProvider,
        "exchange_code",
        lambda self, code, redirect_uri, code_verifier=None: {
            "access_token": "first-access",
            "refresh_token": "first-refresh",
            "expires_in": 3600,
        },
    )
    monkeypatch.setattr(
        GoogleOAuthProvider,
        "get_profile",
        lambda self, access_token: {"email": "first@gmail.com"},
    )

    response = TestClient(app).get("/api/v1/oauth/google/callback?code=abc&state=state-second")

    assert response.status_code == 200
    assert "second@gmail.com" in response.text
    assert "first@gmail.com" in response.text
    assert db.fetch_one("SELECT * FROM accounts WHERE email = ?", ("first@gmail.com",)) is None


def test_google_oauth_callback_can_add_multiple_gmail_accounts(monkeypatch, tmp_path):
    from backend.api import routes as api_routes
    from backend.auth import routes as auth_routes
    from backend.auth.local_auth import get_local_token
    from backend.auth.providers.google import GoogleOAuthProvider
    from backend.auth.token_store import TokenStore
    from backend.db.database import Database
    from fastapi.testclient import TestClient
    from backend.main import app

    db = Database(str(tmp_path / "two-gmail-oauth.db"))
    monkeypatch.setattr(auth_routes, "_db", db)
    monkeypatch.setattr(api_routes, "_db", db)
    for state, email in (("state-first", "first@gmail.com"), ("state-second", "second@gmail.com")):
        db.create_oauth_state(
            provider="gmail",
            state=state,
            code_verifier=f"verifier-{state}",
            redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
            expires_at="2999-01-01T00:00:00",
            requested_email=email,
        )

    def fake_exchange(self, code, redirect_uri, code_verifier=None):
        return {
            "access_token": f"{code}-access-token",
            "refresh_token": f"{code}-refresh-token",
            "expires_in": 3600,
        }

    def fake_profile(self, access_token):
        if access_token.startswith("first"):
            return {"email": "first@gmail.com"}
        return {"email": "second@gmail.com"}

    monkeypatch.setattr(GoogleOAuthProvider, "exchange_code", fake_exchange)
    monkeypatch.setattr(GoogleOAuthProvider, "get_profile", fake_profile)

    client = TestClient(app)
    client.post("/api/v1/session/bootstrap", headers={"X-Local-Token": get_local_token()})
    first_response = client.get("/api/v1/oauth/google/callback?code=first&state=state-first")
    second_response = client.get("/api/v1/oauth/google/callback?code=second&state=state-second")
    accounts_response = client.get("/api/v1/accounts")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert "first@gmail.com" in first_response.text
    assert "second@gmail.com" in second_response.text
    assert accounts_response.status_code == 200
    accounts = sorted(
        [account for account in accounts_response.json()["accounts"] if account["provider"] == "gmail"],
        key=lambda account: account["email"],
    )
    assert [account["email"] for account in accounts] == ["first@gmail.com", "second@gmail.com"]
    token_store = TokenStore(db)
    assert token_store.get_access_token(accounts[0]["id"]) == "first-access-token"
    assert token_store.get_access_token(accounts[1]["id"]) == "second-access-token"


def test_oauth_missing_credentials_returns_428(monkeypatch):
    import backend.config as config
    monkeypatch.setattr(config, "GMAIL_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(config, "GMAIL_CLIENT_SECRET", "", raising=False)
    from fastapi.testclient import TestClient
    from backend.main import app
    c = TestClient(app)
    r = c.post("/api/v1/oauth/google/start", json={"email": "user@gmail.com"})
    assert r.status_code == 428


def test_accounts_test_returns_oauth_info_when_missing_config(monkeypatch):
    import backend.config as config
    import backend.api.routes as routes_module
    monkeypatch.setattr(config, "GMAIL_CLIENT_ID", "YOUR_GMAIL_CLIENT_ID", raising=False)
    monkeypatch.setattr(config, "GMAIL_CLIENT_SECRET", "YOUR_GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(routes_module, "ensure_local_request", lambda req: None)
    from fastapi.testclient import TestClient
    from backend.auth.local_auth import get_local_token
    from backend.main import app
    c = TestClient(app)
    c.post("/api/v1/session/bootstrap", headers={"X-Local-Token": get_local_token()})
    r = c.post("/api/v1/accounts/test", json={"provider": "gmail", "email": "user@gmail.com", "connection_method": "oauth"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in {"provider_setup_required", "oauth_ready"}
    assert data["oauth_start_url"].startswith("/api/v1/oauth/google/start")


def test_enterprise_account_oauth_required_includes_yandex_start_url():
    from fastapi import HTTPException
    from backend.api.enterprise_accounts import EnterpriseAccountPayload, enterprise_save_account

    payload = EnterpriseAccountPayload(
        provider="yandex",
        email="user@yandex.com",
        connection_method="oauth",
    )

    try:
        asyncio.run(enterprise_save_account(payload))
    except HTTPException as exc:
        assert exc.status_code == 428
        assert exc.detail["oauth_start_url"] == "/api/v1/oauth/yandex/start"
    else:
        raise AssertionError("Expected Yandex OAuth save to require provider OAuth start")


def test_manual_app_password_save_validates_stores_hosts_and_never_deletes(monkeypatch, tmp_path):
    from backend.api import routes
    from backend.db.database import Database
    from backend.auth.imap_auth import IMAPAccountManager

    db = Database(str(tmp_path / "email-flow.db"))
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
            "mailbox_count": 3,
        }

    monkeypatch.setattr(IMAPAccountManager, "validate", fake_validate)
    payload = routes.AccountAddRequest(
        provider="yahoo",
        email="ops@yahoo.com",
        password="app-password",
        imap_host="imap.mail.yahoo.com",
        imap_port=993,
        smtp_host="smtp.mail.yahoo.com",
        smtp_port=465,
        ssl=True,
        sync_interval=20,
        connection_method="app_password",
    )
    result = asyncio.run(routes.add_account(payload))
    account = db.get_account_by_id(result["account"]["id"])
    assert result["status"] == "saved"
    assert account["status"] == "connected"
    meta = json.loads(account["metadata"])
    assert meta["host"] == "imap.mail.yahoo.com"
    assert meta["imap_host"] == "imap.mail.yahoo.com"
    assert meta["smtp_host"] == "smtp.mail.yahoo.com"
    db.update_account_status(account["id"], "needs_reconnect", "auth_failed", "bad password")
    assert db.get_account_by_id(account["id"]) is not None


def test_email_delete_endpoint_is_soft_delete_not_permanent(tmp_path):
    from backend.api import routes
    from backend.db.database import Database
    db = Database(str(tmp_path / "soft-delete.db"))
    routes._db = db
    account_id = db.upsert_account(provider="imap", email="a@example.com", status="connected")
    email_id = db.add_email(account_id, "msg-1", "Subject", "Sender", "sender@example.com", "Body")
    result = asyncio.run(routes.clear_emails())
    assert result["status"] == "soft_deleted"
    row = db.fetch_one("SELECT * FROM emails WHERE id = ?", (email_id,))
    assert row is not None
    assert row["delete_state"] == "deleted"
    asyncio.run(routes.restore_emails())
    restored = db.fetch_one("SELECT * FROM emails WHERE id = ?", (email_id,))
    assert restored["delete_state"] == "active"


def test_email_attachments_are_listed_and_downloadable(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api import routes
    from backend.core.attachment_storage import AttachmentStorageEngine
    from backend.db.database import Database
    from backend.main import app

    db = Database(str(tmp_path / "attachments.db"))
    routes._db = db
    storage = AttachmentStorageEngine(str(tmp_path / "attachments"))
    monkeypatch.setattr(routes, "attachment_storage", storage)

    account_id = db.upsert_account(provider="imap", email="a@example.com", status="connected")
    email_id = db.add_email(account_id, "msg-attach", "Invoice attached", "Sender", "sender@example.com", "Body")
    meta = storage.store("invoice.pdf", b"PDFDATA", "application/pdf", email_id=email_id)

    emails = asyncio.run(routes.get_emails())
    row = next(email for email in emails["emails"] if email["id"] == email_id)
    assert row["attachments"] == [
        {
            "id": meta.attachment_id,
            "attachment_id": meta.attachment_id,
            "filename": "invoice.pdf",
            "content_type": "application/pdf",
            "size": 7,
            "download_url": f"/api/v1/attachments/{meta.attachment_id}/download",
        }
    ]

    from backend.auth.local_auth import get_local_token
    client = TestClient(app)
    client.post("/api/v1/session/bootstrap", headers={"X-Local-Token": get_local_token()})
    response = client.get(f"/api/v1/attachments/{meta.attachment_id}/download")
    assert response.status_code == 200
    assert response.content == b"PDFDATA"
    assert response.headers["content-type"].startswith("application/pdf")
    assert "invoice.pdf" in response.headers["content-disposition"]
