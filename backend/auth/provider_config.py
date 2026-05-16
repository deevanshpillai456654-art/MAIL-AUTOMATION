"""Provider credential configuration for local-first universal email onboarding.

The installer never ships real provider secrets. Admins can configure OAuth app
credentials at runtime; client IDs are public identifiers, while client secrets
are encrypted with the existing TokenCipher and never returned to frontend APIs.
Manual IMAP/SMTP providers remain separate and continue to use app-password or
mailbox-password flows.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from backend import config
from backend.auth.token_crypto import TokenCipher


OAUTH_GROUPS = {
    "gmail": {
        "display_name": "Gmail / Google Workspace",
        "client_id_env": "GMAIL_CLIENT_ID",
        "client_secret_env": "GMAIL_CLIENT_SECRET",
        "redirect_env": "GMAIL_REDIRECT_URI",
        "default_callback": "/api/v1/oauth/google/callback",
        "start_path": "/api/v1/oauth/google/start",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "profile_url": "https://www.googleapis.com/oauth2/v2/userinfo",
        "cloud_console_url": "https://console.cloud.google.com/apis/credentials",
        "scopes": ["openid", "email", "profile", "https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/gmail.send"],
        "notes": "Enable Gmail API and create an OAuth Web application client.",
    },
    "microsoft": {
        "display_name": "Outlook / Office 365 / Hotmail / Live / Exchange Online",
        "client_id_env": "OUTLOOK_CLIENT_ID",
        "client_secret_env": "OUTLOOK_CLIENT_SECRET",
        "tenant_env": "OUTLOOK_TENANT_ID",
        "redirect_env": "OUTLOOK_REDIRECT_URI",
        "default_callback": "/api/v1/oauth/microsoft/callback",
        "start_path": "/api/v1/oauth/microsoft/start",
        "auth_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "profile_url": "https://graph.microsoft.com/v1.0/me",
        "cloud_console_url": "https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        "scopes": ["offline_access", "User.Read", "Mail.ReadWrite", "Mail.Send"],
        "notes": "Create an Azure App Registration with Microsoft Graph mail permissions.",
    },
    "yahoo": {
        "display_name": "Yahoo Mail",
        "client_id_env": "YAHOO_CLIENT_ID",
        "client_secret_env": "YAHOO_CLIENT_SECRET",
        "redirect_env": "YAHOO_REDIRECT_URI",
        "default_callback": "/api/v1/oauth/yahoo/callback",
        "start_path": "/api/v1/oauth/yahoo/start",
        "auth_url": "https://api.login.yahoo.com/oauth2/request_auth",
        "token_url": "https://api.login.yahoo.com/oauth2/get_token",
        "profile_url": "https://api.login.yahoo.com/openid/v1/userinfo",
        "cloud_console_url": "https://developer.yahoo.com/apps/",
        "scopes": ["openid", "mail-r", "mail-w"],
        "notes": "Create a Yahoo developer app with mail permissions. OAuth accounts never require an app password.",
    },
    "zoho": {
        "display_name": "Zoho Mail",
        "client_id_env": "ZOHO_CLIENT_ID",
        "client_secret_env": "ZOHO_CLIENT_SECRET",
        "redirect_env": "ZOHO_REDIRECT_URI",
        "default_callback": "/api/v1/oauth/zoho/callback",
        "start_path": "/api/v1/oauth/zoho/start",
        "auth_url": "https://accounts.zoho.com/oauth/v2/auth",
        "token_url": "https://accounts.zoho.com/oauth/v2/token",
        "profile_url": "https://accounts.zoho.com/oauth/user/info",
        "cloud_console_url": "https://api-console.zoho.com/",
        "scopes": ["ZohoMail.accounts.READ", "ZohoMail.folders.READ", "ZohoMail.messages.READ", "ZohoMail.messages.CREATE"],
        "notes": "Create a Zoho API Console client and enable Zoho Mail scopes. IMAP app-password remains available as a manual fallback.",
    },
    "yandex": {
        "display_name": "Yandex Mail",
        "client_id_env": "YANDEX_CLIENT_ID",
        "client_secret_env": "YANDEX_CLIENT_SECRET",
        "redirect_env": "YANDEX_REDIRECT_URI",
        "default_callback": "/api/v1/oauth/yandex/callback",
        "start_path": "/api/v1/oauth/yandex/start",
        "auth_url": "https://oauth.yandex.com/authorize",
        "token_url": "https://oauth.yandex.com/token",
        "profile_url": "https://login.yandex.com/info",
        "cloud_console_url": "https://oauth.yandex.com/client/new",
        "scopes": ["login:email", "mail:imap_ro", "mail:smtp"],
        "notes": "Create a Yandex OAuth application for Mail access. App-password IMAP/SMTP remains available as manual fallback.",
    },
}

PROVIDER_GROUP_ALIASES = {
    "gmail": "gmail",
    "google": "gmail",
    "google_workspace": "gmail",
    "outlook": "microsoft",
    "microsoft": "microsoft",
    "microsoft365": "microsoft",
    "office365": "microsoft",
    "hotmail": "microsoft",
    "live": "microsoft",
    "exchange": "microsoft",
    "exchange_online": "microsoft",
    "yahoo": "yahoo",
    "ymail": "yahoo",
    "rocketmail": "yahoo",
    "zoho": "zoho",
    "zohomail": "zoho",
    "yandex": "yandex",
    "yandex_mail": "yandex",
    "ya": "yandex",
}

MANUAL_PROVIDER_REQUIREMENTS = {
    "imap": "Enter email, IMAP host, port, SSL/TLS mode, and an app password.",
    "smtp": "Enter SMTP host, port, SSL/TLS mode, and an app password. SMTP is send-only.",
    "icloud": "Use an Apple app-specific password with iCloud IMAP/SMTP settings.",
    "fastmail": "Use a Fastmail app password with imap.fastmail.com and smtp.fastmail.com.",
    "yandex": "Use Yandex OAuth when configured, or Yandex app-password IMAP/SMTP fallback.",
    "proton": "Install and run Proton Mail Bridge, then use the Bridge IMAP/SMTP credentials.",
    "aol": "Use AOL IMAP/SMTP settings and an app password when two-step verification is enabled.",
    "custom": "Enter the provider's IMAP/SMTP host, port, security mode, and app password.",
    "self_hosted": "Enter your self-hosted IMAP/SMTP host, port, security mode, and mailbox password/app password.",
    "cpanel": "Use the mailbox's cPanel IMAP/SMTP hosts and app-password/mailbox-password credentials.",
    "roundcube": "Roundcube is a webmail UI; connect the underlying IMAP/SMTP server.",
    "dovecot": "Connect directly to the Dovecot IMAP host and matching SMTP service.",
    "courier": "Connect directly to the Courier IMAP host and matching SMTP service.",
    "mailcow": "Use your Mailcow IMAP/SMTP endpoints and mailbox password/app password.",
    "zimbra": "Use Zimbra IMAP/SMTP or enterprise OAuth if your admin configured it.",
    "mailtrap": "Use Mailtrap sandbox SMTP/IMAP credentials for developer testing.",
    "ethereal": "Use Ethereal test mailbox credentials for developer testing.",
    "sendgrid_inbound": "Use SendGrid Inbound Parse webhook routing; SMTP is send-only.",
    "amazon_ses": "Use Amazon SES receiving or a configured mailbox endpoint for inbound tests.",
    "enterprise": "Use provider OAuth where configured, or explicit IMAP/SMTP host settings for corporate mail servers.",
}


def normalize_provider(provider: str) -> str:
    return (provider or "").strip().lower().replace("-", "_").replace(" ", "_")


def oauth_group_for(provider: str) -> Optional[str]:
    return PROVIDER_GROUP_ALIASES.get(normalize_provider(provider))


def is_placeholder(value: Optional[str]) -> bool:
    raw = (value or "").strip()
    if not raw:
        return True
    lowered = raw.lower()
    return (
        lowered.startswith("your_")
        or lowered.startswith("your-")
        or lowered.startswith("change_this")
        or lowered in {"changeme", "placeholder", "none", "null"}
        or raw.startswith("YOUR_")
    )


class ProviderConfigManager:
    def __init__(self, path: Optional[Path] = None, cipher: Optional[TokenCipher] = None):
        configured_path = os.environ.get("INTEMO_PROVIDER_CREDENTIALS_PATH")
        self.path = Path(path or configured_path or Path(config.DATA_DIR) / "provider_credentials.json")
        self.cipher = cipher or TokenCipher()

    def _read(self) -> Dict:
        if not self.path.exists():
            return {"version": 2, "oauth": {}, "updated_at": None}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"version": 2, "oauth": {}, "updated_at": None}
            data.setdefault("oauth", {})
            return data
        except Exception:
            return {"version": 2, "oauth": {}, "updated_at": None, "read_error": True}

    def _write(self, data: Dict) -> None:
        data["version"] = 2
        data["updated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @staticmethod
    def default_base_url() -> str:
        public = getattr(config, "PUBLIC_BASE_URL", "") or ""
        if public and "127.0.0.1" not in public and "localhost" not in public:
            return public.rstrip("/")
        return f"http://127.0.0.1:{getattr(config, 'API_PORT', 4597)}"

    def redirect_uri_for(self, group: str, base_url: Optional[str] = None, stored_redirect: Optional[str] = None) -> str:
        group = oauth_group_for(group) or normalize_provider(group)
        meta = OAUTH_GROUPS[group]
        env_redirect = os.environ.get(meta["redirect_env"])
        if env_redirect and not is_placeholder(env_redirect):
            return env_redirect.strip()
        if stored_redirect and not is_placeholder(stored_redirect):
            return stored_redirect.strip()
        return f"{(base_url or self.default_base_url()).rstrip('/')}{meta['default_callback']}"

    def get_oauth_config(self, provider: str, runtime_redirect_uri: Optional[str] = None) -> Dict:
        group = oauth_group_for(provider) or normalize_provider(provider)
        if group not in OAUTH_GROUPS:
            return {"provider": normalize_provider(provider), "oauth": False, "configured": False, "missing": []}
        meta = OAUTH_GROUPS[group]
        data = self._read()
        stored = (data.get("oauth") or {}).get(group, {})

        env_client_id = os.environ.get(meta["client_id_env"])
        env_client_secret = os.environ.get(meta["client_secret_env"])
        env_tenant = os.environ.get(meta.get("tenant_env", ""), "") if meta.get("tenant_env") else ""

        client_id = env_client_id if not is_placeholder(env_client_id) else stored.get("client_id", "")
        if not is_placeholder(env_client_secret):
            client_secret = env_client_secret
            secret_source = "environment"
        elif stored.get("client_secret_encrypted"):
            try:
                client_secret = self.cipher.decrypt(stored.get("client_secret_encrypted")) or ""
                secret_source = "encrypted_store"
            except Exception:
                client_secret = ""
                secret_source = "encrypted_store_unreadable"
        else:
            client_secret = ""
            secret_source = "missing"

        tenant_id = "common"
        if group == "microsoft":
            tenant_id = env_tenant if not is_placeholder(env_tenant) else (stored.get("tenant_id") or "common")

        missing = []
        if is_placeholder(client_id):
            missing.append(meta["client_id_env"])
        if is_placeholder(client_secret):
            missing.append(meta["client_secret_env"])

        redirect_uri = runtime_redirect_uri or self.redirect_uri_for(group, stored_redirect=stored.get("redirect_uri"))
        source = "environment" if not is_placeholder(env_client_id) or not is_placeholder(env_client_secret) else ("encrypted_store" if stored else "missing")
        return {
            "provider": group,
            "oauth": True,
            "configured": not missing,
            "missing": missing,
            "client_id": client_id or "",
            "client_secret": client_secret or "",
            "tenant_id": tenant_id,
            "redirect_uri": redirect_uri,
            "source": source,
            "secret_source": secret_source,
            "auth_url": meta.get("auth_url"),
            "token_url": meta.get("token_url"),
            "profile_url": meta.get("profile_url"),
            "scopes": meta.get("scopes", []),
        }

    def status(self, provider: str, base_url: Optional[str] = None) -> Dict:
        normalized = normalize_provider(provider)
        group = oauth_group_for(normalized)
        if not group:
            requirement = MANUAL_PROVIDER_REQUIREMENTS.get(normalized, MANUAL_PROVIDER_REQUIREMENTS["custom"])
            return {
                "provider": normalized,
                "auth_mode": "manual",
                "configured": True,
                "requires_oauth_setup": False,
                "requires_password": True,
                "password_required": True,
                "missing": [],
                "message": requirement,
                "requirements": [requirement],
            }
        meta = OAUTH_GROUPS[group]
        data = self._read()
        stored = (data.get("oauth") or {}).get(group, {})
        cfg = self.get_oauth_config(group, runtime_redirect_uri=self.redirect_uri_for(group, base_url, stored.get("redirect_uri")))
        return {
            "provider": group,
            "display_name": meta["display_name"],
            "auth_mode": "oauth2",
            "configured": cfg["configured"],
            "requires_oauth_setup": not cfg["configured"],
            "requires_password": False,
            "password_required": False,
            "missing": cfg["missing"],
            "client_id_present": not is_placeholder(cfg.get("client_id")),
            "client_secret_present": not is_placeholder(cfg.get("client_secret")),
            "tenant_id": cfg.get("tenant_id") if group == "microsoft" else None,
            "source": cfg.get("source"),
            "redirect_uri": cfg.get("redirect_uri"),
            "start_path": meta["start_path"],
            "setup_url": "/setup#provider-setup",
            "cloud_console_url": meta["cloud_console_url"],
            "scopes": meta["scopes"],
            "message": "Ready to connect accounts with OAuth. Password fields must stay hidden." if cfg["configured"] else f"{meta['display_name']} OAuth app credentials are required before users can connect accounts.",
            "notes": meta["notes"],
        }

    def all_status(self, base_url: Optional[str] = None) -> Dict:
        providers = ["gmail", "outlook", "microsoft365", "exchange", "yahoo", "zoho", "yandex", "icloud", "proton", "aol", "fastmail", "imap", "smtp", "custom", "self_hosted", "cpanel", "roundcube", "dovecot", "courier", "mailcow", "zimbra", "mailtrap", "ethereal", "sendgrid_inbound", "amazon_ses", "enterprise"]
        statuses = {provider: self.status(provider, base_url) for provider in providers}
        oauth_groups = {group: self.status(group, base_url) for group in OAUTH_GROUPS}
        oauth_ready = all(status["configured"] for status in oauth_groups.values())
        return {
            "status": "ready" if oauth_ready else "provider_setup_required",
            "providers": statuses,
            "oauth_groups": oauth_groups,
            "config_file": str(self.path),
            "password_policy": "OAuth providers never require password/app-password fields; manual providers do.",
        }

    def save_oauth_config(self, provider: str, client_id: str, client_secret: Optional[str] = None,
                          tenant_id: Optional[str] = None, redirect_uri: Optional[str] = None) -> Dict:
        group = oauth_group_for(provider) or normalize_provider(provider)
        if group not in OAUTH_GROUPS:
            raise ValueError("Only OAuth-capable providers can be configured here")
        meta = OAUTH_GROUPS[group]
        if is_placeholder(client_id):
            raise ValueError(f"{meta['client_id_env']} is required")

        data = self._read()
        oauth = data.setdefault("oauth", {})
        existing = oauth.get(group, {})
        row = {
            "client_id": client_id.strip(),
            "updated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if redirect_uri and not is_placeholder(redirect_uri):
            row["redirect_uri"] = redirect_uri.strip()
        elif existing.get("redirect_uri"):
            row["redirect_uri"] = existing["redirect_uri"]
        if group == "microsoft":
            row["tenant_id"] = (tenant_id or existing.get("tenant_id") or "common").strip() or "common"
        if client_secret and not is_placeholder(client_secret):
            row["client_secret_encrypted"] = self.cipher.encrypt(client_secret.strip())
        elif existing.get("client_secret_encrypted"):
            row["client_secret_encrypted"] = existing["client_secret_encrypted"]
        else:
            raise ValueError(f"{meta['client_secret_env']} is required")
        oauth[group] = row
        self._write(data)
        return self.status(group)

    def clear_oauth_config(self, provider: str) -> Dict:
        group = oauth_group_for(provider) or normalize_provider(provider)
        if group not in OAUTH_GROUPS:
            raise ValueError("Unknown OAuth provider")
        data = self._read()
        (data.get("oauth") or {}).pop(group, None)
        self._write(data)
        return self.status(group)

    def instructions(self, base_url: Optional[str] = None) -> Dict:
        return {
            "summary": "Configure OAuth app credentials once, then connect user mailboxes from the dashboard. OAuth paths never request passwords.",
            "oauth_providers": {group: self.status(group, base_url) for group in OAUTH_GROUPS},
            "manual_providers": MANUAL_PROVIDER_REQUIREMENTS,
        }
