"""
IMAP account validation and credential storage.
"""

import imaplib
import socket
from typing import Dict, Optional

from backend import config
from backend.core.provider_capability_registry import ProviderCapabilityRegistry
from backend.auth.token_crypto import TokenCipher
from backend.db.database import Database


class IMAPAccountManager:
    def __init__(self, db: Database = None, cipher: TokenCipher = None):
        self.db = db or Database(config.DB_PATH)
        self.cipher = cipher or TokenCipher()

    def build_metadata(self, provider: str, host: str = None, port: int = None,
                       security: str = None) -> Dict:
        normalized = ProviderCapabilityRegistry.normalize(provider)
        registry = ProviderCapabilityRegistry()
        capability = registry.get(normalized)
        preset = config.IMAP_PROVIDER_PRESETS.get(normalized, config.IMAP_PROVIDER_PRESETS["imap"])
        resolved_host = host or preset.get("host") or capability.default_imap_host
        resolved_port = int(port or preset.get("port") or capability.default_imap_port or 993)
        resolved_security = (security or preset.get("security") or capability.default_imap_security or "ssl").lower()
        resolved_smtp_host = capability.default_smtp_host or (host if capability.supports_smtp else "")
        resolved_smtp_port = capability.default_smtp_port or (465 if resolved_security == "ssl" else 587)
        resolved_smtp_security = capability.default_smtp_security or ("ssl" if int(resolved_smtp_port or 465) == 465 else "starttls")
        return {
            "auth_type": capability.auth_type,
            "provider": capability.provider,
            "host": resolved_host,
            "port": resolved_port,
            "security": resolved_security,
            "supports_imap": capability.supports_imap,
            "supports_smtp": capability.supports_smtp,
            "smtp_host": resolved_smtp_host,
            "smtp_port": int(resolved_smtp_port or 465),
            "smtp_security": str(resolved_smtp_security or "ssl").lower(),
            "requires_host": capability.requires_host,
        }

    def validate(self, email: str, password: str, provider: str = "imap", host: str = None,
                 port: int = None, security: str = None, timeout: int = 15) -> Dict:
        metadata = self.build_metadata(provider, host, port, security)
        if not metadata.get("supports_imap"):
            return {"ok": False, "status": "sync_not_supported", "message": "Provider does not expose IMAP inbox sync.", "metadata": metadata}
        if not metadata["host"]:
            return {"ok": False, "status": "configuration_required", "message": "IMAP host is required.", "metadata": metadata}
        if not email or not password:
            return {"ok": False, "status": "invalid_input", "message": "Email and password are required."}

        try:
            socket.setdefaulttimeout(timeout)
            if metadata["security"] == "ssl":
                client = imaplib.IMAP4_SSL(metadata["host"], metadata["port"])
            else:
                client = imaplib.IMAP4(metadata["host"], metadata["port"])
                if metadata["security"] == "starttls":
                    client.starttls()
            try:
                client.login(email, password)
                status, data = client.select("INBOX", readonly=True)
                mailbox_count = int(data[0]) if status == "OK" and data else 0
                return {
                    "ok": True,
                    "status": "connected",
                    "message": "IMAP login succeeded.",
                    "metadata": metadata,
                    "mailbox_count": mailbox_count,
                }
            finally:
                try:
                    client.logout()
                except Exception:
                    pass
        except imaplib.IMAP4.error as exc:
            return {"ok": False, "status": "auth_failed", "message": str(exc), "metadata": metadata}
        except (OSError, socket.timeout) as exc:
            return {"ok": False, "status": "network_error", "message": str(exc), "metadata": metadata}

    def store_account(self, provider: str, email: str, password: str, metadata: Optional[Dict] = None) -> int:
        encrypted_password = self.cipher.encrypt(password)
        return self.db.upsert_account(
            provider=provider,
            email=email,
            refresh_token=encrypted_password,
            status="connected",
            reconnect_state="ok",
            metadata=metadata or {},
        )

    def get_password(self, account: Dict) -> Optional[str]:
        return self.cipher.decrypt(account.get("refresh_token")) if account.get("refresh_token") else None
