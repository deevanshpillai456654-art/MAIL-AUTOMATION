"""DHL Express Connector — REST API v2, rate quotes, shipment creation, tracking."""
from __future__ import annotations

import base64
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...sdk.base import ConnectorBase
from ...sdk.manifest import ConnectorManifest, SyncConfig

MANIFEST = ConnectorManifest(
    id="dhl",
    name="DHL Express",
    category="shipping",
    description="Create DHL shipments, get rate quotes, and track packages.",
    version="1.0.0",
    icon="🟡",
    supports_api_key=True,
    sync=SyncConfig(entities=["shipments"], default_interval_seconds=3600),
    config_schema={
        "api_key": {"type": "string", "required": True,
                     "description": "DHL Express MyDHL API key"},
        "api_secret": {"type": "string", "required": True, "secret": True,
                        "description": "DHL Express MyDHL API secret"},
        "account_number": {"type": "string", "required": True,
                            "description": "DHL account number"},
        "sandbox": {"type": "boolean", "default": False},
    },
    emits_events=["shipment.created", "shipment.tracking_updated"],
)

DHL_PROD = "https://express.api.dhl.com/mydhlapi"
DHL_SANDBOX = "https://express.api.dhl.com/mydhlapi/test"


class DHLConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 3.0
    RATE_BURST = 10.0

    def _base(self) -> str:
        return DHL_SANDBOX if self.config.get("sandbox") else DHL_PROD

    def _basic_auth(self) -> str:
        creds = f"{self.config['api_key']}:{self.config['api_secret']}"
        return "Basic " + base64.b64encode(creds.encode()).decode()

    def _headers(self) -> Dict:
        return {
            "Authorization": self._basic_auth(),
            "Content-Type": "application/json",
        }

    async def get_rates(self, shipper: Dict, recipient: Dict,
                         packages: List[Dict], planned_date: Optional[str] = None) -> List[Dict]:
        client = self._get_http()
        ship_date = planned_date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        payload = {
            "customerDetails": {
                "shipperDetails": {"postalCode": shipper.get("postal_code", ""),
                                   "cityName": shipper.get("city", ""),
                                   "countryCode": shipper.get("country_code", "US"),
                                   "addressLine1": shipper.get("address", "")},
                "receiverDetails": {"postalCode": recipient.get("postal_code", ""),
                                    "cityName": recipient.get("city", ""),
                                    "countryCode": recipient.get("country_code", "US"),
                                    "addressLine1": recipient.get("address", "")},
            },
            "accounts": [{"typeCode": "shipper", "number": self.config["account_number"]}],
            "packages": [
                {"weight": p.get("weight", 1), "dimensions": {
                    "length": p.get("length", 10),
                    "width": p.get("width", 10),
                    "height": p.get("height", 10),
                }}
                for p in packages
            ],
            "plannedShippingDateAndTime": ship_date,
            "unitOfMeasurement": "imperial",
        }
        resp = await client.post(
            f"{self._base()}/rates",
            headers=self._headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        rates = []
        for product in data.get("products", []):
            charges = product.get("totalPrice", [{}])
            price = charges[0].get("price", 0) if charges else 0
            rates.append({
                "product_code": product.get("productCode"),
                "product_name": product.get("productName"),
                "total_price": price,
                "currency": charges[0].get("priceCurrency", "USD") if charges else "USD",
                "delivery_time": product.get("deliveryCapabilities",
                                              {}).get("deliveryTypeCode"),
            })
        return rates

    async def create_shipment(self, shipper_contact: Dict, shipper_address: Dict,
                               receiver_contact: Dict, receiver_address: Dict,
                               packages: List[Dict], content: str,
                               service_code: str = "P") -> Dict:
        client = self._get_http()
        now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        payload = {
            "plannedShippingDateAndTime": now_str,
            "pickup": {"isRequested": False},
            "productCode": service_code,
            "accounts": [{"typeCode": "shipper", "number": self.config["account_number"]}],
            "customerDetails": {
                "shipperDetails": {
                    "postalAddress": shipper_address,
                    "contactInformation": shipper_contact,
                },
                "receiverDetails": {
                    "postalAddress": receiver_address,
                    "contactInformation": receiver_contact,
                },
            },
            "content": {
                "packages": [
                    {
                        "weight": p.get("weight", 1),
                        "dimensions": {
                            "length": p.get("length", 10),
                            "width": p.get("width", 10),
                            "height": p.get("height", 10),
                        },
                        "customerReferences": [{"value": content, "typeCode": "CU"}],
                    }
                    for p in packages
                ],
                "isCustomsDeclarable": False,
                "declaredValue": 0,
                "declaredValueCurrency": "USD",
                "unitOfMeasurement": "imperial",
                "description": content,
                "incoterm": "DAP",
            },
            "outputImageProperties": {
                "printerDPI": 300,
                "encodingFormat": "pdf",
                "imageOptions": [{"typeCode": "label", "templateName": "ECOM26_A6_002"}],
            },
        }
        resp = await client.post(
            f"{self._base()}/shipments",
            headers=self._headers(),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        tracking_number = data.get("shipmentTrackingNumber", "")

        shipment_id = f"shp_{uuid.uuid4().hex}"
        now = datetime.now(tz=timezone.utc).isoformat()
        self.db.execute(
            """INSERT INTO shipments
               (id, tenant_id, carrier, tracking_number, status,
                shipper_name, consignee_name, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                shipment_id, self.tenant_id, "dhl", tracking_number, "created",
                shipper_contact.get("fullName", ""),
                receiver_contact.get("fullName", ""),
                now, now,
            ),
        )
        self._publish_event("shipment.created",
                            {"carrier": "dhl", "tracking_number": tracking_number})
        return {"shipment_id": shipment_id, "tracking_number": tracking_number,
                "data": data}

    async def track_shipment(self, tracking_number: str) -> Dict:
        client = self._get_http()
        resp = await client.get(
            f"{self._base()}/shipments/{tracking_number}/tracking",
            headers=self._headers(),
            params={"trackingView": "all-checkpoints"},
        )
        resp.raise_for_status()
        data = resp.json()
        shipments = data.get("shipments", [])
        if not shipments:
            return {"tracking_number": tracking_number, "status": "unknown"}

        shipment = shipments[0]
        events = shipment.get("events", [])
        latest_status = events[0].get("typeCode", "") if events else ""

        dhl_status_map = {
            "PU": "picked_up", "PL": "in_transit", "AA": "in_transit",
            "AD": "in_transit", "OK": "delivered", "CC": "exception",
        }
        mapped = dhl_status_map.get(latest_status, "in_transit")
        now = datetime.now(tz=timezone.utc).isoformat()
        row = self.db.fetch_one(
            "SELECT id FROM shipments WHERE tracking_number=? AND tenant_id=?",
            (tracking_number, self.tenant_id),
        )
        if row:
            self.db.execute(
                "UPDATE shipments SET status=?, updated_at=? WHERE id=?",
                (mapped, now, row["id"]),
            )
            self._publish_event("shipment.tracking_updated",
                                {"carrier": "dhl", "tracking_number": tracking_number,
                                 "status": mapped})
        return {"tracking_number": tracking_number, "status": mapped, "events": events}

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "shipments":
            rows = self.db.fetch_all(
                "SELECT tracking_number FROM shipments "
                "WHERE carrier='dhl' AND tenant_id=? AND status NOT IN ('delivered','cancelled')",
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
        shipment = payload.get("shipment", {})
        tracking_number = shipment.get("trackingNumber", "")
        events = shipment.get("events", [])
        latest = events[0].get("typeCode", "") if events else ""
        if tracking_number:
            now = datetime.now(tz=timezone.utc).isoformat()
            row = self.db.fetch_one(
                "SELECT id FROM shipments WHERE tracking_number=? AND tenant_id=?",
                (tracking_number, self.tenant_id),
            )
            if row:
                self.db.execute(
                    "UPDATE shipments SET status=?, updated_at=? WHERE id=?",
                    (latest.lower() or "in_transit", now, row["id"]),
                )

    async def health_check(self) -> Dict[str, Any]:
        try:
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(
                f"{self._base()}/rates",
                headers=self._headers(),
            )
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code < 500
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1)}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
