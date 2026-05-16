"""Shopify Admin REST API 2024-01 service layer."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlencode


class ShopifyAPI:
    API_VERSION = "2024-01"

    @staticmethod
    def shop_url(shop: str) -> str:
        s = shop.rstrip("/")
        if not s.endswith(".myshopify.com"):
            s = f"{s}.myshopify.com"
        return f"https://{s}"

    @staticmethod
    def api_url(shop: str) -> str:
        return f"{ShopifyAPI.shop_url(shop)}/admin/api/{ShopifyAPI.API_VERSION}"

    @staticmethod
    def get_auth_url(api_key: str, shop: str, redirect_uri: str,
                     state: str) -> str:
        params = urlencode({
            "client_id": api_key,
            "scope": "read_orders,write_orders,read_products,write_products,"
                     "read_customers,write_customers,read_inventory,write_inventory,"
                     "read_fulfillments,write_fulfillments",
            "redirect_uri": redirect_uri,
            "state": state,
        })
        return f"{ShopifyAPI.shop_url(shop)}/admin/oauth/authorize?{params}"

    @staticmethod
    async def exchange_code(client, api_key: str, api_secret: str,
                            shop: str, code: str) -> Dict[str, Any]:
        resp = await client.post(
            f"{ShopifyAPI.shop_url(shop)}/admin/oauth/access_token",
            json={"client_id": api_key, "client_secret": api_secret, "code": code},
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _h(token: str) -> Dict:
        return {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    @staticmethod
    async def get_orders(client, shop: str, token: str,
                         since_id: Optional[int] = None,
                         status: str = "any") -> List[Dict]:
        params = {"limit": 250, "status": status}
        if since_id:
            params["since_id"] = since_id
        resp = await client.get(f"{ShopifyAPI.api_url(shop)}/orders.json",
                                headers=ShopifyAPI._h(token), params=params)
        resp.raise_for_status()
        return resp.json().get("orders", [])

    @staticmethod
    async def get_customers(client, shop: str, token: str,
                            since_id: Optional[int] = None) -> List[Dict]:
        params = {"limit": 250}
        if since_id:
            params["since_id"] = since_id
        resp = await client.get(f"{ShopifyAPI.api_url(shop)}/customers.json",
                                headers=ShopifyAPI._h(token), params=params)
        resp.raise_for_status()
        return resp.json().get("customers", [])

    @staticmethod
    async def get_products(client, shop: str, token: str,
                           since_id: Optional[int] = None) -> List[Dict]:
        params = {"limit": 250}
        if since_id:
            params["since_id"] = since_id
        resp = await client.get(f"{ShopifyAPI.api_url(shop)}/products.json",
                                headers=ShopifyAPI._h(token), params=params)
        resp.raise_for_status()
        return resp.json().get("products", [])

    @staticmethod
    async def get_inventory_levels(client, shop: str, token: str,
                                   location_id: str) -> List[Dict]:
        resp = await client.get(
            f"{ShopifyAPI.api_url(shop)}/inventory_levels.json",
            headers=ShopifyAPI._h(token),
            params={"limit": 250, "location_ids": location_id},
        )
        resp.raise_for_status()
        return resp.json().get("inventory_levels", [])

    @staticmethod
    async def register_webhook(client, shop: str, token: str,
                               topic: str, address: str) -> Dict:
        resp = await client.post(
            f"{ShopifyAPI.api_url(shop)}/webhooks.json",
            headers=ShopifyAPI._h(token),
            json={"webhook": {"topic": topic, "address": address, "format": "json"}},
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def list_webhooks(client, shop: str, token: str) -> List[Dict]:
        resp = await client.get(f"{ShopifyAPI.api_url(shop)}/webhooks.json",
                                headers=ShopifyAPI._h(token))
        resp.raise_for_status()
        return resp.json().get("webhooks", [])

    @staticmethod
    def verify_webhook(secret: str, raw_body: bytes, hmac_header: str) -> bool:
        import base64, hashlib, hmac as _hmac
        digest = _hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode()
        return _hmac.compare_digest(expected, hmac_header)

    @staticmethod
    async def ping(client, shop: str, token: str) -> bool:
        try:
            resp = await client.get(f"{ShopifyAPI.api_url(shop)}/shop.json",
                                    headers=ShopifyAPI._h(token))
            return resp.status_code == 200
        except Exception:
            return False
