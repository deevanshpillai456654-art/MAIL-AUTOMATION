"""Odoo Connector — JSON-RPC API for products, orders, inventory, CRM, accounting."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..sdk.base import ConnectorBase
from ..sdk.manifest import ConnectorManifest, SyncConfig, Permission

MANIFEST = ConnectorManifest(
    id="odoo",
    name="Odoo ERP",
    category="erp",
    description="Sync products, orders, inventory, customers, and invoices via Odoo JSON-RPC.",
    version="1.0.0",
    icon="🟣",
    supports_api_key=True,
    sync=SyncConfig(
        entities=["products", "sales_orders", "purchase_orders", "invoices",
                  "customers", "inventory"],
        default_interval_seconds=3600,
    ),
    config_schema={
        "url": {"type": "string", "required": True, "description": "https://yourcompany.odoo.com"},
        "database": {"type": "string", "required": True},
        "username": {"type": "string", "required": True},
        "api_key": {"type": "string", "required": True, "secret": True,
                    "description": "User API Key (Settings > Technical > API Keys)"},
    },
    emits_events=["order.created", "order.updated", "invoice.created",
                  "erp.sync.completed", "erp.record.created"],
)


class OdooConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 4.0
    RATE_BURST = 10.0

    def _url(self) -> str:
        return self.config.get("url", "").rstrip("/")

    async def _call(self, service: str, method: str, args: List,
                    kwargs: Optional[Dict] = None) -> Any:
        """Execute an Odoo JSON-RPC call."""
        client = self._get_http()
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "id": 1,
            "params": {
                "service": service,
                "method": method,
                "args": args,
            },
        }
        if kwargs:
            payload["params"]["kwargs"] = kwargs
        resp = await client.post(
            f"{self._url()}/jsonrpc",
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        result = resp.json()
        if "error" in result:
            raise RuntimeError(f"Odoo error: {result['error']}")
        return result.get("result")

    async def _execute(self, model: str, method: str, args: List,
                       kwargs: Optional[Dict] = None) -> Any:
        db = self.config.get("database", "")
        uid_resp = await self._call(
            "common", "authenticate",
            [db, self.config.get("username", ""), self.config.get("api_key", ""), {}],
        )
        uid = uid_resp if isinstance(uid_resp, int) else 1
        return await self._call(
            "object", "execute_kw",
            [db, uid, self.config.get("api_key", ""), model, method, args],
            kwargs or {},
        )

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        domain: List = []
        if since:
            since_str = since.strftime("%Y-%m-%d %H:%M:%S")
            domain = [["write_date", ">=", since_str]]

        if entity == "products":
            records = await self._execute(
                "product.template", "search_read",
                [domain],
                {"fields": ["name", "default_code", "list_price", "qty_available",
                             "type", "categ_id"], "limit": 500},
            )
            for r in records:
                self._upsert_product(r)
            return {"synced": len(records or []), "entity": "products"}

        elif entity == "sales_orders":
            records = await self._execute(
                "sale.order", "search_read",
                [domain],
                {"fields": ["name", "partner_id", "amount_total", "state",
                             "date_order", "currency_id"], "limit": 500},
            )
            for r in (records or []):
                self._publish_event("order.created" if r.get("state") == "draft"
                                    else "order.updated",
                                    {"source": "odoo", "order": r.get("name"),
                                     "amount": r.get("amount_total")})
            return {"synced": len(records or []), "entity": "sales_orders"}

        elif entity == "purchase_orders":
            records = await self._execute(
                "purchase.order", "search_read",
                [domain],
                {"fields": ["name", "partner_id", "amount_total", "state",
                             "date_order", "currency_id"], "limit": 500},
            )
            for r in (records or []):
                self._upsert_po(r)
            return {"synced": len(records or []), "entity": "purchase_orders"}

        elif entity == "invoices":
            records = await self._execute(
                "account.move", "search_read",
                [[*domain, ["move_type", "in", ["in_invoice", "out_invoice"]]]],
                {"fields": ["name", "partner_id", "amount_total", "state",
                             "invoice_date_due", "currency_id"], "limit": 500},
            )
            for r in (records or []):
                self._upsert_invoice(r)
            return {"synced": len(records or []), "entity": "invoices"}

        elif entity == "customers":
            records = await self._execute(
                "res.partner", "search_read",
                [[*domain, ["customer_rank", ">", 0]]],
                {"fields": ["name", "email", "phone", "street", "city",
                             "country_id", "vat"], "limit": 500},
            )
            for r in (records or []):
                self._upsert_contact(r)
            return {"synced": len(records or []), "entity": "customers"}

        elif entity == "inventory":
            records = await self._execute(
                "stock.quant", "search_read",
                [[["location_id.usage", "=", "internal"]]],
                {"fields": ["product_id", "location_id", "quantity",
                             "reserved_quantity"], "limit": 1000},
            )
            for r in (records or []):
                self._upsert_inventory(r)
            return {"synced": len(records or []), "entity": "inventory"}

        return {"synced": 0, "entity": entity}

    def _upsert_product(self, r: Dict) -> None:
        pass  # Odoo products → ERP inventory mapping

    def _upsert_po(self, r: Dict) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        state_map = {"draft": "draft", "sent": "pending", "purchase": "approved",
                     "done": "received", "cancel": "cancelled"}
        status = state_map.get(r.get("state", ""), "pending")
        if not self.db.fetch_one(
            "SELECT id FROM erp_purchase_orders WHERE po_number=? AND tenant_id=?",
            (r.get("name", ""), self.tenant_id),
        ):
            pid = f"po_{uuid.uuid4().hex}"
            order_date = r.get("date_order", "")
            self.db.execute(
                """INSERT INTO erp_purchase_orders
                   (id, tenant_id, po_number, status,
                    total_amount, currency, order_date, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (pid, self.tenant_id, r.get("name", ""),
                 status, r.get("amount_total", 0), "USD",
                 order_date[:10] if order_date else None,
                 now, now),
            )

    def _upsert_invoice(self, r: Dict) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        state_map = {"draft": "draft", "posted": "sent", "cancel": "cancelled",
                     "paid": "paid"}
        status = "paid" if r.get("payment_state") == "paid" else state_map.get(r.get("state", ""), "draft")
        if not self.db.fetch_one(
            "SELECT id FROM erp_invoices WHERE invoice_number=? AND tenant_id=?",
            (r.get("name", ""), self.tenant_id),
        ):
            iid = f"inv_{uuid.uuid4().hex}"
            amount = r.get("amount_total", 0)
            self.db.execute(
                """INSERT INTO erp_invoices
                   (id, tenant_id, invoice_number, status, amount, total_amount,
                    currency, invoice_date, due_date, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (iid, self.tenant_id, r.get("name", ""),
                 status, amount, amount, "USD",
                 r.get("invoice_date", now[:10]),
                 r.get("invoice_date_due"),
                 now, now),
            )
            self._publish_event("invoice.created",
                                {"source": "odoo", "number": r.get("name")})

    def _upsert_contact(self, r: Dict) -> None:
        ext_id = str(r.get("id", ""))
        now = datetime.now(tz=timezone.utc).isoformat()
        if not self.db.fetch_one(
            "SELECT id FROM crm_contacts WHERE external_id=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        ):
            cid = f"cnt_{uuid.uuid4().hex}"
            name_parts = (r.get("name") or "").split(" ", 1)
            self.db.execute(
                """INSERT INTO crm_contacts
                   (id, tenant_id, external_id, first_name, last_name, email, phone,
                    source, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,'odoo','active',?,?)""",
                (cid, self.tenant_id, ext_id,
                 name_parts[0], name_parts[1] if len(name_parts) > 1 else "",
                 r.get("email", ""), r.get("phone", ""),
                 now, now),
            )

    def _upsert_inventory(self, r: Dict) -> None:
        product = r.get("product_id", [None, ""])
        sku = str(product[0] or "")
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = self.db.fetch_one(
            "SELECT id FROM erp_inventory WHERE sku=? AND tenant_id=?",
            (sku, self.tenant_id),
        )
        if existing:
            self.db.execute(
                "UPDATE erp_inventory SET quantity=?, updated_at=? WHERE id=?",
                (r.get("quantity", 0), now, existing["id"]),
            )
        else:
            iid = f"inv_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO erp_inventory
                   (id, tenant_id, sku, name, quantity, reserved, updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (iid, self.tenant_id, sku, str(product[1] or ""),
                 r.get("quantity", 0), r.get("reserved_quantity", 0),
                 now),
            )

    async def verify_webhook_signature(self, raw_body: bytes, headers: Dict) -> bool:
        return True

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict) -> None:
        self._publish_event("erp.record.updated",
                            {"source": "odoo", "event": event_type})

    async def health_check(self) -> Dict[str, Any]:
        try:
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(f"{self._url()}/web/database/list",
                                    json={"jsonrpc": "2.0", "method": "call",
                                          "params": {}})
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code == 200
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1)}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
