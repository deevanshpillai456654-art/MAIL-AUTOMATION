from typing import Dict

from backend import config
from backend.auth.provider_config import ProviderConfigManager
from backend.core.account_persistence import detect_mail_settings
from backend.core.provider_capability_registry import ProviderCapabilityRegistry

PROVIDER_DOMAIN_RULES = {
    "gmail.com": ("gmail", "gmail"),
    "googlemail.com": ("gmail", "gmail"),
    "outlook.com": ("outlook", "microsoft"),
    "hotmail.com": ("outlook", "microsoft"),
    "live.com": ("outlook", "microsoft"),
    "msn.com": ("outlook", "microsoft"),
    "office365.com": ("microsoft365", "microsoft"),
    "onmicrosoft.com": ("microsoft365", "microsoft"),
    "yahoo.com": ("yahoo", "yahoo"),
    "ymail.com": ("yahoo", "yahoo"),
    "rocketmail.com": ("yahoo", "yahoo"),
    "zoho.com": ("zoho", "zoho"),
    "zohomail.com": ("zoho", "zoho"),
    "fastmail.com": ("fastmail", None),
    "proton.me": ("proton", None),
    "protonmail.com": ("proton", None),
    "pm.me": ("proton", None),
    "icloud.com": ("icloud", None),
    "me.com": ("icloud", None),
    "mac.com": ("icloud", None),
    "aol.com": ("aol", None),
    "yandex.com": ("yandex", "yandex"),
    "yandex.ru": ("yandex", "yandex"),
    "ya.ru": ("yandex", "yandex"),
}


def domain_from_email(email: str) -> str:
    return (email or "").split("@", 1)[-1].strip().lower()


def detect_mail_provider(email: str, base_url: str = None) -> Dict:
    """Return the client-safe mailbox onboarding path for an email address."""
    normalized_email = (email or "").strip().lower()
    domain = domain_from_email(normalized_email)
    provider, oauth_provider = PROVIDER_DOMAIN_RULES.get(domain, (None, None))
    if provider is None and domain.endswith(".onmicrosoft.com"):
        provider, oauth_provider = "microsoft365", "microsoft"
    if provider is None:
        provider, oauth_provider = "custom", None

    registry = ProviderCapabilityRegistry()
    capability = registry.get(provider)
    defaults = {
        "imap_host": capability.default_imap_host,
        "imap_port": capability.default_imap_port,
        "imap_security": capability.default_imap_security,
        "smtp_host": capability.default_smtp_host,
        "smtp_port": capability.default_smtp_port,
        "smtp_security": capability.default_smtp_security,
    }
    persistence_defaults = detect_mail_settings(normalized_email)
    defaults["imap_host"] = defaults.get("imap_host") or persistence_defaults.get("imap_host")
    defaults["imap_port"] = defaults.get("imap_port") or persistence_defaults.get("imap_port") or 993
    defaults["smtp_host"] = defaults.get("smtp_host") or persistence_defaults.get("smtp_host")
    defaults["smtp_port"] = defaults.get("smtp_port") or persistence_defaults.get("smtp_port") or 465
    if provider == "custom" and domain:
        defaults.update({"imap_host": f"imap.{domain}", "smtp_host": f"smtp.{domain}"})

    manager = ProviderConfigManager()
    oauth_status = None
    configured = True
    if oauth_provider:
        oauth_status = manager.status(oauth_provider, base_url, email_address=normalized_email)
        configured = bool(oauth_status.get("configured"))

    if oauth_provider:
        action = "oauth" if configured else "contact_admin"
        client_message = (
            f"Continue with {capability.display_name}. You will sign in on the provider's official page."
            if configured else
            f"{capability.display_name} login is not enabled yet. Please contact your administrator."
        )
        admin_message = None if configured else (
            "Provider OAuth credentials are missing. Open Setup > Provider Settings and save the Client ID and Client Secret."
        )
        requires_password = False
        requires_host = False
    else:
        action = "app_password" if not capability.requires_host else "advanced_imap"
        client_message = (
            "Use an app password or provider-specific mailbox password. Your normal Gmail/Outlook password is not required here."
            if action == "app_password" else
            "Custom provider detected. Confirm the IMAP/SMTP server details and use an app password where your provider requires it."
        )
        admin_message = None
        requires_password = True
        requires_host = bool(capability.requires_host)

    return {
        "email": normalized_email,
        "domain": domain,
        "provider": capability.provider,
        "display_name": capability.display_name,
        "auth_type": capability.auth_type,
        "connection_method": "oauth" if oauth_provider else action,
        "oauth_provider": oauth_provider,
        "configured": configured,
        "setup_required": bool(oauth_provider and not configured),
        "requires_password": requires_password,
        "requires_host": requires_host,
        "defaults": defaults,
        "imap_host": defaults.get("imap_host"),
        "imap_port": defaults.get("imap_port"),
        "smtp_host": defaults.get("smtp_host"),
        "smtp_port": defaults.get("smtp_port"),
        "ssl": (defaults.get("imap_security") or "ssl") in ("ssl", "tls", "starttls"),
        "capabilities": capability.as_dict(),
        "client_message": client_message,
        "admin_message": admin_message,
        "setup_url": "/setup#provider-setup" if oauth_provider and not configured else None,
        "oauth_status": oauth_status,
    }


def request_base_url(request) -> str:
    host = request.url.hostname or "127.0.0.1"
    if host not in ("127.0.0.1", "localhost"):
        host = "127.0.0.1"
    port = f":{request.url.port}" if request.url.port else f":{config.API_PORT}"
    return f"http://127.0.0.1{port}"


__all__ = [
    "PROVIDER_DOMAIN_RULES",
    "detect_mail_provider",
    "domain_from_email",
    "request_base_url",
]
