# MailPilot Plugin SDK Reference

This guide covers everything you need to create, test, and deploy a connector plugin for the MailPilot platform.

---

## Table of Contents

1. [Creating a Connector Plugin](#1-creating-a-connector-plugin)
2. [Plugin Manifest Reference](#2-plugin-manifest-reference)
3. [SDK Class Reference](#3-sdk-class-reference)
4. [Event System Guide](#4-event-system-guide)
5. [OAuth Integration Guide](#5-oauth-integration-guide)
6. [Webhook Integration Guide](#6-webhook-integration-guide)
7. [Testing Your Plugin](#7-testing-your-plugin)
8. [Example Code](#8-example-code)

---

## 1. Creating a Connector Plugin

### Using the scaffold generator

The fastest way to start is the CLI generator:

```bash
python -m platform.connectors_panel.sdk.boilerplate \
  --name my_service \
  --category communication \
  --type connector
```

This creates a directory with all required files:

```
my_service/
  __init__.py        # Empty package marker
  plugin.json        # Plugin manifest
  module.py          # Plugin implementation (edit this)
  permissions.json   # Declared permissions
  events.json        # Published/subscribed events
```

### Manual creation

1. Create a directory under `platform/connectors-panel/plugins/<your_plugin>/`
2. Add a `plugin.json` manifest (see Section 2)
3. Add a `module.py` with your plugin class (see Section 3)
4. Add `__init__.py` (empty file)

### Directory placement

| Location | Description |
|----------|-------------|
| `platform/plugins/<name>/` | Platform-wide plugin (shared infrastructure) |
| `platform/connectors-panel/plugins/<name>/` | Connector-specific plugin (discovered by the panel) |

Both locations are scanned automatically on startup.

---

## 2. Plugin Manifest Reference

Every plugin must have a `plugin.json` file in its directory.

### Full manifest schema

```json
{
  "name": "my_connector",
  "version": "1.0.0",
  "type": "connector",
  "category": "communication",
  "description": "Human-readable description",
  "author": "Your Name",
  "enabled": false,
  "multiTenant": true,
  "supports_oauth": false,
  "supports_api_key": true,
  "supports_webhook": false,
  "queue_enabled": true,
  "oauth_provider": "google",
  "oauth_scopes": [],
  "permissions": ["data.read", "data.write"],
  "events": ["my_service.data.synced"],
  "webhook_events": [],
  "config_schema": {
    "api_key": { "type": "secret", "required": true },
    "base_url": { "type": "string", "required": false }
  }
}
```

### Field reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique snake_case identifier |
| `version` | string | Yes | Semver (e.g. `1.0.0`) |
| `type` | string | Yes | Always `"connector"` for connectors |
| `category` | string | Yes | `communication`, `erp`, `crm`, `tracking`, `ocr`, `search`, `ai`, `ecommerce`, `webhook`, `internal` |
| `description` | string | Yes | One-sentence description |
| `author` | string | Yes | Author/organization name |
| `enabled` | boolean | No | Initial enabled state (default: `false`) |
| `multiTenant` | boolean | No | Whether the plugin supports multiple tenants (default: `true`) |
| `supports_oauth` | boolean | No | Set to `true` if using OAuth 2.0 |
| `supports_api_key` | boolean | No | Set to `true` if using an API key |
| `supports_webhook` | boolean | No | Set to `true` if receiving inbound webhooks |
| `queue_enabled` | boolean | No | Set to `true` to enable async job queue |
| `oauth_provider` | string | No | Provider ID: `google`, `microsoft`, `shopify`, `slack`, etc. |
| `oauth_scopes` | array | No | Required OAuth scopes |
| `permissions` | array | No | Permission strings (e.g. `["messages.read"]`) |
| `events` | array | No | Event types this plugin publishes |
| `webhook_events` | array | No | Webhook event names from the external system |
| `config_schema` | object | No | JSON Schema for the plugin configuration |

### Config schema field types

| Type | Description |
|------|-------------|
| `"string"` | Plain text value |
| `"secret"` | Value will be encrypted at rest, masked in API responses |
| `"integer"` | Whole number |
| `"number"` | Floating-point number |
| `"boolean"` | True/false |
| `"array"` | JSON array |

---

## 3. SDK Class Reference

All SDK classes are in `platform/connectors_panel/sdk/plugin_sdk.py`.

### BasePlugin (abstract)

The root base class for all plugins.

```python
from platform.connectors_panel.sdk.plugin_sdk import BasePlugin

class MyPlugin(BasePlugin):
    @property
    def plugin_id(self) -> str: return "my_plugin"

    @property
    def name(self) -> str: return "My Plugin"

    @property
    def version(self) -> str: return "1.0.0"

    @property
    def category(self) -> str: return "internal"
```

#### Abstract properties

| Property | Type | Description |
|----------|------|-------------|
| `plugin_id` | `str` | Unique identifier (matches `plugin.json` name) |
| `name` | `str` | Human-readable name |
| `version` | `str` | Semver version string |
| `category` | `str` | Plugin category |

#### Lifecycle methods (override as needed)

| Method | Signature | Description |
|--------|-----------|-------------|
| `on_install` | `(tenant_id: str, config: dict) -> bool` | Called on first install |
| `on_uninstall` | `(tenant_id: str) -> bool` | Called on uninstall |
| `on_enable` | `(tenant_id: str) -> bool` | Called when enabled |
| `on_disable` | `(tenant_id: str) -> bool` | Called when disabled |
| `health_check` | `(tenant_id: str) -> dict` | Returns `{"status": "ok"|"degraded"|"error", "message": str}` |
| `fetch_data` | `(tenant_id: str, **kwargs) -> list` | Fetch records from external system |
| `handle_event` | `(event_type, payload, tenant_id) -> None` | React to platform events |
| `get_permissions` | `() -> list[str]` | Required permission strings |
| `get_events` | `() -> list[str]` | Published event type strings |

#### Internal utilities

```python
# Write a log entry
self._log("INFO", "Something happened", tenant_id, {"key": "value"})
self._log("ERROR", "Request failed", tenant_id, {"status_code": 500})
```

---

### ConnectorPlugin(BasePlugin)

For plugins that sync data with external APIs.

```python
from platform.connectors_panel.sdk.plugin_sdk import ConnectorPlugin, ConnectorSyncResult

class MyConnector(ConnectorPlugin):
    def sync(self, tenant_id: str) -> ConnectorSyncResult:
        records = self.fetch_data(tenant_id)
        return ConnectorSyncResult(
            success=True,
            records_processed=len(records),
            duration_ms=150.0,
        )

    def test_connection(self, tenant_id: str, config: dict) -> bool:
        # Verify API credentials work
        return True

    def get_config_schema(self) -> dict:
        return {
            "type": "object",
            "required": ["api_key"],
            "properties": {
                "api_key": {"type": "string", "description": "API Key"},
            },
        }
```

#### ConnectorSyncResult dataclass

```python
@dataclass
class ConnectorSyncResult:
    success: bool
    records_processed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
```

---

### OAuthPlugin(ConnectorPlugin)

For OAuth 2.0 connectors. Extends `ConnectorPlugin` with auth flow methods.

```python
from platform.connectors_panel.sdk.plugin_sdk import OAuthPlugin

class MyOAuthConnector(OAuthPlugin):
    def get_auth_url(self, tenant_id: str, redirect_uri: str) -> str:
        return f"https://example.com/oauth/authorize?client_id=...&redirect_uri={redirect_uri}"

    def exchange_code(self, tenant_id: str, code: str) -> dict:
        # POST to token endpoint
        return {
            "access_token": "...",
            "refresh_token": "...",
            "expires_in": 3600,
            "token_type": "bearer",
        }

    def refresh_token(self, tenant_id: str) -> dict:
        # Use stored refresh token to get new access token
        stored = self.get_stored_token(tenant_id)
        # ... perform refresh ...
        return {"access_token": "new_token", ...}
```

#### get_stored_token

Retrieve the decrypted token for a tenant:

```python
token = self.get_stored_token(tenant_id)
if token:
    access_token = token["access_token"]
    refresh_token = token.get("refresh_token")
    expires_at = token.get("expires_at")
```

---

### WebhookPlugin(ConnectorPlugin)

For plugins that receive inbound HTTP webhooks.

```python
from platform.connectors_panel.sdk.plugin_sdk import WebhookPlugin

class MyWebhookConnector(WebhookPlugin):
    def handle_webhook(self, payload: dict, headers: dict, tenant_id: str) -> dict:
        event_type = headers.get("X-My-Event", "webhook.received")
        # Process payload...
        return {"processed": True, "event_type": event_type}

    def validate_signature(self, payload: bytes, headers: dict) -> bool:
        import os
        from platform.connectors_panel.shared.utils import verify_hmac
        secret = os.environ.get("MY_WEBHOOK_SECRET", "")
        sig = headers.get("X-Signature", "")
        return verify_hmac(secret, payload, sig) if secret else True
```

---

## 4. Event System Guide

The MailPilot event bus (`EventBus`) provides async pub/sub for cross-connector communication.

### Publishing events

```python
import asyncio
from platform.connectors_panel.shared.event_bus import get_event_bus

async def my_async_function():
    bus = get_event_bus()
    event_id = await bus.publish(
        event_type="invoice.created",
        source="my_connector",
        tenant_id="tenant_123",
        payload={
            "invoice_id": "INV-001",
            "amount": 1500.00,
            "currency": "USD",
        },
    )
    print(f"Published event: {event_id}")

# From synchronous code:
loop = asyncio.new_event_loop()
loop.run_until_complete(my_async_function())
loop.close()
```

### Subscribing to events

```python
from platform.connectors_panel.shared.event_bus import get_event_bus

bus = get_event_bus()

async def handle_invoice(event_type: str, source: str, tenant_id: str, payload: dict):
    print(f"Invoice received from {source}: {payload['invoice_id']}")

# Subscribe to specific events
bus.subscribe(
    subscriber_id="my_connector",
    event_types=["invoice.created", "invoice.updated"],
    callback=handle_invoice,
)

# Subscribe to ALL events
bus.subscribe("audit_connector", None, handle_invoice)
```

### Unsubscribing

```python
bus.unsubscribe("my_connector")
```

### Getting subscriber list

```python
subscribers = bus.get_subscribers("invoice.created")
# Returns: ["my_connector", "audit_connector"]
```

### Supported event types

See `platform/connectors_panel/shared/constants.py` for the full `SUPPORTED_EVENT_TYPES` list.

Key categories:

- `invoice.*` — invoice.created, invoice.paid, invoice.overdue
- `order.*` — order.created, order.fulfilled, order.cancelled
- `email.*` — email.received, email.sent, email.bounced
- `whatsapp.*` — whatsapp.message.received, whatsapp.status.updated
- `shipment.*` — shipment.created, shipment.delivered
- `ocr.*` — ocr.document.processed, ocr.document.failed
- `ai.*` — ai.classification.completed, ai.extraction.completed
- `connector.*` — connector.installed, connector.sync.completed

---

## 5. OAuth Integration Guide

### Step 1: Extend OAuthPlugin

```python
class MyCRMConnector(OAuthPlugin):
    AUTH_URL = "https://mycrm.com/oauth/authorize"
    TOKEN_URL = "https://mycrm.com/oauth/token"

    def get_auth_url(self, tenant_id: str, redirect_uri: str) -> str:
        import os
        from urllib.parse import urlencode
        params = {
            "client_id": os.environ["MYCRM_CLIENT_ID"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "contacts.read contacts.write",
            "state": tenant_id,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, tenant_id: str, code: str) -> dict:
        import httpx, os
        r = httpx.post(self.TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": os.environ["MYCRM_CLIENT_ID"],
            "client_secret": os.environ["MYCRM_CLIENT_SECRET"],
        })
        r.raise_for_status()
        return r.json()
```

### Step 2: Start the OAuth flow via API

```
GET /api/connector-panel/oauth/authorize/mycrm?tenant_id=t1&connector_id=con_abc&redirect_uri=https://...
```

Returns `{"auth_url": "https://mycrm.com/oauth/authorize?..."}`.  
Redirect the user to this URL.

### Step 3: Store the token after callback

After the user authorizes and is redirected back:

```
POST /api/connector-panel/oauth/tokens
{
  "connector_id": "con_abc",
  "tenant_id": "t1",
  "provider": "mycrm",
  "access_token": "...",
  "refresh_token": "...",
  "expires_at": "2026-01-01T00:00:00Z",
  "scopes": ["contacts.read", "contacts.write"]
}
```

The token is **encrypted** before storage. The response never includes the token values.

### Step 4: Retrieve the token in your plugin

```python
token = self.get_stored_token(tenant_id)
if not token:
    raise ValueError("Authorization required")
access_token = token["access_token"]
```

---

## 6. Webhook Integration Guide

### Receiving webhooks

The `WebhookPlugin.handle_webhook()` method is called by the platform when an inbound request arrives at:

```
POST /api/connector-panel/webhooks/receive/{connector_id}
```

The platform:
1. Reads the raw body bytes
2. Calls `validate_signature(body_bytes, headers)`
3. Parses the body as JSON
4. Calls `handle_webhook(payload_dict, headers, tenant_id)`

### Implementing signature validation

```python
def validate_signature(self, payload: bytes, headers: dict) -> bool:
    import os, hmac, hashlib
    secret = os.environ.get("MY_WEBHOOK_SECRET", "")
    if not secret:
        return True  # permissive if no secret configured

    expected = "sha256=" + hmac.new(
        secret.encode(), payload, hashlib.sha256
    ).hexdigest()
    received = headers.get("X-Hub-Signature-256", "")
    return hmac.compare_digest(expected, received)
```

### Registering a webhook endpoint

```
POST /api/connector-panel/webhooks
{
  "connector_id": "con_abc",
  "tenant_id": "t1",
  "url": "https://yourapp.com/webhooks/myservice",
  "events": ["order.created", "order.fulfilled"],
  "secret": "my_secret_123"
}
```

### Webhook HMAC delivery

When the platform delivers events to registered webhook URLs, it signs the payload:

```
X-Hub-Signature-256: sha256=<hex_digest>
X-MailPilot-Event: order.created
Content-Type: application/json
```

Verify on the receiving end:

```python
import hmac, hashlib

def verify_mailpilot_webhook(body: bytes, signature: str, secret: str) -> bool:
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
```

---

## 7. Testing Your Plugin

### Unit test template

```python
import pytest
from platform.connectors_panel.plugins.my_service.module import MyServiceConnector

@pytest.fixture
def connector():
    return MyServiceConnector()

def test_plugin_id(connector):
    assert connector.plugin_id == "my_service"

def test_on_install(connector):
    result = connector.on_install("test_tenant", {"api_key": "test_key"})
    assert result is True

def test_health_check_no_key(connector, monkeypatch):
    monkeypatch.delenv("MY_SERVICE_API_KEY", raising=False)
    health = connector.health_check("test_tenant")
    assert health["status"] == "error"

def test_health_check_ok(connector, monkeypatch, requests_mock):
    monkeypatch.setenv("MY_SERVICE_API_KEY", "valid_key")
    requests_mock.get("https://api.myservice.com/ping", json={"status": "ok"})
    health = connector.health_check("test_tenant")
    assert health["status"] == "ok"

def test_validate_signature(connector):
    import hmac, hashlib
    secret = "test_secret"
    payload = b'{"event": "test"}'
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert connector.validate_signature(payload, {"X-Hub-Signature-256": sig}) is True

def test_validate_signature_invalid(connector):
    assert connector.validate_signature(b"payload", {"X-Hub-Signature-256": "sha256=invalid"}) is False
```

### Integration test with the panel router

```python
from fastapi.testclient import TestClient
from fastapi import FastAPI
from platform.connectors_panel.backend.router import setup

app = FastAPI()
app.include_router(setup(db_path=":memory:"))
client = TestClient(app)

def test_marketplace_list():
    response = client.get("/api/connector-panel/marketplace/connectors")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 10  # 10 catalog connectors

def test_install_connector():
    response = client.post(
        "/api/connector-panel/marketplace/connectors/gmail/install",
        json={
            "connector_id": "gmail",
            "tenant_id": "test_tenant",
            "config": {},
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "installing"
```

---

## 8. Example Code

### Minimal connector plugin

```python
from platform.connectors_panel.sdk.plugin_sdk import ConnectorPlugin

class MyMinimalConnector(ConnectorPlugin):
    @property
    def plugin_id(self): return "my_minimal"

    @property
    def name(self): return "My Minimal Connector"

    @property
    def version(self): return "1.0.0"

    @property
    def category(self): return "internal"

    def fetch_data(self, tenant_id, **kwargs):
        return [{"id": 1, "name": "Record 1"}, {"id": 2, "name": "Record 2"}]

    def test_connection(self, tenant_id, config):
        return True

    def health_check(self, tenant_id):
        return {"status": "ok", "message": "Running"}
```

### OAuth connector with token refresh

```python
import os
from platform.connectors_panel.sdk.plugin_sdk import OAuthPlugin

class HubSpotConnector(OAuthPlugin):
    @property
    def plugin_id(self): return "hubspot_connector"

    @property
    def name(self): return "HubSpot CRM"

    @property
    def version(self): return "1.0.0"

    @property
    def category(self): return "crm"

    def get_auth_url(self, tenant_id, redirect_uri):
        from urllib.parse import urlencode
        return "https://app.hubspot.com/oauth/authorize?" + urlencode({
            "client_id": os.environ["HUBSPOT_CLIENT_ID"],
            "redirect_uri": redirect_uri,
            "scope": "contacts crm.objects.deals.read",
            "state": tenant_id,
        })

    def exchange_code(self, tenant_id, code):
        import httpx
        r = httpx.post("https://api.hubapi.com/oauth/v1/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": os.environ["HUBSPOT_CLIENT_ID"],
            "client_secret": os.environ["HUBSPOT_CLIENT_SECRET"],
            "redirect_uri": os.environ["HUBSPOT_REDIRECT_URI"],
        })
        r.raise_for_status()
        return r.json()

    def refresh_token(self, tenant_id):
        stored = self.get_stored_token(tenant_id)
        import httpx
        r = httpx.post("https://api.hubapi.com/oauth/v1/token", data={
            "grant_type": "refresh_token",
            "refresh_token": stored["refresh_token"],
            "client_id": os.environ["HUBSPOT_CLIENT_ID"],
            "client_secret": os.environ["HUBSPOT_CLIENT_SECRET"],
        })
        r.raise_for_status()
        return r.json()

    def fetch_data(self, tenant_id, **kwargs):
        token = self.get_stored_token(tenant_id)
        if not token:
            return []
        import httpx
        r = httpx.get(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers={"Authorization": f"Bearer {token['access_token']}"},
            params={"limit": kwargs.get("limit", 10)},
        )
        r.raise_for_status()
        return r.json().get("results", [])
```

### Webhook connector with event routing

```python
import os
from platform.connectors_panel.sdk.plugin_sdk import WebhookPlugin

class StripeConnector(WebhookPlugin):
    @property
    def plugin_id(self): return "stripe_connector"

    @property
    def name(self): return "Stripe"

    @property
    def version(self): return "1.0.0"

    @property
    def category(self): return "ecommerce"

    def validate_signature(self, payload: bytes, headers: dict) -> bool:
        import stripe
        sig = headers.get("Stripe-Signature", "")
        secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        try:
            stripe.Webhook.construct_event(payload, sig, secret)
            return True
        except Exception:
            return False

    def handle_webhook(self, payload: dict, headers: dict, tenant_id: str) -> dict:
        event_type_map = {
            "payment_intent.succeeded": "invoice.paid",
            "invoice.created": "invoice.created",
            "invoice.payment_failed": "invoice.overdue",
            "customer.subscription.created": "order.created",
        }
        stripe_type = payload.get("type", "unknown")
        mailpilot_type = event_type_map.get(stripe_type, "webhook.received")

        self._publish(mailpilot_type, tenant_id, payload.get("data", {}))
        return {"processed": True, "event_type": mailpilot_type}

    def _publish(self, event_type, tenant_id, data):
        import asyncio
        from platform.connectors_panel.shared.event_bus import get_event_bus
        bus = get_event_bus()
        loop = asyncio.new_event_loop()
        loop.run_until_complete(bus.publish(event_type, self.plugin_id, tenant_id, data))
        loop.close()
```
