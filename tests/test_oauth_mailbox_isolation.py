from __future__ import annotations

from urllib.parse import parse_qs, urlparse


def test_provider_config_manager_keeps_per_mailbox_configs_isolated(tmp_path):
    from backend.auth.provider_config import ProviderConfigManager

    manager = ProviderConfigManager(path=tmp_path / "provider_credentials.json")
    manager.save_oauth_config(
        provider="gmail",
        email_address="user1@example.com",
        client_id="gmail-user1-client",
        client_secret="gmail-user1-secret",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
    )
    manager.save_oauth_config(
        provider="gmail",
        email_address="user2@example.com",
        client_id="gmail-user2-client",
        client_secret="gmail-user2-secret",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
    )
    manager.save_oauth_config(
        provider="microsoft",
        email_address="user1@example.com",
        client_id="microsoft-user1-client",
        client_secret="microsoft-user1-secret",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/microsoft/callback",
    )

    gmail_user1 = manager.get_oauth_config("gmail", email_address="user1@example.com")
    gmail_user2 = manager.get_oauth_config("gmail", email_address="user2@example.com")
    microsoft_user1 = manager.get_oauth_config("microsoft", email_address="user1@example.com")

    assert gmail_user1["client_id"] == "gmail-user1-client"
    assert gmail_user2["client_id"] == "gmail-user2-client"
    assert microsoft_user1["client_id"] == "microsoft-user1-client"
    assert gmail_user1["client_secret"] == "gmail-user1-secret"
    assert gmail_user2["client_secret"] == "gmail-user2-secret"
    assert gmail_user1["config_scope"] == "mailbox"
    assert gmail_user2["config_scope"] == "mailbox"


def test_provider_config_manager_falls_back_to_shared_config(tmp_path):
    from backend.auth.provider_config import ProviderConfigManager

    manager = ProviderConfigManager(path=tmp_path / "provider_credentials.json")
    manager.save_oauth_config(
        provider="zoho",
        client_id="zoho-shared-client",
        client_secret="zoho-shared-secret",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/zoho/callback",
    )

    cfg = manager.get_oauth_config("zoho", email_address="user2@example.com")

    assert cfg["client_id"] == "zoho-shared-client"
    assert cfg["client_secret"] == "zoho-shared-secret"
    assert cfg["config_scope"] == "shared"
    assert cfg["email_address"] == "user2@example.com"


def test_oauth_config_api_masks_secret_and_is_email_scoped(monkeypatch, tmp_path):
    from backend.auth.local_auth import get_local_token
    from backend.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("INTEMO_PROVIDER_CREDENTIALS_PATH", str(tmp_path / "provider_credentials.json"))
    client = TestClient(app)
    client.post("/api/v1/session/bootstrap", headers={"X-Local-Token": get_local_token()})

    response = client.post(
        "/api/v1/oauth/config",
        json={
            "provider": "gmail",
            "email_address": "user1@example.com",
            "client_id": "gmail-user1-client",
            "client_secret": "gmail-user1-secret",
            "redirect_uri": "http://127.0.0.1:4597/api/v1/oauth/google/callback",
            "provider_options": {},
        },
    )
    assert response.status_code == 200

    fetched = client.get("/api/v1/oauth/config?provider=gmail&email_address=user1@example.com")

    assert fetched.status_code == 200
    data = fetched.json()
    assert data["provider"] == "gmail"
    assert data["email_address"] == "user1@example.com"
    assert data["client_id"] == "gmail-user1-client"
    assert data["client_secret"] != "gmail-user1-secret"
    assert data["client_secret_masked"] is True
    assert data["config_scope"] == "mailbox"


def test_oauth_start_requires_email_for_provider_specific_and_generic(monkeypatch, tmp_path):
    from backend.auth import routes as auth_routes
    from backend.db.database import Database
    from backend.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("INTEMO_PROVIDER_CREDENTIALS_PATH", str(tmp_path / "provider_credentials.json"))
    monkeypatch.setattr(auth_routes, "_db", Database(str(tmp_path / "oauth-start.db")))
    client = TestClient(app)

    assert client.post("/api/v1/oauth/google/start").status_code == 400
    assert client.get("/api/v1/oauth/google/start", follow_redirects=False).status_code == 400
    assert client.post("/api/v1/oauth/start", json={"provider": "gmail"}).status_code == 400


def test_oauth_start_uses_per_mailbox_config_and_records_state(monkeypatch, tmp_path):
    from backend.auth import routes as auth_routes
    from backend.auth.provider_config import ProviderConfigManager
    from backend.db.database import Database
    from backend.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("INTEMO_PROVIDER_CREDENTIALS_PATH", str(tmp_path / "provider_credentials.json"))
    db = Database(str(tmp_path / "oauth-start-user2.db"))
    monkeypatch.setattr(auth_routes, "_db", db)
    manager = ProviderConfigManager(path=tmp_path / "provider_credentials.json")
    manager.save_oauth_config(
        provider="gmail",
        email_address="user1@example.com",
        client_id="gmail-user1-client",
        client_secret="gmail-user1-secret",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
    )
    manager.save_oauth_config(
        provider="gmail",
        email_address="user2@example.com",
        client_id="gmail-user2-client",
        client_secret="gmail-user2-secret",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
    )

    response = TestClient(app).post(
        "/api/v1/oauth/google/start",
        json={"email_address": "user2@example.com"},
    )

    assert response.status_code == 200
    data = response.json()
    qs = parse_qs(urlparse(data["auth_url"]).query)
    assert qs["client_id"][0] == "gmail-user2-client"
    assert {"consent", "select_account"}.issubset(set(qs["prompt"][0].split()))
    assert qs["access_type"][0] == "offline"
    row = db.fetch_one("SELECT * FROM oauth_states WHERE state = ?", (data["state"],))
    assert row["requested_email"] == "user2@example.com"
    assert row["oauth_config_provider"] == "gmail"
    assert row["oauth_config_email"] == "user2@example.com"


def test_google_callback_uses_state_bound_config_and_saves_only_expected_mailbox(monkeypatch, tmp_path):
    from backend.auth import routes as auth_routes
    from backend.auth.provider_config import ProviderConfigManager
    from backend.auth.providers.google import GoogleOAuthProvider
    from backend.auth.token_store import TokenStore
    from backend.db.database import Database
    from backend.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("INTEMO_PROVIDER_CREDENTIALS_PATH", str(tmp_path / "provider_credentials.json"))
    db = Database(str(tmp_path / "oauth-callback-user2.db"))
    monkeypatch.setattr(auth_routes, "_db", db)
    manager = ProviderConfigManager(path=tmp_path / "provider_credentials.json")
    manager.save_oauth_config(
        provider="gmail",
        email_address="user2@example.com",
        client_id="gmail-user2-client",
        client_secret="gmail-user2-secret",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
    )
    db.create_oauth_state(
        provider="gmail",
        state="state-user2",
        code_verifier="verifier-user2",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
        expires_at="2999-01-01T00:00:00",
        requested_email="user2@example.com",
        oauth_config_provider="gmail",
        oauth_config_email="user2@example.com",
    )
    seen = {}

    def fake_exchange(self, code, redirect_uri, code_verifier=None):
        seen["client_id"] = self.client_id
        return {
            "access_token": "user2-access-token",
            "refresh_token": "user2-refresh-token",
            "expires_in": 3600,
        }

    monkeypatch.setattr(GoogleOAuthProvider, "exchange_code", fake_exchange)
    monkeypatch.setattr(GoogleOAuthProvider, "get_profile", lambda self, token: {"email": "user2@example.com"})

    response = TestClient(app).get("/api/v1/oauth/google/callback?code=user2&state=state-user2")

    assert response.status_code == 200
    assert seen["client_id"] == "gmail-user2-client"
    user2 = db.fetch_one("SELECT * FROM accounts WHERE provider = ? AND email = ?", ("gmail", "user2@example.com"))
    user1 = db.fetch_one("SELECT * FROM accounts WHERE provider = ? AND email = ?", ("gmail", "user1@example.com"))
    assert user2 is not None
    assert user1 is None
    assert TokenStore(db).get_access_token(user2["id"]) == "user2-access-token"


def test_callback_wrong_account_message_and_no_token_write(monkeypatch, tmp_path):
    from backend.auth import routes as auth_routes
    from backend.auth.provider_config import ProviderConfigManager
    from backend.auth.providers.google import GoogleOAuthProvider
    from backend.db.database import Database
    from backend.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("INTEMO_PROVIDER_CREDENTIALS_PATH", str(tmp_path / "provider_credentials.json"))
    db = Database(str(tmp_path / "oauth-mismatch-message.db"))
    monkeypatch.setattr(auth_routes, "_db", db)
    ProviderConfigManager(path=tmp_path / "provider_credentials.json").save_oauth_config(
        provider="gmail",
        email_address="user2@example.com",
        client_id="gmail-user2-client",
        client_secret="gmail-user2-secret",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
    )
    db.create_oauth_state(
        provider="gmail",
        state="state-user2",
        code_verifier="verifier-user2",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
        expires_at="2999-01-01T00:00:00",
        requested_email="user2@example.com",
        oauth_config_provider="gmail",
        oauth_config_email="user2@example.com",
    )
    monkeypatch.setattr(GoogleOAuthProvider, "exchange_code", lambda self, code, redirect_uri, code_verifier=None: {"access_token": "bad-access", "refresh_token": "bad-refresh", "expires_in": 3600})
    monkeypatch.setattr(GoogleOAuthProvider, "get_profile", lambda self, token: {"email": "user1@example.com"})

    response = TestClient(app).get("/api/v1/oauth/google/callback?code=user2&state=state-user2")

    assert response.status_code == 200
    assert "Wrong account selected. Expected user2@example.com but received user1@example.com. Please retry and select the correct account." in response.text
    assert db.fetch_all("SELECT * FROM accounts") == []


def test_provider_specific_authorization_params_are_preserved(monkeypatch, tmp_path):
    from backend.auth.provider_config import ProviderConfigManager
    from backend.auth.providers.microsoft import MicrosoftOAuthProvider
    from backend.auth.universal_oauth import UniversalOAuth
    from backend.db.database import Database

    monkeypatch.setenv("INTEMO_PROVIDER_CREDENTIALS_PATH", str(tmp_path / "provider_credentials.json"))
    manager = ProviderConfigManager(path=tmp_path / "provider_credentials.json")
    for provider, callback in {
        "microsoft": "microsoft",
        "yahoo": "yahoo",
        "zoho": "zoho",
        "yandex": "yandex",
    }.items():
        manager.save_oauth_config(
            provider=provider,
            email_address="user2@example.com",
            client_id=f"{provider}-client",
            client_secret=f"{provider}-secret",
            redirect_uri=f"http://127.0.0.1:4597/api/v1/oauth/{callback}/callback",
        )

    db = Database(str(tmp_path / "params.db"))
    microsoft = MicrosoftOAuthProvider(db=db, email_address="user2@example.com")
    ms_qs = parse_qs(urlparse(microsoft.create_authorization_request("http://127.0.0.1:4597/api/v1/oauth/microsoft/callback", login_hint="user2@example.com")["auth_url"]).query)
    assert ms_qs["client_id"][0] == "microsoft-client"
    assert ms_qs["prompt"][0] == "select_account"

    yahoo = UniversalOAuth("yahoo", db=db, email_address="user2@example.com")
    yahoo_qs = parse_qs(urlparse(yahoo.create_authorization_request("http://127.0.0.1:4597/api/v1/oauth/yahoo/callback", login_hint="user2@example.com")["auth_url"]).query)
    assert yahoo_qs["client_id"][0] == "yahoo-client"
    assert "prompt" not in yahoo_qs

    zoho = UniversalOAuth("zoho", db=db, email_address="user2@example.com")
    zoho_qs = parse_qs(urlparse(zoho.create_authorization_request("http://127.0.0.1:4597/api/v1/oauth/zoho/callback", login_hint="user2@example.com")["auth_url"]).query)
    assert zoho_qs["access_type"][0] == "offline"
    assert zoho_qs["prompt"][0] == "consent"

    yandex = UniversalOAuth("yandex", db=db, email_address="user2@example.com")
    yandex_qs = parse_qs(urlparse(yandex.create_authorization_request("http://127.0.0.1:4597/api/v1/oauth/yandex/callback", login_hint="user2@example.com")["auth_url"]).query)
    assert yandex_qs["force_confirm"][0] == "yes"


def test_refresh_uses_account_scoped_config_and_updates_only_that_account(monkeypatch, tmp_path):
    from backend.auth.gmail_auth import GmailOAuth
    from backend.auth.provider_config import ProviderConfigManager
    from backend.auth.token_store import TokenStore
    from backend.db.database import Database

    monkeypatch.setenv("INTEMO_PROVIDER_CREDENTIALS_PATH", str(tmp_path / "provider_credentials.json"))
    ProviderConfigManager(path=tmp_path / "provider_credentials.json").save_oauth_config(
        provider="gmail",
        email_address="user2@example.com",
        client_id="gmail-user2-client",
        client_secret="gmail-user2-secret",
        redirect_uri="http://127.0.0.1:4597/api/v1/oauth/google/callback",
    )
    db = Database(str(tmp_path / "refresh.db"))
    first = db.upsert_account(provider="gmail", email="user1@example.com", auth_type="oauth", oauth_provider="gmail")
    second = db.upsert_account(provider="gmail", email="user2@example.com", auth_type="oauth", oauth_provider="gmail")
    store = TokenStore(db)
    store.save(first, "first-access", "first-refresh", -10)
    store.save(second, "old-second-access", "second-refresh", -10)
    seen = {}

    def fake_refresh(self, refresh_token):
        seen["client_id"] = self.client_id
        seen["refresh_token"] = refresh_token
        return {"access_token": "new-second-access", "expires_in": 3600}

    monkeypatch.setattr(GmailOAuth, "refresh_access_token", fake_refresh)

    token = GmailOAuth(db=db, email_address="user2@example.com").get_valid_token(second)

    assert token == "new-second-access"
    assert seen == {"client_id": "gmail-user2-client", "refresh_token": "second-refresh"}
    assert TokenStore(db).get_access_token(second) == "new-second-access"
    assert TokenStore(db).get_access_token(first) is None
