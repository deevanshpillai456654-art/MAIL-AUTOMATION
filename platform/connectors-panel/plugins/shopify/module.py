"""
Shopify OAuth Connector Plugin

Integrates with the Shopify Admin REST API for order/product/customer sync
and processes real-time Shopify webhooks.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any, Optional
from urllib.parse import urlencode

from ...sdk.plugin_sdk import ConnectorSyncResult, OAuthPlugin


class ShopifyConnector(OAuthPlugin):
    """
    Shopify connector (OAuth 2.0 + webhooks).

    Supports:
    - OAuth authorization code flow
    - REST Admin API for orders, products, customers
    - HMAC-SHA256 webhook verification
    """

    SHOPIFY_API_VERSION = "2024-01"

    @property
    def plugin_id(self) -> str:
        return "shopify_connector"

    @property
    def name(self) -> str:
        return "Shopify"

    @property
    def version(self) -> str:
        return "1.4.2"

    @property
    def category(self) -> str:
        return "ecommerce"

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _get_api_key(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("api_key") or os.environ.get("SHOPIFY_API_KEY", "")

    def _get_api_secret(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("api_secret") or os.environ.get("SHOPIFY_API_SECRET", "")

    def _get_shop(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("shop") or os.environ.get("SHOPIFY_SHOP", "")

    def _get_redirect_uri(self, config: Optional[dict] = None) -> str:
        return (config or {}).get("redirect_uri") or os.environ.get("SHOPIFY_REDIRECT_URI", "")

    def _api_url(self, shop: str, path: str) -> str:
        return f"https://{shop}.myshopify.com/admin/api/{self.SHOPIFY_API_VERSION}{path}"

    def _auth_headers(self, token: dict) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": token["access_token"],
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # OAuth flow
    # ------------------------------------------------------------------

    def get_auth_url(self, tenant_id: str, redirect_uri: str) -> str:
        shop = self._get_shop()
        if not shop:
            raise ValueError("SHOPIFY_SHOP not configured")
        api_key = self._get_api_key()
        if not api_key:
            raise ValueError("SHOPIFY_API_KEY not configured")

        scopes = "read_orders,write_orders,read_products,write_products,read_customers,read_inventory"
        params = {
            "client_id": api_key,
            "scope": scopes,
            "redirect_uri": redirect_uri,
            "state": tenant_id,
        }
        return f"https://{shop}.myshopify.com/admin/oauth/authorize?{urlencode(params)}"

    def exchange_code(self, tenant_id: str, code: str) -> dict[str, Any]:
        shop = self._get_shop()
        import httpx
        response = httpx.post(
            f"https://{shop}.myshopify.com/admin/oauth/access_token",
            json={
                "client_id": self._get_api_key(),
                "client_secret": self._get_api_secret(),
                "code": code,
            },
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------

    def fetch_data(self, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Fetch recent orders from Shopify."""
        token = self.get_stored_token(tenant_id)
        if not token:
            self._log("WARN", "No OAuth token for Shopify", tenant_id)
            return []

        shop = self._get_shop()
        limit = kwargs.get("limit", 50)
        status = kwargs.get("status", "any")

        try:
            import httpx
            response = httpx.get(
                self._api_url(shop, "/orders.json"),
                headers=self._auth_headers(token),
                params={"limit": limit, "status": status},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json().get("orders", [])
        except Exception as exc:
            self._log("ERROR", f"Shopify orders fetch failed: {exc}", tenant_id)
            return []

    def sync(self, tenant_id: str) -> ConnectorSyncResult:
        """Sync orders and products, publish events."""
        import asyncio, time
        start = time.monotonic()
        result = ConnectorSyncResult(success=False)

        token = self.get_stored_token(tenant_id)
        if not token:
            result.add_error("No OAuth token available")
            result.duration_ms = (time.monotonic() - start) * 1000
            return result

        shop = self._get_shop()
        records = 0

        try:
            import httpx
            from ...shared.event_bus import get_event_bus

            bus = get_event_bus()
            loop = asyncio.new_event_loop()

            # Sync orders
            orders_resp = httpx.get(
                self._api_url(shop, "/orders.json"),
                headers=self._auth_headers(token),
                params={"limit": 50, "status": "any"},
                timeout=30.0,
            )
            orders_resp.raise_for_status()
            for order in orders_resp.json().get("orders", []):
                loop.run_until_complete(
                    bus.publish("order.created", self.plugin_id, tenant_id, order)
                )
                records += 1

            # Sync products
            products_resp = httpx.get(
                self._api_url(shop, "/products.json"),
                headers=self._auth_headers(token),
                params={"limit": 50},
                timeout=30.0,
            )
            products_resp.raise_for_status()
            for product in products_resp.json().get("products", []):
                loop.run_until_complete(
                    bus.publish("product.updated", self.plugin_id, tenant_id, product)
                )
                records += 1

            loop.close()
            result.records_processed = records
            result.success = True
        except Exception as exc:
            result.add_error(str(exc))

        result.duration_ms = (time.monotonic() - start) * 1000
        return result

    # ------------------------------------------------------------------
    # Webhook handling
    # ------------------------------------------------------------------

    def handle_webhook(
        self,
        payload: dict[str, Any],
        headers: dict[str, str],
        tenant_id: str,
    ) -> dict[str, Any]:
        """Process an inbound Shopify webhook payload."""
        topic = headers.get("X-Shopify-Topic") or headers.get("x-shopify-topic", "unknown")

        # Map Shopify topics to MailPilot event types
        topic_map = {
            "orders/create": "order.created",
            "orders/updated": "order.updated",
            "orders/fulfilled": "order.fulfilled",
            "orders/cancelled": "order.cancelled",
            "orders/refunded": "order.refunded",
            "products/create": "product.created",
            "products/update": "product.updated",
            "products/delete": "product.deleted",
        }

        event_type = topic_map.get(topic, "webhook.received")

        try:
            import asyncio
            from ...shared.event_bus import get_event_bus
            bus = get_event_bus()
            loop = asyncio.new_event_loop()
            loop.run_until_complete(bus.publish(event_type, self.plugin_id, tenant_id, payload))
            loop.close()
        except Exception as exc:
            return {"processed": False, "error": str(exc)}

        return {"processed": True, "event_type": event_type, "topic": topic}

    def validate_signature(self, payload: bytes, headers: dict[str, str]) -> bool:
        """Verify Shopify HMAC-SHA256 webhook signature."""
        secret = self._get_api_secret()
        if not secret:
            return True

        signature_b64 = (
            headers.get("X-Shopify-Hmac-Sha256")
            or headers.get("x-shopify-hmac-sha256")
            or ""
        )
        if not signature_b64:
            return False

        import base64
        expected = base64.b64encode(
            hmac.new(secret.encode(), payload, hashlib.sha256).digest()
        ).decode()
        return hmac.compare_digest(expected, signature_b64)

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    def test_connection(self, tenant_id: str, config: dict[str, Any]) -> bool:
        token = self.get_stored_token(tenant_id)
        if not token:
            return False
        shop = self._get_shop(config)
        if not shop:
            return False
        try:
            import httpx
            response = httpx.get(
                self._api_url(shop, "/shop.json"),
                headers=self._auth_headers(token),
                timeout=10.0,
            )
            return response.is_success
        except Exception:
            return False

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        if not self._get_api_key():
            return {"status": "error", "message": "SHOPIFY_API_KEY not configured"}
        token = self.get_stored_token(tenant_id)
        if not token:
            return {"status": "degraded", "message": "No OAuth token — authorization required"}
        ok = self.test_connection(tenant_id, {})
        return {
            "status": "ok" if ok else "error",
            "message": "Shopify API reachable" if ok else "Shopify API unreachable",
        }

    def get_config_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["shop", "api_key", "api_secret", "redirect_uri"],
            "properties": {
                "shop": {"type": "string", "description": "Shopify store handle"},
                "api_key": {"type": "string", "description": "Shopify API Key"},
                "api_secret": {"type": "string", "format": "secret", "description": "Shopify API Secret"},
                "redirect_uri": {"type": "string", "description": "OAuth redirect URI"},
            },
        }

    def get_permissions(self) -> list[str]:
        return ["orders.read", "orders.write", "products.read", "customers.read"]

    def get_events(self) -> list[str]:
        return ["order.created", "order.updated", "order.fulfilled", "order.cancelled", "product.created", "product.updated"]
