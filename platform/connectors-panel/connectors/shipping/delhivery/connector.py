"""Delhivery Connector — REST API, shipment creation and tracking (India)."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...sdk.base import ConnectorBase
from ...sdk.manifest import ConnectorManifest, SyncConfig

MANIFEST = ConnectorManifest(
    id="delhivery",
    name="Delhivery",
    category="shipping",
    description="Create Delhivery shipments and track packages across India.",
    version="1.0.0",
    icon="🔵",
    supports_api_key=True,
    sync=SyncConfig(entities=["shipments"], default_interval_seconds=1800),
    config_schema={
        "api_key": {"type": "string", "required": True, "secret": True,
                     "description": "Delhivery API Token"},
        "pickup_name": {"type": "string", "required": True,
                         "description": "Registered pickup location name"},
        "sandbox": {"type": "boolean", "default": False},
    },
    emits_events=["shipment.created", "shipment.tracking_updated"],
)

DELHIVERY_PROD = "https://track.delhivery.com"
DELHIVERY_SANDBOX = "https://staging-express.delhivery.com"


class DelhiveryConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 5.0
    RATE_BURST = 15.0

    def _base(self) -> str:
        return DELHIVERY_SANDBOX if self.config.get("sandbox") else DELHIVERY_PROD

    def _headers(self) -> Dict:
        return {
            "Authorization": f"Token {self.config['api_key']}",
            "Content-Type": "application/json",
        }

    async def check_serviceability(self, origin_pin: str,
                                    destination_pin: str,
                                    cod: bool = False,
                                    weight: float = 0.5) -> Dict:
        client = self._get_http()
        resp = await client.get(
            f"{self._base()}/c/api/delhivery-serviceability/",
            headers=self._headers(),
            params={
                "md": "S",
                "ss": "Delivered",
                "d_pin": destination_pin,
                "o_pin": origin_pin,
                "cgm": weight * 1000,
                "pt": "Pre-paid" if not cod else "COD",
                "code": destination_pin,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def create_shipment(self, order_id: str, name: str, phone: str,
                               address: str, city: str, state: str,
                               pincode: str, products: List[Dict],
                               payment_mode: str = "Prepaid",
                               cod_amount: float = 0) -> Dict:
        client = self._get_http()
        shipment_data = {
            "shipments": [
                {
                    "name": name,
                    "add": address,
                    "city": city,
                    "state": state,
                    "country": "India",
                    "phone": phone,
                    "pin": pincode,
                    "payment_mode": payment_mode,
                    "order": order_id,
                    "total_amount": cod_amount,
                    "cod_amount": cod_amount if payment_mode == "COD" else 0,
                    "products_desc": ", ".join(p.get("name", "") for p in products),
                    "hsn_code": "",
                    "seller_inv": order_id,
                    "quantity": sum(p.get("qty", 1) for p in products),
                    "waybill": "",
                    "shipment_width": 10,
                    "shipment_height": 10,
                    "weight": sum(p.get("weight", 0.5) for p in products),
                    "seller_name": self.config.get("pickup_name", ""),
                    "seller_add": self.config.get("pickup_address", ""),
                    "seller_city": self.config.get("pickup_city", ""),
                    "seller_state": self.config.get("pickup_state", ""),
                    "seller_pin": self.config.get("pickup_pincode", ""),
                    "seller_cst_no": "",
                    "seller_gst_tin": "",
                    "shipping_mode": "Surface",
                    "pickup_location": self.config.get("pickup_name", ""),
                }
            ]
        }
        form_data = {"format": "json", "data": json.dumps(shipment_data)}
        resp = await client.post(
            f"{self._base()}/api/cmu/create.json",
            headers={"Authorization": f"Token {self.config['api_key']}"},
            data=form_data,
        )
        resp.raise_for_status()
        data = resp.json()
        packages = data.get("packages", [{}])
        waybill = packages[0].get("waybill", "") if packages else ""
        status = packages[0].get("status", "") if packages else ""

        shipment_id = f"shp_{uuid.uuid4().hex}"
        now = datetime.now(tz=timezone.utc).isoformat()
        self.db.execute(
            """INSERT INTO shipments
               (id, tenant_id, carrier, tracking_number, status,
                consignee_name, destination_location, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (shipment_id, self.tenant_id, "delhivery", waybill,
             "created" if status == "Success" else "error",
             name, f"{address}, {city}, {state} - {pincode}", now, now),
        )
        if waybill:
            self._publish_event("shipment.created",
                                {"carrier": "delhivery", "waybill": waybill,
                                 "order_id": order_id})
        return {"shipment_id": shipment_id, "waybill": waybill, "data": data}

    async def track_shipment(self, waybill: str) -> Dict:
        client = self._get_http()
        resp = await client.get(
            f"{self._base()}/api/v1/packages/json/",
            headers=self._headers(),
            params={"waybill": waybill},
        )
        resp.raise_for_status()
        data = resp.json()
        packages = data.get("ShipmentData", [])
        if not packages:
            return {"waybill": waybill, "status": "unknown"}

        shipment = packages[0].get("Shipment", {})
        status = shipment.get("Status", {}).get("Status", "")
        scans = shipment.get("Scans", [])

        status_map = {
            "Delivered": "delivered", "In Transit": "in_transit",
            "Out For Delivery": "out_for_delivery", "Picked Up": "picked_up",
            "RTO": "returned", "DLC": "delivered", "Booked": "created",
        }
        mapped = status_map.get(status, "in_transit")
        now = datetime.now(tz=timezone.utc).isoformat()
        row = self.db.fetch_one(
            "SELECT id FROM shipments WHERE tracking_number=? AND tenant_id=?",
            (waybill, self.tenant_id),
        )
        if row:
            self.db.execute(
                "UPDATE shipments SET status=?, updated_at=? WHERE id=?",
                (mapped, now, row["id"]),
            )
            self._publish_event("shipment.tracking_updated",
                                {"carrier": "delhivery", "waybill": waybill,
                                 "status": mapped})
        return {"waybill": waybill, "status": mapped, "raw_status": status,
                "scans": scans}

    async def cancel_shipment(self, waybill: str) -> Dict:
        client = self._get_http()
        resp = await client.post(
            f"{self._base()}/api/p/edit",
            headers=self._headers(),
            json={"waybill": waybill, "cancellation": True},
        )
        resp.raise_for_status()
        return resp.json()

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "shipments":
            rows = self.db.fetch_all(
                "SELECT tracking_number FROM shipments "
                "WHERE carrier='delhivery' AND tenant_id=? "
                "AND status NOT IN ('delivered','returned','cancelled')",
                (self.tenant_id,),
            )
            updated = 0
            for row in rows or []:
                try:
                    await self.track_shipment(row["tracking_number"])
                    updated += 1
                except Exception:
                    pass
            return {"synced": updated, "entity": "shipments"}
        return {"synced": 0, "entity": entity}

    async def verify_webhook_signature(self, raw_body: bytes,
                                        headers: Dict) -> bool:
        return True

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                              raw_body: bytes, headers: Dict) -> None:
        waybill = payload.get("waybill", "")
        status = payload.get("status", "")
        if waybill and status:
            now = datetime.now(tz=timezone.utc).isoformat()
            row = self.db.fetch_one(
                "SELECT id FROM shipments WHERE tracking_number=? AND tenant_id=?",
                (waybill, self.tenant_id),
            )
            if row:
                self.db.execute(
                    "UPDATE shipments SET status=?, updated_at=? WHERE id=?",
                    (status.lower().replace(" ", "_"), now, row["id"]),
                )
                self._publish_event("shipment.tracking_updated",
                                    {"carrier": "delhivery", "waybill": waybill,
                                     "status": status})

    async def health_check(self) -> Dict[str, Any]:
        try:
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(
                f"{self._base()}/c/api/delhivery-serviceability/",
                headers=self._headers(),
                params={"md": "S", "ss": "Delivered", "d_pin": "110001",
                         "o_pin": "110001", "cgm": 500, "pt": "Pre-paid",
                         "code": "110001"},
            )
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code < 400
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1)}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
