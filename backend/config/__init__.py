"""Authoritative backend configuration.

OAuth credentials come from pydantic_settings (backend.config.settings).
Path resolution, port binding, and runtime settings are derived here.
Startup FAILS LOUDLY if required values are missing — no silent placeholders.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from backend.config.settings import settings

APP_VENDOR_DIR = "AIEmailOrganizer"


def _is_truthy(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # __file__ is backend/config/__init__.py → .parent.parent.parent = project root
    return Path(__file__).resolve().parent.parent.parent


def _windows_data_home() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_VENDOR_DIR
    return Path.home() / "AppData" / "Local" / APP_VENDOR_DIR


def _platform_data_home() -> Path:
    if os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA"):
        return _windows_data_home()
    if os.name == "nt":
        return _windows_data_home()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_VENDOR_DIR
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_VENDOR_DIR


def _resolve_runtime_dir(env_names: tuple[str, ...], default_name: str, *, portable: bool = False) -> Path:
    for name in env_names:
        raw = os.environ.get(name)
        if raw:
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = (_app_dir() if portable else _platform_data_home()) / path
            return path.resolve()
    root = _app_dir() if portable else _platform_data_home()
    return (root / default_name).resolve()


def _copy_tree_missing(src: Path, dst: Path) -> None:
    if not src.exists() or not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        try:
            if item.is_dir():
                _copy_tree_missing(item, target)
            elif not target.exists():
                shutil.copy2(item, target)
        except Exception:
            pass


def _migrate_legacy_runtime_data(data_dir: Path, log_dir: Path, model_dir: Path) -> None:
    if _is_truthy(os.environ.get("AIO_DISABLE_DATA_MIGRATION")):
        return
    app = _app_dir()
    service_dir = app / "backend"
    legacy_roots = []
    for candidate in (
        app / "data",
        app / "local-service" / "data",
        app / "backend" / "data",
        app / "service" / "data",
        service_dir / "data",
    ):
        if candidate not in legacy_roots:
            legacy_roots.append(candidate)
    if not (data_dir / "emails.db").exists():
        for legacy in legacy_roots:
            if (legacy / "emails.db").exists():
                _copy_tree_missing(legacy, data_dir)
                break
    for legacy_log in (
        app / "logs", app / "local-service" / "logs",
        app / "backend" / "logs", app / "service" / "logs", service_dir / "logs",
    ):
        if legacy_log.exists():
            _copy_tree_missing(legacy_log, log_dir)
            break
    for legacy_model in (
        app / "models", app / "local-service" / "models",
        app / "backend" / "models", app / "service" / "models", service_dir / "models",
    ):
        if legacy_model.exists():
            _copy_tree_missing(legacy_model, model_dir)
            break


def _get_int_env(name: str, default: int, minimum: int = None, maximum: int = None) -> int:
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


# ── Runtime profile ──────────────────────────────────────────────────────────

APP_ENV = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "local")).lower()
IS_PRODUCTION = APP_ENV == "production"
IS_CONTAINERIZED = os.environ.get("CONTAINERIZED", "").lower() in {"1", "true", "yes", "on"}
IS_PORTABLE = _is_truthy(os.environ.get("AIO_PORTABLE")) or _is_truthy(os.environ.get("AIO_USE_PROJECT_DATA"))

# ── API binding ───────────────────────────────────────────────────────────────

API_HOST = settings.api_host
# Wildcard binds are reduced to loopback unless explicitly enabled.
if API_HOST == "0.0.0.0" and not (IS_CONTAINERIZED or os.environ.get("ALLOW_EXTERNAL_BIND") == "1"):  # nosec B104
    API_HOST = "127.0.0.1"
API_PORT = settings.api_port
PUBLIC_BASE_URL = settings.public_base_url or f"http://127.0.0.1:{API_PORT}"

# ── File paths ────────────────────────────────────────────────────────────────

APP_DIR = _app_dir()
BASE_DIR = str(APP_DIR)
RUNTIME_HOME = (_app_dir() if IS_PORTABLE else _platform_data_home()).resolve()
DATA_DIR = str(_resolve_runtime_dir(("AIO_DATA_DIR", "DATA_DIR"), "data", portable=IS_PORTABLE))
LOG_DIR = str(_resolve_runtime_dir(("AIO_LOG_DIR", "LOG_DIR"), "logs", portable=IS_PORTABLE))
MODEL_DIR = str(_resolve_runtime_dir(("AIO_MODEL_DIR", "MODEL_DIR"), "models", portable=IS_PORTABLE))
CACHE_DIR = str(_resolve_runtime_dir(("AIO_CACHE_DIR", "CACHE_DIR"), "cache", portable=IS_PORTABLE))
DATABASE_DIR = str(_resolve_runtime_dir(("AIO_DATABASE_DIR", "DATABASE_DIR"), "database", portable=IS_PORTABLE))

for _directory in (DATA_DIR, LOG_DIR, MODEL_DIR, CACHE_DIR, DATABASE_DIR):
    os.makedirs(_directory, exist_ok=True)

_migrate_legacy_runtime_data(Path(DATA_DIR), Path(LOG_DIR), Path(MODEL_DIR))

DB_PATH = os.environ.get("DB_PATH") or os.path.join(DATA_DIR, "emails.db")
LOG_PATH = LOG_DIR

# ── Infrastructure ────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").lower()
REDIS_URL = os.environ.get("REDIS_URL", "")
QUEUE_BACKEND = os.environ.get("QUEUE_BACKEND", "local").lower()
DEAD_LETTER_QUEUE_URL = os.environ.get("DEAD_LETTER_QUEUE_URL", "")
VAULT_PROVIDER = os.environ.get("VAULT_PROVIDER", "local").lower()
VAULT_ADDR = os.environ.get("VAULT_ADDR", "")
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
OTEL_EXPORTER_OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
PROMETHEUS_ENABLED = os.environ.get("PROMETHEUS_ENABLED", "").lower() in {"1", "true", "yes", "on"}
BACKUP_BUCKET = os.environ.get("BACKUP_BUCKET", "")
BACKUP_PATH = os.environ.get("BACKUP_PATH", "")
K8S_REPLICAS = _get_int_env("K8S_REPLICAS", 1, 1, 100)

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_LEVEL = settings.log_level
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

# ── Classification ────────────────────────────────────────────────────────────

CONFIDENCE_AUTO_MOVE = 0.95
CONFIDENCE_SUGGEST = 0.70
CONFIDENCE_LOW = 0.70

VALID_CATEGORIES = [
    "Finance", "OTP", "Clients", "Personal", "Promotions",
    "Spam", "Newsletters", "Trading", "Logistics", "Purchases",
    "HR", "Support", "Bills", "Security", "Urgent", "Waiting Reply",
]
VALID_PRIORITIES = ["Low", "Medium", "High", "Critical"]

# ── Email providers ───────────────────────────────────────────────────────────

EMAIL_PROVIDERS = [
    "gmail", "outlook", "microsoft365", "exchange", "imap", "smtp",
    "yahoo", "zoho", "proton", "fastmail", "custom", "self_hosted", "enterprise",
]

# ── Port management ───────────────────────────────────────────────────────────

PORT_RANGE_MIN = 4597
PORT_RANGE_MAX = 4600

# ── Security ──────────────────────────────────────────────────────────────────

CORS_ORIGINS = [
    "chrome-extension://*",
    "ms-office-addin://*",
    "http://127.0.0.1:*",
    "http://localhost:*",
]
RATE_LIMIT_REQUESTS = 600
RATE_LIMIT_WINDOW = 60
TOKEN_EXPIRY_SECONDS = 3600
MAX_CONNECTIONS = 100

# ── Database ──────────────────────────────────────────────────────────────────

DB_PRAGMAS = {
    "journal_mode": "WAL",
    "synchronous": "NORMAL",
    "cache_size": "-2000",
    "temp_store": "MEMORY",
    "busy_timeout": "30000",
    "foreign_keys": "ON",
}

# ── Performance ───────────────────────────────────────────────────────────────

MAX_WORKERS = 4
BATCH_SIZE = 50
CACHE_TTL = 1800

# ── OAuth credentials (from pydantic_settings — no placeholders) ─────────────

GMAIL_CLIENT_ID = settings.google_client_id or settings.gmail_client_id
GMAIL_CLIENT_SECRET = settings.google_client_secret or settings.gmail_client_secret
OUTLOOK_CLIENT_ID = settings.microsoft_client_id or settings.outlook_client_id
OUTLOOK_CLIENT_SECRET = settings.microsoft_client_secret or settings.outlook_client_secret
OUTLOOK_TENANT_ID = settings.outlook_tenant_id or os.environ.get("OUTLOOK_TENANT_ID", "common")
YAHOO_CLIENT_ID = settings.yahoo_client_id
YAHOO_CLIENT_SECRET = settings.yahoo_client_secret
ZOHO_CLIENT_ID = os.environ.get("ZOHO_CLIENT_ID", "")
ZOHO_CLIENT_SECRET = os.environ.get("ZOHO_CLIENT_SECRET", "")
TOKEN_ENCRYPTION_KEY = settings.token_encryption_key
GMAIL_PUBSUB_TOPIC = os.environ.get("GMAIL_PUBSUB_TOPIC", "")

# ── OAuth redirect URIs (always /api/v1/oauth/*) ──────────────────────────────

GMAIL_REDIRECT_URI = (
    os.environ.get("GMAIL_REDIRECT_URI")
    or settings.gmail_redirect_uri
    or f"http://127.0.0.1:{API_PORT}/api/v1/oauth/google/callback"
)
OUTLOOK_REDIRECT_URI = (
    os.environ.get("OUTLOOK_REDIRECT_URI")
    or settings.outlook_redirect_uri
    or f"http://127.0.0.1:{API_PORT}/api/v1/oauth/microsoft/callback"
)
YAHOO_REDIRECT_URI = (
    os.environ.get("YAHOO_REDIRECT_URI")
    or f"http://127.0.0.1:{API_PORT}/api/v1/oauth/yahoo/callback"
)
ZOHO_REDIRECT_URI = (
    os.environ.get("ZOHO_REDIRECT_URI")
    or f"http://127.0.0.1:{API_PORT}/api/v1/oauth/zoho/callback"
)

# ── IMAP presets ──────────────────────────────────────────────────────────────

IMAP_PROVIDER_PRESETS = {
    "gmail": {"host": "imap.gmail.com", "port": 993, "security": "ssl"},
    "yahoo": {"host": "imap.mail.yahoo.com", "port": 993, "security": "ssl"},
    "zoho": {"host": "imap.zoho.com", "port": 993, "security": "ssl"},
    "proton": {"host": "127.0.0.1", "port": 1143, "security": "starttls"},
    "fastmail": {"host": "imap.fastmail.com", "port": 993, "security": "ssl"},
    "icloud": {"host": "imap.mail.me.com", "port": 993, "security": "ssl"},
    "aol": {"host": "imap.aol.com", "port": 993, "security": "ssl"},
    "custom": {"host": "", "port": 993, "security": "ssl"},
    "self_hosted": {"host": "", "port": 993, "security": "ssl"},
    "enterprise": {"host": "", "port": 993, "security": "ssl"},
    "imap": {"host": "", "port": 993, "security": "ssl"},
}

# ── Extension / notification / scheduler ─────────────────────────────────────

EXTENSION_API_TIMEOUT = 5
EXTENSION_HEARTBEAT_INTERVAL = 30
NOTIFICATIONS_ENABLED = True
DESKTOP_NOTIFICATIONS = True
MAX_NOTIFICATIONS = 100
SCHEDULER_ENABLED = True
SYNC_INTERVAL_HOURS = 1
CLEANUP_INTERVAL_HOURS = 24
METRICS_INTERVAL_HOURS = 1
