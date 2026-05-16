"""Universal provider detection and authentication strategy engine.

This module is intentionally the single source of truth for account onboarding.
It separates three things that were previously easy to mix up:

1. Provider/app configuration (admin OAuth client credentials)
2. User authentication (OAuth token callback OR IMAP/app-password login)
3. Account initialization (secure persistence, sync queue, AI orchestration)

The most important invariant is enforced by ``AuthStrategy.password_required``:
OAuth strategies never require mailbox passwords or app passwords.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import json
import logging
import socket
import subprocess

from backend.auth.provider_config import ProviderConfigManager, oauth_group_for, normalize_provider
from backend.auth.validation import ProviderAuthValidator
from backend.core.account_persistence import detect_mail_settings, account_metadata
from backend.core.provider_capability_registry import ProviderCapability, ProviderCapabilityRegistry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderDetection:
    email: str
    domain: str
    provider: str
    oauth_provider: Optional[str]
    source: str
    mx_records: List[str]
    defaults: Dict[str, Any]
    capabilities: Dict[str, Any]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AuthStrategy:
    provider: str
    display_name: str
    auth_method: str
    connection_method: str
    oauth_provider: Optional[str]
    recommended: bool
    password_required: bool
    app_password_required: bool
    imap_required: bool
    smtp_required: bool
    exchange_supported: bool
    token_required: bool
    configured: bool
    setup_required: bool
    oauth_start_url: Optional[str]
    manual_guidance: Optional[str]
    client_message: str
    admin_message: Optional[str]
    defaults: Dict[str, Any]
    capabilities: Dict[str, Any]
    validate_oauth_tokens_only: bool

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class UniversalEmailAuthEngine:
    """Detect providers, pick the correct auth path and build onboarding plans."""

    DOMAIN_RULES: Dict[str, Tuple[str, Optional[str]]] = {
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
        "icloud.com": ("icloud", None),
        "me.com": ("icloud", None),
        "mac.com": ("icloud", None),
        "proton.me": ("proton", None),
        "protonmail.com": ("proton", None),
        "pm.me": ("proton", None),
        "fastmail.com": ("fastmail", None),
        "aol.com": ("aol", None),
        "yandex.com": ("yandex", "yandex"),
        "yandex.ru": ("yandex", "yandex"),
        "ya.ru": ("yandex", "yandex"),
        "mail.ru": ("custom", None),
    }

    MX_HINTS: List[Tuple[str, str, Optional[str]]] = [
        ("google.com", "gmail", "gmail"),
        ("googlemail.com", "gmail", "gmail"),
        ("outlook.com", "microsoft365", "microsoft"),
        ("protection.outlook.com", "microsoft365", "microsoft"),
        ("yahoodns.net", "yahoo", "yahoo"),
        ("zoho.com", "zoho", "zoho"),
        ("icloud.com", "icloud", None),
        ("messagingengine.com", "fastmail", None),
        ("protonmail.ch", "proton", None),
        ("yandex.net", "yandex", "yandex"),
    ]

    MANUAL_GUIDANCE: Dict[str, str] = {
        "icloud": "Use an Apple app-specific password with iCloud IMAP/SMTP settings.",
        "proton": "Start Proton Mail Bridge locally, then enter the Bridge-generated IMAP/SMTP credentials.",
        "fastmail": "Use a Fastmail app password; normal account passwords should not be reused.",
        "aol": "Use AOL IMAP/SMTP with an app password when two-step verification is enabled.",
        "custom": "Confirm IMAP/SMTP host, port and SSL/TLS settings, then enter the mailbox/app password.",
        "self_hosted": "Use your server's IMAP/SMTP endpoints and mailbox/app password.",
        "exchange": "Exchange Online uses Microsoft OAuth; corporate/on-prem Exchange can fall back to explicit IMAP/SMTP details.",
        "yandex": "Yandex OAuth is preferred when configured; app-password IMAP/SMTP remains available as manual fallback.",
    }

    def __init__(self, registry: ProviderCapabilityRegistry = None, config_manager: ProviderConfigManager = None):
        self.registry = registry or ProviderCapabilityRegistry()
        self.config_manager = config_manager or ProviderConfigManager()

    @staticmethod
    def normalize_email(email: str) -> str:
        value = (email or "").strip().lower()
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Valid email is required")
        return value

    @staticmethod
    def domain_from_email(email: str) -> str:
        return email.split("@", 1)[1].strip().lower()

    def lookup_mx_records(self, domain: str, timeout_seconds: int = 3) -> List[str]:
        """Best-effort MX lookup without a hard dependency on dnspython.

        Tests and offline desktop installs can run without DNS access. The method
        therefore returns [] on failure instead of blocking onboarding.
        """
        if not domain:
            return []
        try:
            try:
                import dns.resolver  # type: ignore
                resolver = dns.resolver.Resolver()
                resolver.lifetime = timeout_seconds
                return sorted(str(r.exchange).rstrip(".").lower() for r in resolver.resolve(domain, "MX"))
            except Exception:
                pass
            proc = subprocess.run(
                ["nslookup", "-type=mx", domain],
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
            records: List[str] = []
            for line in (proc.stdout or "").splitlines():
                lowered = line.lower()
                if "mail exchanger" in lowered and "=" in lowered:
                    records.append(lowered.rsplit("=", 1)[-1].strip().rstrip("."))
            return sorted(set(records))
        except (OSError, subprocess.SubprocessError, socket.timeout):
            return []

    def provider_from_domain_or_mx(self, domain: str, enable_mx_lookup: bool = False) -> Tuple[str, Optional[str], str, List[str]]:
        if domain in self.DOMAIN_RULES:
            provider, oauth = self.DOMAIN_RULES[domain]
            return provider, oauth, "domain", []
        if domain.endswith(".onmicrosoft.com"):
            return "microsoft365", "microsoft", "domain_suffix", []
        mx_records = self.lookup_mx_records(domain) if enable_mx_lookup else []
        for record in mx_records:
            for needle, provider, oauth in self.MX_HINTS:
                if needle in record:
                    return provider, oauth, "mx", mx_records
        return "custom", None, "custom_domain", mx_records

    def defaults_for(self, provider: str, email: str = "") -> Dict[str, Any]:
        provider = ProviderCapabilityRegistry.normalize(provider)
        cap = self.registry.get(provider)
        persistence = detect_mail_settings(email) if email else {}
        domain = self.domain_from_email(email) if email and "@" in email else ""
        defaults = {
            "imap_host": cap.default_imap_host or persistence.get("imap_host"),
            "imap_port": cap.default_imap_port or persistence.get("imap_port") or 993,
            "imap_security": cap.default_imap_security or persistence.get("imap_security") or "ssl",
            "smtp_host": cap.default_smtp_host or persistence.get("smtp_host"),
            "smtp_port": cap.default_smtp_port or persistence.get("smtp_port") or 465,
            "smtp_security": cap.default_smtp_security or persistence.get("smtp_security") or "ssl",
        }
        if provider == "custom" and domain:
            defaults["imap_host"] = defaults.get("imap_host") or f"imap.{domain}"
            defaults["smtp_host"] = defaults.get("smtp_host") or f"smtp.{domain}"
        return defaults

    def detect(self, email: str, *, enable_mx_lookup: bool = False) -> ProviderDetection:
        normalized = self.normalize_email(email)
        domain = self.domain_from_email(normalized)
        provider, oauth_provider, source, mx_records = self.provider_from_domain_or_mx(domain, enable_mx_lookup=enable_mx_lookup)
        cap = self.registry.get(provider)
        return ProviderDetection(
            email=normalized,
            domain=domain,
            provider=cap.provider,
            oauth_provider=oauth_provider,
            source=source,
            mx_records=mx_records,
            defaults=self.defaults_for(cap.provider, normalized),
            capabilities=cap.as_dict(),
        )

    def oauth_start_url(self, oauth_provider: Optional[str], email: str = "") -> Optional[str]:
        group = oauth_group_for(oauth_provider or "") or normalize_provider(oauth_provider or "")
        if not group:
            return None
        path = {
            "gmail": "/api/v1/oauth/google/start",
            "microsoft": "/api/v1/oauth/microsoft/start",
            "yahoo": "/api/v1/oauth/yahoo/start",
            "zoho": "/api/v1/oauth/zoho/start",
            "yandex": "/api/v1/oauth/yandex/start",
        }.get(group)
        if not path:
            return None
        return f"{path}?email={email}" if email else path

    def strategy_for(self, email: str, provider: str = None, requested_method: str = "auto", base_url: str = None) -> AuthStrategy:
        detection = self.detect(email)
        selected_provider = ProviderCapabilityRegistry.normalize(provider or detection.provider)
        cap = self.registry.get(selected_provider)
        oauth_provider = oauth_group_for(selected_provider) or detection.oauth_provider
        requested = (requested_method or "auto").strip().lower()
        if requested in {"default", "auto", ""}:
            requested = "oauth" if oauth_provider and cap.supports_oauth else ("app_password" if cap.requires_app_password else "imap")
        if requested in {"oauth2", "provider_oauth"}:
            requested = "oauth"
        if requested in {"password", "manual", "imap_smtp", "advanced_imap"}:
            requested = "imap"

        if requested == "oauth" and oauth_provider and cap.supports_oauth:
            oauth_status = self.config_manager.status(oauth_provider, base_url)
            configured = bool(oauth_status.get("configured"))
            message = (
                f"Continue with {cap.display_name}. Mailbox passwords and app passwords are never requested in OAuth mode."
                if configured else
                f"{cap.display_name} OAuth app credentials must be configured before users can connect."
            )
            return AuthStrategy(
                provider=cap.provider,
                display_name=cap.display_name,
                auth_method="oauth2",
                connection_method="oauth",
                oauth_provider=oauth_provider,
                recommended=True,
                password_required=False,
                app_password_required=False,
                imap_required=False,
                smtp_required=False,
                exchange_supported=cap.supports_graph or "exchange" in cap.protocols,
                token_required=True,
                configured=configured,
                setup_required=not configured,
                oauth_start_url=self.oauth_start_url(oauth_provider, detection.email),
                manual_guidance=None,
                client_message=message,
                admin_message=None if configured else f"Save OAuth Client ID/Secret for {oauth_provider} in Provider Setup.",
                defaults=self.defaults_for(cap.provider, detection.email),
                capabilities=cap.as_dict(),
                validate_oauth_tokens_only=True,
            )

        # Unsupported explicit OAuth falls back to the provider's safe manual path.
        manual_guidance = self.MANUAL_GUIDANCE.get(cap.provider) or self.MANUAL_GUIDANCE.get("custom")
        manual_method = "app_password" if cap.requires_app_password else "imap"
        return AuthStrategy(
            provider=cap.provider,
            display_name=cap.display_name,
            auth_method=cap.auth_type,
            connection_method=manual_method,
            oauth_provider=None,
            recommended=not bool(oauth_provider),
            password_required=True,
            app_password_required=bool(cap.requires_app_password or cap.supports_imap),
            imap_required=bool(cap.supports_imap),
            smtp_required=bool(cap.supports_smtp),
            exchange_supported=cap.supports_graph or "exchange" in cap.protocols,
            token_required=False,
            configured=True,
            setup_required=False,
            oauth_start_url=None,
            manual_guidance=manual_guidance,
            client_message=manual_guidance,
            admin_message=None,
            defaults=self.defaults_for(cap.provider, detection.email),
            capabilities=cap.as_dict(),
            validate_oauth_tokens_only=False,
        )

    def validate_account_payload(self, payload: Dict[str, Any], base_url: str = None) -> Dict[str, Any]:
        """Validate account onboarding through the single auth validation pipeline.

        OAuth strategies dispatch only to the OAuth validator, which deliberately
        ignores password/app-password/IMAP/SMTP fields. Manual strategies dispatch
        only to the IMAP/app-password validator.
        """
        email = self.normalize_email(payload.get("email", ""))
        provider = payload.get("provider")
        method = payload.get("connection_method") or payload.get("auth_method") or "auto"
        strategy = self.strategy_for(email=email, provider=provider, requested_method=method, base_url=base_url)
        return ProviderAuthValidator().validate(payload, strategy)

    def onboarding_plan(self, email: str, provider: str = None, requested_method: str = "auto", base_url: str = None) -> Dict[str, Any]:
        detection = self.detect(email)
        strategy = self.strategy_for(email, provider=provider or detection.provider, requested_method=requested_method, base_url=base_url)
        steps = ["provider_detection", "capability_detection", "auth_strategy"]
        if strategy.connection_method == "oauth":
            steps += ["oauth_pkce_state", "provider_consent", "callback_token_exchange", "encrypted_token_vault", "account_auto_create", "mailbox_initialize", "sync_start", "ai_orchestration_start"]
        else:
            steps += ["imap_smtp_auto_config", "credential_validation", "encrypted_credential_vault", "account_create", "mailbox_initialize", "sync_start", "ai_orchestration_start"]
        return {
            "status": "ready" if strategy.configured else "provider_setup_required",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "detection": detection.as_dict(),
            "strategy": strategy.as_dict(),
            "steps": steps,
            "separation_policy": "Provider configuration, user authentication, and account initialization are separate flows.",
            "oauth_password_policy": "OAuth strategies never accept or require mailbox passwords/app passwords.",
        }

    @staticmethod
    def account_metadata_for_strategy(strategy: AuthStrategy, sync_interval: int = 20, extra: Dict[str, Any] = None) -> Dict[str, Any]:
        metadata = account_metadata(
            sync_interval,
            auth_type=strategy.auth_method,
            provider=strategy.provider,
            oauth_provider=strategy.oauth_provider,
            connection_method=strategy.connection_method,
            password_required=strategy.password_required,
            app_password_required=strategy.app_password_required,
            validate_oauth_tokens_only=strategy.validate_oauth_tokens_only,
            credential_storage="encrypted_local_vault",
            provider_capabilities=strategy.capabilities,
            imap_host=strategy.defaults.get("imap_host"),
            imap_port=strategy.defaults.get("imap_port"),
            imap_security=strategy.defaults.get("imap_security"),
            smtp_host=strategy.defaults.get("smtp_host"),
            smtp_port=strategy.defaults.get("smtp_port"),
            smtp_security=strategy.defaults.get("smtp_security"),
            sync_status="pending",
            preserve_on_restart=True,
            manual_removal_only=True,
        )
        if extra:
            metadata.update(extra)
        return metadata

    @staticmethod
    def serialize_scopes(scopes: Any) -> str:
        if isinstance(scopes, str):
            scopes = [scopes]
        if not scopes:
            return "[]"
        return json.dumps(sorted(set(str(item) for item in scopes)))
