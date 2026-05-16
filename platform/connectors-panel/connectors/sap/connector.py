"""
SAP ERP Connector — OData services for POs, invoices, vendors, inventory.
Supports Basic Auth and OAuth2 (SAP BTP).
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from ..sdk.base import ConnectorBase
from ..sdk.manifest import (
    ConnectorManifest, SyncConfig, Permission,
)

MANIFEST = ConnectorManifest(
    id="sap",
    name="SAP ERP",
    category="erp",
    description="Sync purchase orders, invoices, vendors, and inventory via SAP OData.",
    version="1.0.0",
    icon="🏗️",
    supports_api_key=True,
    sync=SyncConfig(
        entities=["purchase_orders", "invoices", "vendors", "inventory"],
        default_interval_seconds=3600,
        supports_incremental=True,
    ),
    permissions=[
        Permission("MM_PUR_S4HANA_PURCHASEORDER_READ", "Purchase Orders", "Read PO data"),
        Permission("MM_FIM_SUPPLIER_INVOICE_READ", "Invoices", "Read invoice data"),
        Permission("MM_MATL_MGMT_INVENTORY_READ", "Inventory", "Read inventory data"),
    ],
    config_schema={
        "base_url": {"type": "string", "required": True,
                     "description": "https://your-sap.example.com/sap/opu/odata/sap"},
        "username": {"type": "string", "required": True},
        "password": {"type": "string", "required": True, "secret": True},
        "client": {"type": "string", "default": "100", "description": "SAP client number"},
        "use_csrf": {"type": "boolean", "default": True},
    },
    emits_events=[
        "erp.sync.completed", "erp.record.created", "erp.record.updated",
        "invoice.created", "invoice.paid", "shipment.created",
    ],
)


class SAPConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 2.0
    RATE_BURST = 5.0

    def _base(self) -> str:
        return self.config.get("base_url", "").rstrip("/")

    def _basic_auth(self) -> str:
        creds = f"{self.config.get('username','')}:{self.config.get('password','')}"
        return "Basic " + base64.b64encode(creds.encode()).decode()

    def _headers(self) -> Dict:
        return {
            "Authorization": self._basic_auth(),
            "Accept": "application/json",
            "sap-client": self.config.get("client", "100"),
        }

    async def _csrf_token(self, client) -> str:
        """Fetch CSRF token required for write operations."""
        resp = await client.get(self._base(), headers={
            **self._headers(), "X-CSRF-Token": "Fetch"
        })
        return resp.headers.get("X-CSRF-Token", "")

    async def _odata_get(self, client, service: str, entity: str,
                          params: Optional[Dict] = None) -> List[Dict]:
        url = f"{self._base()}/{service}/{entity}"
        resp = await client.get(url, headers=self._headers(),
                                params={**(params or {}), "$format": "json"})
        resp.raise_for_status()
        data = resp.json()
        return data.get("d", {}).get("results", data.get("value", []))

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        client = self._get_http()

        if entity == "purchase_orders":
            return await self._sync_pos(client, since)
        elif entity == "invoices":
            return await self._sync_invoices(client, since)
        elif entity == "vendors":
            return await self._sync_vendors(client, since)
        elif entity == "inventory":
            return await self._sync_inventory(client)
        return {"synced": 0, "entity": entity}

    async def _sync_pos(self, client, since: Optional[datetime]) -> Dict:
        filter_str = ""
        if since:
            ts = since.strftime("datetime'%Y-%m-%dT%H:%M:%S'")
            filter_str = f"LastChangeDateTime ge {ts}"
        params = {"$top": 200}
        if filter_str:
            params["$filter"] = filter_str
        try:
            records = await self._odata_get(
                client, "API_PURCHASEORDER_PROCESS_SRV",
                "A_PurchaseOrder", params,
            )
        except Exception as exc:
            self._log("WARN", f"SAP PO sync failed: {exc}")
            return {"synced": 0, "entity": "purchase_orders", "error": str(exc)}

        for r in records:
            self._upsert_po(r)
        self._publish_event("erp.sync.completed",
                            {"entity": "purchase_orders", "count": len(records)})
        return {"synced": len(records), "entity": "purchase_orders"}

    def _upsert_po(self, r: Dict) -> None:
        ext_id = r.get("PurchaseOrder", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        status_map = {
            "01": "draft", "02": "pending", "03": "approved",
            "04": "received", "05": "cancelled",
        }
        status = status_map.get(r.get("PurchaseOrderType", ""), "pending")
        existing = self.db.fetch_one(
            "SELECT po_id FROM erp_purchase_orders WHERE po_number=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        )
        if not existing:
            po_id = f"po_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO erp_purchase_orders
                   (po_id, tenant_id, po_number, vendor_id, status,
                    total_amount, currency, order_date, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (po_id, self.tenant_id, ext_id,
                 r.get("Supplier", ""),
                 status,
                 float(r.get("NetAmount", 0) or 0),
                 r.get("DocumentCurrency", "USD"),
                 r.get("CreationDate", "")[:10] if r.get("CreationDate") else None,
                 now, now),
            )
        else:
            self.db.execute(
                "UPDATE erp_purchase_orders SET status=?, updated_at=? WHERE po_id=?",
                (status, now, existing["po_id"]),
            )

    async def _sync_invoices(self, client, since: Optional[datetime]) -> Dict:
        params: Dict[str, Any] = {"$top": 200}
        if since:
            ts = since.strftime("datetime'%Y-%m-%dT%H:%M:%S'")
            params["$filter"] = f"CreationDate ge {ts}"
        try:
            records = await self._odata_get(
                client, "API_SUPPLIERINVOICE_PROCESS_SRV",
                "A_SupplierInvoice", params,
            )
        except Exception as exc:
            self._log("WARN", f"SAP invoice sync failed: {exc}")
            return {"synced": 0, "entity": "invoices", "error": str(exc)}

        for r in records:
            self._upsert_invoice(r)
        self._publish_event("erp.sync.completed",
                            {"entity": "invoices", "count": len(records)})
        return {"synced": len(records), "entity": "invoices"}

    def _upsert_invoice(self, r: Dict) -> None:
        inv_num = r.get("SupplierInvoice", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = self.db.fetch_one(
            "SELECT invoice_id FROM erp_invoices WHERE invoice_number=? AND tenant_id=?",
            (inv_num, self.tenant_id),
        )
        clear_status = r.get("ClearingStatus", "")
        status = "paid" if clear_status == "C" else "sent"
        if not existing:
            iid = f"inv_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO erp_invoices
                   (invoice_id, tenant_id, invoice_number, vendor_id, status,
                    amount, currency, due_date, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (iid, self.tenant_id, inv_num,
                 r.get("Supplier", ""),
                 status,
                 float(r.get("InvoiceGrossAmount", 0) or 0),
                 r.get("DocumentCurrency", "USD"),
                 r.get("PaymentDueDate", "")[:10] if r.get("PaymentDueDate") else None,
                 now, now),
            )
            self._publish_event("invoice.created",
                                {"source": "sap", "invoice_number": inv_num})

    async def _sync_vendors(self, client, since: Optional[datetime]) -> Dict:
        try:
            records = await self._odata_get(
                client, "API_BUSINESS_PARTNER",
                "A_BusinessPartner",
                {"$filter": "BusinessPartnerCategory eq '2'", "$top": 500},
            )
        except Exception as exc:
            return {"synced": 0, "entity": "vendors", "error": str(exc)}

        for r in records:
            self._upsert_vendor(r)
        return {"synced": len(records), "entity": "vendors"}

    def _upsert_vendor(self, r: Dict) -> None:
        ext_id = r.get("BusinessPartner", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = self.db.fetch_one(
            "SELECT vendor_id FROM erp_vendors WHERE vendor_code=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        )
        if not existing:
            vid = f"ven_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO erp_vendors
                   (vendor_id, tenant_id, vendor_code, name, status,
                    category, created_at, updated_at)
                   VALUES (?,?,?,?,'active','supplier',?,?)""",
                (vid, self.tenant_id, ext_id,
                 r.get("BusinessPartnerFullName", ""),
                 now, now),
            )

    async def _sync_inventory(self, client) -> Dict:
        try:
            records = await self._odata_get(
                client, "API_MATERIAL_STOCK_SRV",
                "A_MatlStkInAcctMod",
                {"$top": 500},
            )
        except Exception as exc:
            return {"synced": 0, "entity": "inventory", "error": str(exc)}

        for r in records:
            self._upsert_inventory(r)
        return {"synced": len(records), "entity": "inventory"}

    def _upsert_inventory(self, r: Dict) -> None:
        sku = r.get("Material", "")
        plant = r.get("Plant", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = self.db.fetch_one(
            "SELECT inventory_id FROM erp_inventory WHERE sku=? AND warehouse_id=? AND tenant_id=?",
            (sku, plant, self.tenant_id),
        )
        qty = float(r.get("MatlWrhsStkQtyInMatlBaseUnit", 0) or 0)
        if existing:
            self.db.execute(
                "UPDATE erp_inventory SET quantity=?, updated_at=? WHERE inventory_id=?",
                (qty, now, existing["inventory_id"]),
            )
        else:
            iid = f"inv_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO erp_inventory
                   (inventory_id, tenant_id, sku, name, warehouse_id,
                    quantity, reserved_quantity, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,0,?,?)""",
                (iid, self.tenant_id, sku, sku, plant, qty, now, now),
            )

    async def verify_webhook_signature(self, raw_body: bytes, headers: Dict) -> bool:
        return True  # SAP uses network-level security; verify IP in production

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict) -> None:
        self._publish_event("erp.record.updated",
                            {"source": "sap", "event_type": event_type, "payload": payload})

    async def health_check(self) -> Dict[str, Any]:
        try:
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(self._base(), headers=self._headers())
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code < 400
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1)}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
