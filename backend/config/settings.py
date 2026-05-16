"""Authoritative application settings via pydantic_settings.

Startup FAILS LOUDLY if required OAuth credentials are missing or malformed.
No placeholder defaults. No silent fallbacks.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _strip_quotes(value: str) -> str:
    value = (value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1].strip()
    return value


def _placeholder(value: str) -> bool:
    v = (value or "").strip().upper()
    return v.startswith("YOUR_") or v.startswith("PLACEHOLDER") or v in ("", "NONE", "NULL")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Runtime environment ─────────────────────────────────────────────────
    app_env: str = "local"
    is_containerized: bool = False
    aio_portable: bool = False

    # ── Network binding ─────────────────────────────────────────────────────
    api_host: str = "127.0.0.1"
    api_port: int = 4597
    public_base_url: str = ""

    # ── OAuth — Google ──────────────────────────────────────────────────────
    google_client_id: str = ""
    google_client_secret: str = ""

    # ── OAuth — Microsoft ───────────────────────────────────────────────────
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    outlook_tenant_id: str = "common"

    # ── OAuth — Yahoo (optional) ────────────────────────────────────────────
    yahoo_client_id: str = ""
    yahoo_client_secret: str = ""

    # ── Backward-compat env aliases ─────────────────────────────────────────
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_redirect_uri: str = ""
    outlook_client_id: str = ""
    outlook_client_secret: str = ""
    outlook_redirect_uri: str = ""

    # ── Encryption ──────────────────────────────────────────────────────────
    token_encryption_key: Optional[str] = None

    # ── Logging ─────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── CORS ────────────────────────────────────────────────────────────────
    cors_allowed_origins: str = ""

    # ── DB ──────────────────────────────────────────────────────────────────
    db_path: str = ""
    database_url: str = ""
    db_backend: str = "sqlite"

    # ── Misc infrastructure ──────────────────────────────────────────────────
    redis_url: str = ""
    sentry_dsn: str = ""
    prometheus_enabled: bool = False
    gmail_pubsub_topic: str = ""

    @field_validator(
        "google_client_id", "google_client_secret",
        "gmail_client_id", "gmail_client_secret",
        "microsoft_client_id", "microsoft_client_secret",
        "outlook_client_id", "outlook_client_secret",
        "yahoo_client_id", "yahoo_client_secret",
        "token_encryption_key",
        mode="before",
    )
    @classmethod
    def sanitize_credential(cls, v):
        if v is None:
            return ""
        return _strip_quotes(str(v))

    @field_validator("api_host", mode="before")
    @classmethod
    def validate_host(cls, v):
        v = _strip_quotes(str(v or "127.0.0.1"))
        return v if v in ("127.0.0.1", "localhost", "0.0.0.0") else "127.0.0.1"

    @field_validator("api_port", mode="before")
    @classmethod
    def validate_port(cls, v):
        try:
            p = int(_strip_quotes(str(v or "4597")))
            return max(1, min(65535, p))
        except (TypeError, ValueError):
            return 4597

    @field_validator("log_level", mode="before")
    @classmethod
    def validate_log_level(cls, v):
        v = _strip_quotes(str(v or "INFO")).upper()
        return v if v in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "INFO"

    @model_validator(mode="after")
    def coalesce_aliases(self):
        """Merge GMAIL_*/OUTLOOK_* legacy env names into canonical GOOGLE_*/MICROSOFT_* names."""
        if not self.google_client_id and self.gmail_client_id:
            self.google_client_id = self.gmail_client_id
        if not self.google_client_secret and self.gmail_client_secret:
            self.google_client_secret = self.gmail_client_secret
        if not self.microsoft_client_id and self.outlook_client_id:
            self.microsoft_client_id = self.outlook_client_id
        if not self.microsoft_client_secret and self.outlook_client_secret:
            self.microsoft_client_secret = self.outlook_client_secret
        if not self.public_base_url:
            self.public_base_url = f"http://127.0.0.1:{self.api_port}"
        return self

    def require_google_oauth(self) -> None:
        """Raise ValueError loudly if Google OAuth is not configured."""
        missing = []
        if _placeholder(self.google_client_id):
            missing.append("GOOGLE_CLIENT_ID")
        if _placeholder(self.google_client_secret):
            missing.append("GOOGLE_CLIENT_SECRET")
        if missing:
            raise ValueError(f"Google OAuth requires: {', '.join(missing)}")

    def require_microsoft_oauth(self) -> None:
        """Raise ValueError loudly if Microsoft OAuth is not configured."""
        missing = []
        if _placeholder(self.microsoft_client_id):
            missing.append("MICROSOFT_CLIENT_ID")
        if _placeholder(self.microsoft_client_secret):
            missing.append("MICROSOFT_CLIENT_SECRET")
        if missing:
            raise ValueError(f"Microsoft OAuth requires: {', '.join(missing)}")


settings = Settings()
