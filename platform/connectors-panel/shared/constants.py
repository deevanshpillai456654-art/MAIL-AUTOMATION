"""
Shared constants for the MailPilot Connector & Plugin Panel.
"""
from __future__ import annotations

CONNECTOR_PANEL_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Supported event types
# ---------------------------------------------------------------------------

SUPPORTED_EVENT_TYPES: list[str] = [
    # Invoice / finance
    "invoice.created",
    "invoice.updated",
    "invoice.paid",
    "invoice.overdue",
    "invoice.cancelled",
    # Shipment / tracking
    "shipment.created",
    "shipment.updated",
    "shipment.delivered",
    "shipment.failed",
    "shipment.returned",
    # Email
    "email.received",
    "email.sent",
    "email.bounced",
    "email.opened",
    "email.clicked",
    "email.spam_reported",
    # WhatsApp
    "whatsapp.message.received",
    "whatsapp.message.sent",
    "whatsapp.status.updated",
    "whatsapp.media.received",
    # Order / ecommerce
    "order.created",
    "order.updated",
    "order.fulfilled",
    "order.cancelled",
    "order.refunded",
    "product.created",
    "product.updated",
    "product.deleted",
    # CRM
    "contact.created",
    "contact.updated",
    "contact.deleted",
    "deal.created",
    "deal.updated",
    "deal.closed",
    # AI / processing
    "ai.classification.completed",
    "ai.extraction.completed",
    "ai.summary.completed",
    # OCR
    "ocr.document.processed",
    "ocr.document.failed",
    # Slack
    "slack.message.received",
    "slack.notification.sent",
    "slack.channel.created",
    # ERP
    "erp.sync.completed",
    "erp.sync.failed",
    "erp.record.created",
    "erp.record.updated",
    # Webhook
    "webhook.received",
    "webhook.failed",
    "webhook.retry",
    # Connector lifecycle
    "connector.installed",
    "connector.uninstalled",
    "connector.enabled",
    "connector.disabled",
    "connector.sync.started",
    "connector.sync.completed",
    "connector.sync.failed",
    "connector.health.degraded",
    "connector.health.recovered",
]

# ---------------------------------------------------------------------------
# Webhook / queue settings
# ---------------------------------------------------------------------------

DEFAULT_WEBHOOK_TIMEOUT_SECONDS: int = 30
MAX_RETRY_ATTEMPTS: int = 3
LOG_RETENTION_DAYS: int = 30
MAX_QUEUE_JOB_AGE_DAYS: int = 7
WEBHOOK_SIGNATURE_HEADER: str = "X-Hub-Signature-256"
WEBHOOK_TIMESTAMP_HEADER: str = "X-Webhook-Timestamp"
HEARTBEAT_INTERVAL_SECONDS: int = 60
HEALTH_DEGRADED_THRESHOLD_FAILURES: int = 3

# ---------------------------------------------------------------------------
# OAuth providers
# ---------------------------------------------------------------------------

OAUTH_PROVIDERS: dict[str, dict] = {
    "google": {
        "display_name": "Google",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": ["openid", "email", "profile"],
        "gmail_scopes": [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.modify",
        ],
        "required_config": ["client_id", "client_secret", "redirect_uri"],
        "supports_refresh": True,
        "icon": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/google.svg",
    },
    "microsoft": {
        "display_name": "Microsoft",
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": ["openid", "email", "profile", "offline_access"],
        "mail_scopes": ["Mail.Read", "Mail.Send", "Mail.ReadWrite"],
        "required_config": ["client_id", "client_secret", "redirect_uri", "tenant"],
        "supports_refresh": True,
        "icon": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/microsoft.svg",
    },
    "whatsapp_business": {
        "display_name": "WhatsApp Business",
        "auth_url": "https://www.facebook.com/v17.0/dialog/oauth",
        "token_url": "https://graph.facebook.com/v17.0/oauth/access_token",
        "scopes": ["whatsapp_business_management", "whatsapp_business_messaging"],
        "required_config": ["app_id", "app_secret", "redirect_uri"],
        "supports_refresh": False,
        "icon": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/whatsapp.svg",
    },
    "shopify": {
        "display_name": "Shopify",
        "auth_url": "https://{shop}.myshopify.com/admin/oauth/authorize",
        "token_url": "https://{shop}.myshopify.com/admin/oauth/access_token",
        "scopes": ["read_orders", "write_orders", "read_products", "write_products", "read_customers"],
        "required_config": ["api_key", "api_secret", "shop", "redirect_uri"],
        "supports_refresh": False,
        "icon": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/shopify.svg",
    },
    "slack": {
        "display_name": "Slack",
        "auth_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "scopes": ["channels:read", "chat:write", "channels:history", "users:read"],
        "required_config": ["client_id", "client_secret", "redirect_uri"],
        "supports_refresh": False,
        "icon": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/slack.svg",
    },
    "hubspot": {
        "display_name": "HubSpot",
        "auth_url": "https://app.hubspot.com/oauth/authorize",
        "token_url": "https://api.hubapi.com/oauth/v1/token",
        "scopes": ["contacts", "crm.objects.deals.read", "crm.objects.deals.write"],
        "required_config": ["client_id", "client_secret", "redirect_uri"],
        "supports_refresh": True,
        "icon": "https://cdn.jsdelivr.net/npm/simple-icons@v9/icons/hubspot.svg",
    },
}

# ---------------------------------------------------------------------------
# Permission levels
# ---------------------------------------------------------------------------

PERMISSION_LEVELS: dict[str, dict] = {
    "read": {
        "label": "Read",
        "description": "Can read data but not modify it",
        "level": 1,
    },
    "write": {
        "label": "Write",
        "description": "Can read and write data",
        "level": 2,
    },
    "admin": {
        "label": "Admin",
        "description": "Full access including configuration changes",
        "level": 3,
    },
}

# ---------------------------------------------------------------------------
# Connector categories
# ---------------------------------------------------------------------------

CONNECTOR_CATEGORIES: list[dict] = [
    {"id": "communication", "label": "Communication",  "icon": "message-circle"},
    {"id": "erp",           "label": "ERP",            "icon": "layers"},
    {"id": "crm",           "label": "CRM",            "icon": "users"},
    {"id": "tracking",      "label": "Tracking",       "icon": "map-pin"},
    {"id": "ecommerce",     "label": "E-Commerce",     "icon": "shopping-cart"},
    {"id": "accounting",    "label": "Accounting",     "icon": "dollar-sign"},
    {"id": "support",       "label": "Support",        "icon": "life-buoy"},
    {"id": "ai",            "label": "AI",             "icon": "cpu"},
    {"id": "ocr",           "label": "OCR",            "icon": "file-text"},
    {"id": "webhook",       "label": "Webhook",        "icon": "zap"},
    {"id": "search",        "label": "Search",         "icon": "search"},
    {"id": "internal",      "label": "Internal",       "icon": "server"},
]

# ---------------------------------------------------------------------------
# Marketplace featured connector IDs
# ---------------------------------------------------------------------------

FEATURED_CONNECTOR_IDS: list[str] = [
    "salesforce", "dhl", "sap", "hubspot", "aftership",
    "quickbooks", "whatsapp", "gmail", "shopify", "anthropic",
]
