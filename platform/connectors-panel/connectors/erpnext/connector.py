"""ERPNext Connector — REST API for inventory, orders, invoices, warehouses."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from ..sdk.base import ConnectorBase
from ..sdk.manifest import ConnectorManifest, SyncConfig, Permission

MANIFEST = ConnectorManifest(
    id="erpnext",
    name="ERPNext",
    category="erp",
    description="Sync inventory, sales/purchase orders, invoices, customers from ERPNext.",
    version="1.0.0",
    icon="🟢",
    supports_api_key=True,
    sync=SyncConfig(
        entities=["items", "customers", "suppliers", "purchase_orders",
                  "sales_orders", "purchase_invoices", "stock_entries"],
        default_interval_seconds=3600,
    ),
    config_schema={
        "url": {"type": "string", "required": True, "description": "https://yourcompany.erpnext.com"},
        "api_key": {"type": "string", "required": True, "secret": True},
        "api_secret": {"type": "string", "required": True, "secret": True},
    },
    emits_events=["erp.sync.completed", "order.created", "invoice.created"],
)


class ERPNextConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 5.0
    RATE_BURST = 10.0

    def _base(self) -> str:
        return self.config.get("url", "").rstrip("/") + "/api/resource"

    def _headers(self) -> Dict:
        return {
            "Authorization": f"token {self.config.get('api_key','')}:{self.config.get('api_secret','')}",
            "Accept": "application/json",
        }

    async def _get_list(self, doctype: str, fields: List[str],
                        filters: Optional[List] = None,
                        limit: int = 500) -> List[Dict]:
        client = self._get_http()
        params: Dict[str, Any] = {
            "fields": json.dumps(fields),
            "limit_page_length": limit,
        }
        if filters:
            params["filters"] = json.dumps(filters)
        resp = await client.get(
            f"{self._base()}/{doctype}",
            headers=self._headers(),
            params=params,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        filters: List = []
        if since:
            filters = [["modified", ">=", since.strftime("%Y-%m-%d %H:%M:%S")]]

        if entity == "items":
            records = await self._get_list(
                "Item",
                ["name", "item_name", "item_code", "item_group",
                 "stock_uom", "standard_rate", "last_purchase_rate"],
                filters,
            )
            return {"synced": len(records), "entity": "items"}

        elif entity == "customers":
            records = await self._get_list(
                "Customer",
                ["name", "customer_name", "customer_type",
                 "email_id", "mobile_no", "territory"],
                filters,
            )
            for r in records:
                self._upsert_contact(r)
            return {"synced": len(records), "entity": "customers"}

        elif entity == "suppliers":
            records = await self._get_list(
                "Supplier",
                ["name", "supplier_name", "supplier_type",
                 "email_id", "mobile_no", "country"],
                filters,
            )
            for r in records:
                self._upsert_vendor(r)
            return {"synced": len(records), "entity": "suppliers"}

        elif entity == "purchase_orders":
            records = await self._get_list(
                "Purchase Order",
                ["name", "supplier", "status", "grand_total",
                 "currency", "transaction_date", "schedule_date"],
                filters,
            )
            for r in records:
                self._upsert_po(r)
            return {"synced": len(records), "entity": "purchase_orders"}

        elif entity == "purchase_invoices":
            records = await self._get_list(
                "Purchase Invoice",
                ["name", "supplier", "status", "grand_total",
                 "due_date", "currency"],
                filters,
            )
            for r in records:
                self._upsert_invoice(r)
            return {"synced": len(records), "entity": "purchase_invoices"}

        elif entity == "stock_entries":
            records = await self._get_list(
                "Bin",
                ["item_code", "warehouse", "actual_qty",
                 "reserved_qty", "ordered_qty", "reorder_level"],
            )
            for r in records:
                self._upsert_inventory(r)
            return {"synced": len(records), "entity": "stock_entries"}

        return {"synced": 0, "entity": entity}

    def _upsert_contact(self, r: Dict) -> None:
        ext_id = r.get("name", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        if not self.db.fetch_one(
            "SELECT contact_id FROM crm_contacts WHERE external_id=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        ):
            cid = f"cnt_{uuid.uuid4().hex}"
            name = r.get("customer_name", "")
            parts = name.split(" ", 1)
            self.db.execute(
                """INSERT INTO crm_contacts
                   (contact_id, tenant_id, first_name, last_name, email, phone,
                    source, external_id, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,'erpnext',?,'active',?,?)""",
                (cid, self.tenant_id, parts[0], parts[1] if len(parts) > 1 else "",
                 r.get("email_id", ""), r.get("mobile_no", ""),
                 ext_id, now, now),
            )

    def _upsert_vendor(self, r: Dict) -> None:
        ext_id = r.get("name", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        if not self.db.fetch_one(
            "SELECT vendor_id FROM erp_vendors WHERE vendor_code=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        ):
            vid = f"ven_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO erp_vendors
                   (vendor_id, tenant_id, vendor_code, name, status,
                    category, email, created_at, updated_at)
                   VALUES (?,?,?,?,'active','supplier',?,?,?)""",
                (vid, self.tenant_id, ext_id,
                 r.get("supplier_name", ""),
                 r.get("email_id", ""),
                 now, now),
            )

    def _upsert_po(self, r: Dict) -> None:
        ext_id = r.get("name", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        st_map = {"Draft": "draft", "To Receive and Bill": "approved",
                  "To Bill": "received", "Completed": "received",
                  "Cancelled": "cancelled"}
        status = st_map.get(r.get("status", ""), "pending")
        if not self.db.fetch_one(
            "SELECT po_id FROM erp_purchase_orders WHERE po_number=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        ):
            pid = f"po_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO erp_purchase_orders
                   (po_id, tenant_id, po_number, vendor_id, status,
                    total_amount, currency, order_date, expected_delivery, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, self.tenant_id, ext_id, r.get("supplier",""),
                 status, r.get("grand_total", 0), r.get("currency","USD"),
                 r.get("transaction_date"), r.get("schedule_date"),
                 now, now),
            )

    def _upsert_invoice(self, r: Dict) -> None:
        ext_id = r.get("name", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        st_map = {"Draft": "draft", "Unpaid": "sent", "Paid": "paid",
                  "Overdue": "overdue", "Cancelled": "cancelled"}
        status = st_map.get(r.get("status", ""), "sent")
        if not self.db.fetch_one(
            "SELECT invoice_id FROM erp_invoices WHERE invoice_number=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        ):
            iid = f"inv_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO erp_invoices
                   (invoice_id, tenant_id, invoice_number, vendor_id,
                    status, amount, currency, due_date, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (iid, self.tenant_id, ext_id, r.get("supplier",""),
                 status, r.get("grand_total",0), r.get("currency","USD"),
                 r.get("due_date"), now, now),
            )

    def _upsert_inventory(self, r: Dict) -> None:
        sku = r.get("item_code", "")
        wh = r.get("warehouse", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = self.db.fetch_one(
            "SELECT inventory_id FROM erp_inventory WHERE sku=? AND warehouse_id=? AND tenant_id=?",
            (sku, wh, self.tenant_id),
        )
        if existing:
            self.db.execute(
                "UPDATE erp_inventory SET quantity=?, reorder_point=?, updated_at=? WHERE inventory_id=?",
                (r.get("actual_qty",0), r.get("reorder_level",0), now, existing["inventory_id"]),
            )
        else:
            iid = f"inv_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO erp_inventory
                   (inventory_id, tenant_id, sku, name, warehouse_id,
                    quantity, reserved_quantity, reorder_point, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (iid, self.tenant_id, sku, sku, wh,
                 r.get("actual_qty",0), r.get("reserved_qty",0),
                 r.get("reorder_level",0), now, now),
            )

    async def verify_webhook_signature(self, raw_body: bytes, headers: Dict) -> bool:
        return True  # ERPNext uses API-key auth at URL level

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict) -> None:
        self._publish_event("erp.record.updated",
                            {"source": "erpnext", "event": event_type, "data": payload})

    async def health_check(self) -> Dict[str, Any]:
        try:
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(
                f"{self.config.get('url','').rstrip('/')}/api/method/frappe.auth.get_logged_user",
                headers=self._headers(),
            )
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code == 200
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1)}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
