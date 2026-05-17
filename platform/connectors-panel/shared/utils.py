"""
Utility functions for the MailPilot Connector & Plugin Panel.
Provides encryption, HMAC helpers, and general-purpose utilities.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

_logger = logging.getLogger("connectors_panel.utils")


# ---------------------------------------------------------------------------
# Encryption — Fernet symmetric encryption
# ---------------------------------------------------------------------------

def _key_file_path():
    from pathlib import Path
    try:
        from backend import config as _cfg
        return Path(_cfg.DATA_DIR) / "connector_panel.key"
    except Exception:
        return Path.home() / ".mailpilot" / "connector_panel.key"


def _get_fernet():
    """Build a Fernet instance backed by a persistent on-disk key."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "cryptography package is required for encryption. "
            "Install it with: pip install cryptography"
        ) from exc

    # 1. Env var takes priority (explicit production config).
    env_key = os.environ.get("CONNECTOR_PANEL_ENCRYPTION_KEY", "")
    if env_key:
        key_bytes = env_key.encode() if isinstance(env_key, str) else env_key
        try:
            return Fernet(key_bytes)
        except Exception:
            import base64
            derived = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
            return Fernet(derived)

    # 2. Key file — generate once, persist for lifetime of the installation.
    key_file = _key_file_path()
    if key_file.exists():
        try:
            raw = key_file.read_bytes().strip()
            f = Fernet(raw)
            os.environ["CONNECTOR_PANEL_ENCRYPTION_KEY"] = raw.decode()
            return f
        except Exception:
            pass  # Corrupt file — fall through to regenerate

    generated = Fernet.generate_key()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes(generated)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    os.environ["CONNECTOR_PANEL_ENCRYPTION_KEY"] = generated.decode()
    _logger.warning(
        "CONNECTOR_PANEL_ENCRYPTION_KEY not set — generated persistent key at %s. "
        "Set the env var explicitly in production.", key_file,
    )
    return Fernet(generated)


def encrypt_secret(value: str) -> str:
    """Encrypt a plaintext secret string. Returns a URL-safe base64 ciphertext string."""
    f = _get_fernet()
    return f.encrypt(value.encode()).decode()


def decrypt_secret(encrypted: str) -> str:
    """Decrypt a ciphertext string previously encrypted with encrypt_secret."""
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()


def encrypt_config(config: dict) -> str:
    """Encrypt a connector config dict as a JSON string. Secrets at rest are opaque."""
    return encrypt_secret(json.dumps(config))


def decrypt_config(raw: str) -> dict:
    """Decrypt a stored connector config string.

    Falls back to plain JSON parsing for unencrypted records written before this
    change so that existing installations continue to work during migration.
    """
    if not raw:
        return {}
    try:
        return json.loads(decrypt_secret(raw))
    except Exception:
        try:
            return json.loads(raw)
        except Exception:
            return {}


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

_SECRET_KEY_FRAGMENTS = frozenset({"password", "secret", "token"})


def sanitize_config(config: dict[str, Any], max_depth: int = 5, _depth: int = 0) -> dict[str, Any]:
    """
    Recursively remove None values and limit nesting depth.
    Also removes keys containing 'password', 'secret', 'token', 'key', or 'credential'
    from nested structures (top-level secrets are allowed, they are
    stored encrypted separately).
    """
    if _depth > max_depth:
        return {}
    result: dict[str, Any] = {}
    for k, v in config.items():
        if v is None:
            continue
        k_lower = k.lower()
        if _depth > 0 and any(frag in k_lower for frag in _SECRET_KEY_FRAGMENTS):
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
