# MailPilot Connector & Plugin Panel

A production-ready modular connector and plugin management system for the MailPilot platform.  
Provides a full REST API for installing, configuring, and monitoring integrations with external services.

---

## Overview

The Connector Panel manages the entire lifecycle of platform integrations:

- **Marketplace** — browse and install from a catalog of pre-built connectors
- **Connectors** — configure, enable/disable, and sync installed connectors
- **Plugins** — manage platform plugins and their per-tenant permissions
- **OAuth** — securely store and manage OAuth 2.0 tokens (never exposed in API responses)
- **Webhooks** — register outbound webhook endpoints with HMAC signature delivery
- **Queues** — monitor async job queues and dead-letter queues per tenant
- **Logs** — searchable connector activity logs with real-time WebSocket streaming
- **Health** — live health metrics for connectors, queues, and plugins
- **Events** — publish/subscribe event bus with real-time WebSocket streaming

---

## Quick Start

### 1. Install dependencies

```bash
pip install fastapi uvicorn httpx cryptography pydantic
# Optional for OCR fallback:
pip install pdfplumber pytesseract Pillow
```

### 2. Configure environment

```bash
cp platform/connectors-panel/.env.example .env
# Edit .env and fill in at minimum:
#   CONNECTOR_PANEL_ENCRYPTION_KEY  (generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

### 3. Mount the panel into your FastAPI app

```python
# main.py
from fastapi import FastAPI
from platform.connectors_panel.backend.router import setup

app = FastAPI(title="MailPilot")

# Initialize DB and mount all connector panel routes
panel_router = setup()
app.include_router(panel_router)

# Optional: explicit DB path
# panel_router = setup(db_path="/data/connectors_panel.db")
```

### 4. Start the server

```bash
uvicorn main:app --reload
```

### 5. View the API docs

```
http://localhost:8000/docs
```

---

## Architecture

```
platform/connectors-panel/
├── backend/
│   ├── models.py          # Pydantic v2 models (ConnectorStatus, InstalledConnector, OAuthToken, ...)
│   ├── db.py              # Isolated SQLite DB wrapper (ConnectorPanelDB)
│   ├── router.py          # Main APIRouter — mounts all sub-routers
│   ├── marketplace.py     # GET/POST /marketplace/connectors
│   ├── connectors.py      # CRUD /connectors
│   ├── plugins.py         # Plugin discovery & permissions /plugins
│   ├── oauth.py           # OAuth token management /oauth
│   ├── webhooks.py        # Webhook endpoints /webhooks
│   ├── queues.py          # Job queue management /queues
│   ├── logs.py            # Log management + WS streaming /logs
│   ├── health.py          # Health endpoints /health
│   └── events.py          # Event pub/sub + WS streaming /events
├── shared/
│   ├── constants.py       # Event types, OAuth providers, categories
│   ├── event_bus.py       # Async singleton EventBus
│   └── utils.py           # Encryption, HMAC, formatting utilities
├── sdk/
│   ├── plugin_sdk.py      # BasePlugin, ConnectorPlugin, OAuthPlugin, WebhookPlugin
│   └── boilerplate.py     # CLI scaffold generator
├── plugins/               # Bundled connector plugins
│   ├── whatsapp/          # WhatsApp Business API
│   ├── gmail/             # Gmail OAuth
│   ├── openai/            # OpenAI GPT
│   ├── ocr_engine/        # OCR pipeline bridge
│   ├── shopify/           # Shopify OAuth + webhooks
│   ├── slack/             # Slack OAuth + Events API
│   └── webhook_listener/  # Generic webhook receiver
├── migrations/
│   └── 001_connector_tables.sql
├── docs/
│   └── PLUGIN_SDK.md
└── .env.example

Database (isolated, next to the package):
    platform/connectors_panel.db     ← SQLite WAL, created on first startup
```

---

## Mounting the Panel

```python
from fastapi import FastAPI
from platform.connectors_panel.backend.router import setup

app = FastAPI()

# One-line setup — initialises the DB and returns the configured router
app.include_router(setup())
```

The panel is mounted at `/api/connector-panel`. All endpoints are prefixed accordingly.

---

## Available Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/connector-panel/` | Panel version and status |
| **Marketplace** | | |
| GET | `/marketplace/connectors` | List available connectors |
| GET | `/marketplace/connectors/{id}` | Connector details |
| POST | `/marketplace/connectors/{id}/install` | Install connector |
| GET | `/marketplace/categories` | List categories |
| GET | `/marketplace/featured` | Featured connectors |
| **Connectors** | | |
| GET | `/connectors?tenant_id=` | List installed connectors |
| GET | `/connectors/{id}` | Get connector |
| PUT | `/connectors/{id}` | Update config |
| DELETE | `/connectors/{id}` | Uninstall |
| POST | `/connectors/{id}/enable` | Enable |
| POST | `/connectors/{id}/disable` | Disable |
| POST | `/connectors/{id}/sync` | Trigger sync |
| POST | `/connectors/{id}/test` | Test connection |
| **OAuth** | | |
| GET | `/oauth/providers` | List OAuth providers |
| GET | `/oauth/tokens?tenant_id=` | List tokens (no values exposed) |
| POST | `/oauth/tokens` | Store token (encrypted) |
| DELETE | `/oauth/tokens/{id}` | Revoke token |
| POST | `/oauth/tokens/{id}/refresh` | Refresh token |
| GET | `/oauth/authorize/{provider}` | Start OAuth flow |
| **Webhooks** | | |
| GET | `/webhooks?tenant_id=` | List webhooks |
| POST | `/webhooks` | Create webhook |
| PUT | `/webhooks/{id}` | Update webhook |
| DELETE | `/webhooks/{id}` | Delete webhook |
| POST | `/webhooks/{id}/test` | Test delivery |
| POST | `/webhooks/receive/{connector_id}` | Receive inbound webhook |
| **Queues** | | |
| GET | `/queues/stats` | Queue statistics |
| GET | `/queues/jobs` | List jobs |
| POST | `/queues/jobs/{id}/retry` | Retry failed job |
| GET | `/queues/dead-letters` | Dead-letter queue |
| **Logs** | | |
| GET | `/logs?tenant_id=` | List logs |
| GET | `/logs/summary` | Log summary |
| DELETE | `/logs` | Clear logs |
| WS | `/logs/stream` | Real-time log stream |
| **Health** | | |
| GET | `/health` | System health |
| GET | `/health/connectors` | All connector health |
| GET | `/health/queues` | Queue health |
| POST | `/health/connectors/{id}/heartbeat` | Update heartbeat |
| **Events** | | |
| GET | `/events?tenant_id=` | List events |
| GET | `/events/types` | Available event types |
| POST | `/events/publish` | Publish event |
| WS | `/events/subscribe` | Real-time event stream |
| **Plugins** | | |
| GET | `/plugins` | List all plugins |
| GET | `/plugins/health` | Plugin system health |
| POST | `/plugins/{id}/enable` | Enable plugin |
| POST | `/plugins/{id}/disable` | Disable plugin |
| GET | `/plugins/{id}/permissions` | Get permissions |
| POST | `/plugins/{id}/permissions` | Grant permission |

---

## Plugin Development Guide

### Generate a scaffold

```bash
python -m platform.connectors_panel.sdk.boilerplate \
  --name my_crm \
  --category crm \
  --type oauth \
  --output ./platform/connectors-panel/plugins
```

This creates:
```
my_crm/
  __init__.py
  plugin.json
  module.py
  permissions.json
  events.json
```

### Implement your plugin

Edit `module.py` and implement the required methods.  
See `docs/PLUGIN_SDK.md` for the full SDK reference.

### Register your plugin

Place the plugin directory inside `platform/plugins/` (for platform-wide plugins)
or `platform/connectors-panel/plugins/` (for connector-specific plugins).

The plugin is auto-discovered via the `plugin.json` manifest on the next startup.

---

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `CONNECTOR_PANEL_ENCRYPTION_KEY` | Yes (production) | Fernet key for token/secret encryption |
| `CONNECTOR_PANEL_DB_PATH` | No | Override SQLite DB path |
| `WHATSAPP_API_KEY` | For WhatsApp | Meta System User Access Token |
| `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` | For Gmail | Google OAuth credentials |
| `OPENAI_API_KEY` | For OpenAI | OpenAI API key |
| `SHOPIFY_API_KEY` / `SHOPIFY_API_SECRET` | For Shopify | Shopify app credentials |
| `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` | For Slack | Slack app credentials |

---

## Security Notes

1. **OAuth tokens** — access and refresh tokens are encrypted at rest using Fernet symmetric encryption before being stored in SQLite. They are **never** returned in API responses.

2. **Webhook secrets** — signing secrets are Fernet-encrypted at rest. The `WebhookEndpointSafe` model never includes the secret field.

3. **HMAC verification** — all inbound webhooks validate HMAC-SHA256 signatures using constant-time comparison (`hmac.compare_digest`) to prevent timing attacks.

4. **Encryption key** — set `CONNECTOR_PANEL_ENCRYPTION_KEY` to a proper Fernet key in production. If unset, a key is auto-generated per process (tokens will be unreadable after restart).

5. **SQLite WAL mode** — the database uses WAL (Write-Ahead Logging) for concurrent read access and `synchronous=NORMAL` for a balance of durability and performance.

6. **Tenant isolation** — all data queries are scoped by `tenant_id`. Never query without providing a tenant.
