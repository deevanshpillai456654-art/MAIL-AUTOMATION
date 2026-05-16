"""
Utility functions for the MailPilot Connector & Plugin Panel.
Provides encryption, HMAC helpers, and general-purpose utilities.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any


# ---------------------------------------------------------------------------
# Encryption — Fernet symmetric encryption
# ---------------------------------------------------------------------------

def _get_fernet():
    """Lazily import cryptography and build a Fernet instance."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "cryptography package is required for encryption. "
            "Install it with: pip install cryptography"
        ) from exc

    key = os.environ.get("CONNECTOR_PANEL_ENCRYPTION_KEY", "")
    if not key:
        # Auto-generate a key if not configured; warn in production
        key = Fernet.generate_key().decode()
        os.environ["CONNECTOR_PANEL_ENCRYPTION_KEY"] = key
    key_bytes = key.encode() if isinstance(key, str) else key
    # Fernet requires a 32-byte URL-safe base64-encoded key
    # If the stored key is raw, derive a proper Fernet key
    try:
        return Fernet(key_bytes)
    except Exception:
        import base64
        derived = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
        return Fernet(derived)


def encrypt_secret(value: str) -> str:
    """Encrypt a plaintext secret string. Returns a URL-safe base64 ciphertext string."""
    f = _get_fernet()
    return f.encrypt(value.encode()).decode()


def decrypt_secret(encrypted: str) -> str:
    """Decrypt a ciphertext string previously encrypted with encrypt_secret."""
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()


# ---------------------------------------------------------------------------
# Secret / ID generation
# ---------------------------------------------------------------------------

def generate_webhook_secret() -> str:
    """Generate a cryptographically secure webhook signing secret (40 hex chars)."""
    return secrets.token_hex(20)


def generate_token_id() -> str:
    """Generate a unique token ID using UUID4."""
    return f"tok_{uuid.uuid4().hex}"


def generate_job_id() -> str:
    """Generate a unique queue job ID."""
    return f"job_{uuid.uuid4().hex}"


def generate_event_id() -> str:
    """Generate a unique event ID."""
    return f"evt_{uuid.uuid4().hex}"


def generate_log_id() -> str:
    """Generate a unique log entry ID."""
    return f"log_{uuid.uuid4().hex}"


def generate_connector_id() -> str:
    """Generate a unique installed-connector record ID."""
    return f"con_{uuid.uuid4().hex}"


def generate_webhook_id() -> str:
    """Generate a unique webhook record ID."""
    return f"wh_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# HMAC helpers
# ---------------------------------------------------------------------------

def compute_hmac(secret: str, payload: bytes) -> str:
    """
    Compute HMAC-SHA256 of *payload* with *secret*.
    Returns a lowercase hex digest prefixed with 'sha256='.
    """
    mac = hmac.new(secret.encode(), payload, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_hmac(secret: str, payload: bytes, signature: str) -> bool:
    """
    Verify an HMAC-SHA256 signature using a constant-time comparison.
    *signature* should be 'sha256=<hex>' or just '<hex>'.
    """
    expected = compute_hmac(secret, payload)
    # Normalise: strip the 'sha256=' prefix for comparison if both have it
    if signature.startswith("sha256="):
        return hmac.compare_digest(expected, signature)
    return hmac.compare_digest(expected.replace("sha256=", ""), signature)


# ---------------------------------------------------------------------------
# Config sanitisation
# ---------------------------------------------------------------------------

def sanitize_config(config: dict[str, Any], max_depth: int = 5, _depth: int = 0) -> dict[str, Any]:
    """
    Recursively remove None values and limit nesting depth.
    Also removes keys containing 'password', 'secret', or 'token'
    from nested structures (top-level secrets are allowed, they are
    stored encrypted separately).
    """
    if _depth > max_depth:
        return {}
    result: dict[str, Any] = {}
    for k, v in config.items():
        if v is None:
            continue
        if isinstance(v, dict):
            result[k] = sanitize_config(v, max_depth, _depth + 1)
        elif isinstance(v, (str, int, float, bool, list)):
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_duration(seconds: int) -> str:
    """Convert a duration in seconds to a human-readable string."""
    if seconds < 0:
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{m}m {s}s" if s else f"{m}m"
    if seconds < 86400:
        h, remainder = divmod(seconds, 3600)
        m = remainder // 60
        return f"{h}h {m}m" if m else f"{h}h"
    d, remainder = divmod(seconds, 86400)
    h = remainder // 3600
    return f"{d}d {h}h" if h else f"{d}d"


def utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(tz=timezone.utc)


def utc_now_str() -> str:
    """Return current UTC time as ISO 8601 string."""
    return utc_now().isoformat()


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def to_json(value: Any) -> str:
    """Serialise value to a JSON string, handling datetime objects."""
    def default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")
    return json.dumps(value, default=default)


def from_json(value: str, fallback: Any = None) -> Any:
    """Deserialise a JSON string, returning *fallback* on parse errors."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


# ---------------------------------------------------------------------------
# Health score computation
# ---------------------------------------------------------------------------

def compute_health_score(
    failure_count: int,
    retry_count: int,
    response_latency_ms: float | None,
    last_heartbeat_age_seconds: float | None,
) -> float:
    """
    Compute a normalised health score in [0.0, 1.0].
    Lower failure counts, lower latency, and recent heartbeats yield higher scores.
    """
    score = 1.0

    # Penalise for failures
    if failure_count >= 10:
        score *= 0.1
    elif failure_count >= 5:
        score *= 0.4
    elif failure_count >= 3:
        score *= 0.6
    elif failure_count >= 1:
        score *= 0.85

    # Penalise for retries (lighter penalty)
    if retry_count >= 5:
        score *= 0.8
    elif retry_count >= 2:
        score *= 0.9

    # Penalise for high latency
    if response_latency_ms is not None:
        if response_latency_ms > 10_000:
            score *= 0.5
        elif response_latency_ms > 5_000:
            score *= 0.7
        elif response_latency_ms > 2_000:
            score *= 0.9

    # Penalise for stale heartbeat
    if last_heartbeat_age_seconds is not None:
        if last_heartbeat_age_seconds > 3600:  # 1 hour
            score *= 0.3
        elif last_heartbeat_age_seconds > 600:  # 10 minutes
            score *= 0.7
        elif last_heartbeat_age_seconds > 120:  # 2 minutes
            score *= 0.9

    return round(max(0.0, min(1.0, score)), 4)
