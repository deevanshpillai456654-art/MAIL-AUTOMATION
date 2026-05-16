"""Shopify Advanced Connector — orders, customers, products, inventory, webhooks."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..sdk.base import ConnectorBase
from ..sdk.manifest import (
    ConnectorManifest, OAuthConfig, WebhookConfig,
    SyncConfig, Permission,
)
from .service import ShopifyAPI

MANIFEST = ConnectorManifest(
    id="shopify",
    name="Shopify",
    category="ecommerce",
    description="Sync orders, customers, products, and inventory from Shopify.",
    version="1.0.0",
    icon="🛍️",
    supports_oauth=True,
    supports_webhook=True,
    oauth=OAuthConfig(
        provider_id="shopify",
        auth_url="https://{shop}.myshopify.com/admin/oauth/authorize",
        token_url="https://{shop}.myshopify.com/admin/oauth/access_token",
        scopes=["read_orders", "write_orders", "read_products", "write_products",
                "read_customers", "write_customers", "read_inventory"],
        supports_refresh=False,
    ),
    webhook=WebhookConfig(
        events=["orders/create", "orders/updated", "orders/fulfilled",
                "orders/cancelled", "customers/create", "customers/update",
                "products/create", "products/update", "checkouts/create",
                "refunds/create"],
        signature_header="X-Shopify-Hmac-SHA256",
    ),
    sync=SyncConfig(
        entities=["orders", "customers", "products"],
        default_interval_seconds=1800,
    ),
    permissions=[
        Permission("read_orders", "Read Orders", "Access order data"),
        Permission("read_customers", "Read Customers", "Access customer data"),
        Permission("read_products", "Read Products", "Access product catalog"),
        Permission("read_inventory", "Read Inventory", "Access inventory levels"),
    ],
    config_schema={
        "api_key": {"type": "string", "required": True},
        "api_secret": {"type": "string", "required": True, "secret": True},
        "shop": {"type": "string", "required": True, "description": "mystore (without .myshopify.com)"},
        "webhook_secret": {"type": "string", "required": False, "secret": True},
    },
    emits_events=["order.created", "order.updated", "order.fulfilled",
                  "order.cancelled", "order.refunded",
                  "product.created", "product.updated"],
)


class ShopifyConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 2.0   # Shopify: 2 req/s burst 40
    RATE_BURST = 40.0

    def _shop(self) -> str:
        return self.config.get("shop", "")

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        return ShopifyAPI.get_auth_url(
            self.config["api_key"], self._shop(), redirect_uri, state
        )

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        client = self._get_http()
        data = await ShopifyAPI.exchange_code(
            client, self.config["api_key"], self.config["api_secret"],
            self._shop(), code,
        )
        # Shopify tokens never expire
        self._store_token(
            access_token=data["access_token"],
            refresh_token=None,
            expires_at=None,
            scopes=data.get("scope", "").split(","),
        )
        return data

    async def refresh_access_token(self) -> str:
        # Shopify doesn't support refresh; return current token
        tok = self._get_token()
        if not tok:
            raise RuntimeError("No access token. Re-install the connector.")
        return tok["access_token"]

    async def on_install(self) -> None:
        await super().on_install()
        await self._register_webhooks()

    async def _register_webhooks(self) -> None:
        try:
            token = await self.get_valid_token()
            client = self._get_http()
            shop = self._shop()
            # Get the platform's webhook URL from config or env
            import os
            base_url = os.environ.get("PLATFORM_BASE_URL", "")
            if not base_url:
                return
            webhook_url = (
                f"{base_url}/api/connector-panel/engine/webhook/"
                f"{self.instance_id}/{self.tenant_id}"
            )
            topics = ["orders/create", "orders/updated", "orders/fulfilled",
                      "orders/cancelled", "refunds/create",
                      "customers/create", "products/create", "products/update"]
            existing = await ShopifyAPI.list_webhooks(client, shop, token)
            existing_topics = {w["topic"] for w in existing}
            for topic in topics:
                if topic not in existing_topics:
                    await ShopifyAPI.register_webhook(client, shop, token, topic, webhook_url)
            self._log("INFO", f"Registered {len(topics)} Shopify webhooks")
        except Exception as exc:
            self._log("WARN", f"Could not register webhooks: {exc}")

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        token = await self.get_valid_token()
        client = self._get_http()
        shop = self._shop()
        total = 0

        if entity == "orders":
            orders = await ShopifyAPI.get_orders(client, shop, token)
            for o in orders:
                self._publish_event("order.created" if o.get("created_at") else "order.updated",
                                    {"source": "shopify", "order_id": o["id"],
                                     "order_number": o.get("order_number"),
                                     "total": o.get("total_price"),
                                     "status": o.get("fulfillment_status")})
            total = len(orders)

        elif entity == "customers":
            customers = await ShopifyAPI.get_customers(client, shop, token)
            for c in customers:
                self._upsert_crm_contact(c)
            total = len(customers)

        elif entity == "products":
            products = await ShopifyAPI.get_products(client, shop, token)
            for p in products:
                self._publish_event("product.created",
                                    {"source": "shopify", "product_id": p["id"],
                                     "title": p.get("title"),
                                     "status": p.get("status")})
            total = len(products)

        return {"synced": total, "entity": entity}

    def _upsert_crm_contact(self, c: Dict) -> None:
        ext_id = str(c["id"])
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = self.db.fetch_one(
            "SELECT contact_id FROM crm_contacts WHERE external_id=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        )
        if existing:
            return
        cid = f"cnt_{uuid.uuid4().hex}"
        name = c.get("default_address", {}) or {}
        self.db.execute(
            """INSERT INTO crm_contacts
               (contact_id, tenant_id, first_name, last_name, email, phone,
                source, external_id, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,'shopify',?,'active',?,?)""",
            (cid, self.tenant_id,
             c.get("first_name", ""), c.get("last_name", ""),
             c.get("email", ""), c.get("phone", ""),
             ext_id, now, now),
        )

    async def verify_webhook_signature(self, raw_body: bytes,
                                       headers: Dict[str, str]) -> bool:
        secret = self.config.get("api_secret", "")
        hmac_header = headers.get("X-Shopify-Hmac-Sha256", "")
        return ShopifyAPI.verify_webhook(secret, raw_body, hmac_header)

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict[str, str]) -> None:
        topic = headers.get("X-Shopify-Topic", event_type)
        order_id = payload.get("id", "")

        event_map = {
            "orders/create": "order.created",
            "orders/updated": "order.updated",
            "orders/fulfilled": "order.fulfilled",
            "orders/cancelled": "order.cancelled",
            "refunds/create": "order.refunded",
            "products/create": "product.created",
            "products/update": "product.updated",
            "customers/create": "contact.created",
        }
        internal_event = event_map.get(topic, f"shopify.{topic.replace('/','.')}")
        self._publish_event(internal_event, {
            "source": "shopify",
            "shop": self._shop(),
            "id": order_id,
            "topic": topic,
        })
        self._log("INFO", f"Shopify webhook: {topic} id={order_id}")

    async def health_check(self) -> Dict[str, Any]:
        try:
            token = await self.get_valid_token()
            client = self._get_http()
            t0 = time.monotonic()
            ok = await ShopifyAPI.ping(client, self._shop(), token)
            latency = (time.monotonic() - t0) * 1000
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1), "message": "Shopify API reachable"}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
