"""Universal provider capability registry.

The registry is deliberately data-driven so provider support does not turn into
provider-specific branching across the app. It describes what each mailbox
provider can safely do locally, which authentication flow it needs, and which
sync/watch primitives the orchestrator may call.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, Iterable, List, Mapping, Optional, Set


@dataclass(frozen=True)
class ProviderCapability:
    provider: str
    display_name: str
    auth_type: str
    protocols: Set[str] = field(default_factory=set)
    supports_oauth: bool = False
    supports_refresh: bool = False
    supports_imap: bool = False
    supports_smtp: bool = False
    supports_graph: bool = False
    supports_watch: bool = False
    supports_incremental_sync: bool = True
    requires_app_password: bool = False
    requires_host: bool = False
    default_imap_host: str = ""
    default_imap_port: int = 993
    default_imap_security: str = "ssl"
    default_smtp_host: str = ""
    default_smtp_port: int = 465
    default_smtp_security: str = "ssl"
    notes: str = ""

    def as_dict(self) -> Dict:
        data = asdict(self)
        data["protocols"] = sorted(self.protocols)
        data["password_required_when_oauth"] = False if self.supports_oauth else self.supports_imap or self.supports_smtp
        return data


class ProviderCapabilityRegistry:
    """Normalizes provider capabilities for onboarding, sync and recovery."""

    def __init__(self, providers: Optional[Mapping[str, ProviderCapability]] = None):
        self._providers: Dict[str, ProviderCapability] = dict(providers or self._defaults())

    @staticmethod
    def normalize(provider: str) -> str:
        aliases = {
            "google": "gmail",
            "google_workspace": "gmail",
            "office365": "microsoft365",
            "office_365": "microsoft365",
            "hotmail": "outlook",
            "live": "outlook",
            "exchange_online": "exchange",
            "selfhosted": "self_hosted",
            "self-hosted": "self_hosted",
            "sendgrid_inbound_parse": "sendgrid_inbound",
            "ses": "amazon_ses",
            "amazon_ses_mailbox": "amazon_ses",
            "custom_imap": "custom",
            "corporate_exchange": "exchange",
            "yandex_mail": "yandex",
            "ya": "yandex",
        }
        key = (provider or "").strip().lower().replace(" ", "_").replace("-", "_").replace("/", "_")
        return aliases.get(key, key)

    def register(self, capability: ProviderCapability) -> None:
        self._providers[self.normalize(capability.provider)] = capability

    def get(self, provider: str) -> ProviderCapability:
        key = self.normalize(provider)
        if key in self._providers:
            return self._providers[key]
        if key.startswith("exchange"):
            return self._providers["exchange"]
        # Custom domains are allowed only with explicit IMAP/SMTP host metadata.
        custom = self._providers["custom"]
        return ProviderCapability(
            provider=key or "custom",
            display_name=(provider or "Custom Provider").strip() or "Custom Provider",
            auth_type=custom.auth_type,
            protocols=set(custom.protocols),
            supports_imap=True,
            supports_smtp=True,
            requires_host=True,
            default_imap_port=993,
            default_imap_security="ssl",
            notes="Custom provider requires explicit host, port and security metadata.",
        )

    def list(self) -> List[Dict]:
        return [self._providers[key].as_dict() for key in sorted(self._providers)]

    def supported(self) -> Set[str]:
        return set(self._providers)

    def oauth_providers(self) -> Set[str]:
        return {name for name, cap in self._providers.items() if cap.supports_oauth}

    def imap_providers(self) -> Set[str]:
        return {name for name, cap in self._providers.items() if cap.supports_imap}

    def validate_requested_capabilities(self, provider: str, required: Iterable[str]) -> Dict:
        cap = self.get(provider)
        missing = sorted({item for item in required if item not in cap.protocols})
        return {
            "provider": cap.provider,
            "ok": not missing,
            "missing": missing,
            "capabilities": cap.as_dict(),
        }

    @staticmethod
    def _defaults() -> Dict[str, ProviderCapability]:
        rows = [
            ProviderCapability("gmail", "Gmail / Google Workspace", "oauth2", {"oauth2", "gmail_api", "imap", "labels", "smtp"}, True, True, True, True, False, True, True, False, False, "imap.gmail.com", 993, "ssl", "smtp.gmail.com", 465, "ssl", "OAuth is preferred; IMAP requires app-password/manual fallback."),
            ProviderCapability("outlook", "Outlook / Hotmail / Live", "oauth2", {"oauth2", "graph", "folders", "categories", "smtp"}, True, True, False, False, True, True, True),
            ProviderCapability("microsoft365", "Microsoft 365 / Office 365", "oauth2", {"oauth2", "graph", "folders", "categories", "smtp"}, True, True, False, False, True, True, True),
            ProviderCapability("exchange", "Exchange Online", "oauth2_or_graph", {"oauth2", "graph", "exchange", "shared_mailboxes", "delegated_mailboxes"}, True, True, False, False, True, True, True, notes="Exchange Online is routed through Microsoft Graph; corporate Exchange can fall back to manual server settings."),
            ProviderCapability("yahoo", "Yahoo Mail", "oauth2_or_app_password", {"oauth2", "imap", "smtp"}, True, True, True, True, False, False, True, True, False, "imap.mail.yahoo.com", 993, "ssl", "smtp.mail.yahoo.com", 465, "ssl", "OAuth path never asks for passwords; app-password is available as manual fallback."),
            ProviderCapability("zoho", "Zoho Mail", "oauth2_or_app_password", {"oauth2", "zoho_mail_api", "imap", "smtp"}, True, True, True, True, False, False, True, False, False, "imap.zoho.com", 993, "ssl", "smtp.zoho.com", 465, "ssl", "OAuth path never asks for passwords; IMAP/manual fallback is supported."),
            ProviderCapability("yandex", "Yandex Mail", "oauth2_or_app_password", {"oauth2", "imap", "smtp"}, True, True, True, True, False, False, True, True, False, "imap.yandex.com", 993, "ssl", "smtp.yandex.com", 465, "ssl", "OAuth is preferred when configured; app-password IMAP/SMTP fallback is supported."),
            ProviderCapability("icloud", "iCloud Mail", "app_password", {"imap", "smtp"}, False, False, True, True, False, False, True, True, False, "imap.mail.me.com", 993, "ssl", "smtp.mail.me.com", 587, "starttls", "Requires an Apple app-specific password."),
            ProviderCapability("proton", "Proton Mail Bridge", "bridge_password", {"imap", "smtp", "bridge"}, False, False, True, True, False, False, True, True, True, "127.0.0.1", 1143, "starttls", "127.0.0.1", 1025, "starttls", "Requires Proton Mail Bridge on the same machine."),
            ProviderCapability("aol", "AOL Mail", "app_password", {"imap", "smtp"}, False, False, True, True, False, False, True, True, False, "imap.aol.com", 993, "ssl", "smtp.aol.com", 465, "ssl", "Requires an AOL app password when two-step verification is enabled."),
            ProviderCapability("fastmail", "Fastmail", "app_password", {"imap", "smtp"}, False, False, True, True, False, False, True, True, False, "imap.fastmail.com", 993, "ssl", "smtp.fastmail.com", 465, "ssl"),
            ProviderCapability("imap", "Generic IMAP", "password", {"imap"}, False, False, True, False, False, False, True, False, True),
            ProviderCapability("smtp", "Generic SMTP", "password", {"smtp"}, False, False, False, True, False, False, False, False, True, default_smtp_host="", notes="SMTP is stored as a send-only capability and is not used for inbox sync."),
            ProviderCapability("custom", "Custom IMAP/SMTP", "password", {"imap", "smtp"}, False, False, True, True, False, False, True, False, True),
            ProviderCapability("self_hosted", "Self-hosted Mail Server", "password", {"imap", "smtp"}, False, False, True, True, False, False, True, False, True),
            ProviderCapability("cpanel", "cPanel Mail", "password", {"imap", "smtp"}, False, False, True, True, False, False, True, False, True),
            ProviderCapability("roundcube", "Roundcube-backed Mailbox", "password", {"imap", "smtp"}, False, False, True, True, False, False, True, False, True),
            ProviderCapability("dovecot", "Dovecot IMAP", "password", {"imap", "smtp"}, False, False, True, True, False, False, True, False, True),
            ProviderCapability("courier", "Courier IMAP", "password", {"imap", "smtp"}, False, False, True, True, False, False, True, False, True),
            ProviderCapability("mailcow", "Mailcow", "password", {"imap", "smtp"}, False, False, True, True, False, False, True, False, True),
            ProviderCapability("zimbra", "Zimbra", "password_or_oauth", {"imap", "smtp", "enterprise_oauth"}, False, False, True, True, False, False, True, False, True),
            ProviderCapability("mailtrap", "Mailtrap", "developer_password", {"imap", "smtp", "sandbox"}, False, False, True, True, False, False, True, False, True),
            ProviderCapability("ethereal", "Ethereal", "developer_password", {"imap", "smtp", "sandbox"}, False, False, True, True, False, False, True, False, True),
            ProviderCapability("sendgrid_inbound", "SendGrid Inbound", "webhook_or_smtp", {"webhook", "smtp"}, False, False, False, True, False, True, False, False, True),
            ProviderCapability("amazon_ses", "Amazon SES Mailbox", "webhook_or_imap", {"webhook", "imap", "smtp"}, False, False, True, True, False, True, True, False, True),
            ProviderCapability("enterprise", "Enterprise / Corporate Mail", "oauth2_or_password", {"oauth2", "imap", "smtp", "graph", "exchange", "shared_mailboxes", "delegated_mailboxes"}, True, True, True, True, True, True, True, False, True, notes="Enterprise provider must be configured with explicit OAuth or IMAP metadata."),
        ]
        return {ProviderCapabilityRegistry.normalize(row.provider): row for row in rows}


def get_default_registry() -> ProviderCapabilityRegistry:
    return ProviderCapabilityRegistry()
