"""Shiprocket Connector — REST API v1, orders, AWB, tracking (India)."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...sdk.base import ConnectorBase
from ...sdk.manifest import ConnectorManifest, SyncConfig

MANIFEST = ConnectorManifest(
    id="shiprocket",
    name="Shiprocket",
    category="shipping",
    description="Create Shiprocket orders, generate AWB, and track shipments.",
    version="1.0.0",
    icon="🚀",
    supports_api_key=True,
    sync=SyncConfig(entities=["shipments", "orders"], default_interval_seconds=1800),
    config_schema={
        "email": {"type": "string", "required": True,
                   "description": "Shiprocket account email"},
        "password": {"type": "string", "required": True, "secret": True,
                      "description": "Shiprocket account password"},
        "channel_id": {"type": "string", "required": False,
                        "description": "Shiprocket channel/store ID"},
    },
    emits_events=["shipment.created", "shipment.tracking_updated"],
)

SHIPROCKET_API = "https://apiv2.shiprocket.in/v1/external"


class ShiprocketConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 5.0
    RATE_BURST = 15.0

    async def _get_access_token(self) -> str:
        tok = self._get_token()
        if tok and tok.get("access_token"):
            from datetime import datetime as dt2
            try:
                exp = dt2.fromisoformat(tok["expires_at"].replace("Z", "+00:00"))
                if (exp - dt2.now(tz=timezone.utc)).total_seconds() > 60:
                    return tok["access_token"]
            except Exception:
                pass
        client = self._get_http()
        resp = await client.post(
            f"{SHIPROCKET_API}/auth/login",
            json={
                "email": self.config["email"],
                "password": self.config["password"],
            },
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token", "")
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(days=9)).isoformat()
        self._store_token(token, None, expires_at, [])
        return token

    def _headers(self, token: str) -> Dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def get_courier_serviceability(self, pickup_pincode: str,
                                          delivery_pincode: str,
                                          cod: int = 0,
                                          weight: float = 0.5) -> List[Dict]:
        token = await self._get_access_token()
        client = self._get_http()
        resp = await client.get(
            f"{SHIPROCKET_API}/courier/serviceability/",
            headers=self._headers(token),
            params={
                "pickup_postcode": pickup_pincode,
                "delivery_postcode": delivery_pincode,
                "cod": cod,
                "weight": weight,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("available_courier_companies", [])

    async def create_order(self, order_data: Dict) -> Dict:
        token = await self._get_access_token()
        client = self._get_http()
        channel_id = self.config.get("channel_id")
        if channel_id:
            order_data["channel_id"] = channel_id
        resp = await client.post(
            f"{SHIPROCKET_API}/orders/create/adhoc",
            headers=self._headers(token),
            json=order_data,
        )
        resp.raise_for_status()
        data = resp.json()
        order_id = data.get("order_id")
        shipment_id_sr = data.get("shipment_id")

        shipment_id = f"shp_{uuid.uuid4().hex}"
        now = datetime.now(tz=timezone.utc).isoformat()
        self.db.execute(
            """INSERT INTO erp_shipments
               (shipment_id, tenant_id, carrier, tracking_number, status,
                recipient_name, recipient_address, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                shipment_id, self.tenant_id, "shiprocket",
                str(shipment_id_sr or ""), "created",
                order_data.get("billing_customer_name", ""),
                order_data.get("billing_address", ""),
                now, now,
            ),
        )
        self._publish_event("shipment.created",
                            {"carrier": "shiprocket", "order_id": order_id,
                             "shipment_id": shipment_id_sr})
        return {"shipment_id": shipment_id, "sr_order_id": order_id,
                "sr_shipment_id": shipment_id_sr, "data": data}

    async def assign_awb(self, shipment_id: int, courier_id: int) -> Dict:
        token = await self._get_access_token()
        client = self._get_http()
        resp = await client.post(
            f"{SHIPROCKET_API}/courier/assign/awb",
            headers=self._headers(token),
            json={"shipment_id": shipment_id, "courier_id": courier_id},
        )
        resp.raise_for_status()
        data = resp.json()
        awb = data.get("response", {}).get("data", {}).get("awb_code", "")
        # Update tracking number in DB
        now = datetime.now(tz=timezone.utc).isoformat()
        self.db.execute(
            "UPDATE erp_shipments SET tracking_number=?, updated_at=? "
            "WHERE tracking_number=? AND tenant_id=? AND carrier='shiprocket'",
            (awb, now, str(shipment_id), self.tenant_id),
        )
        return {"awb": awb, "data": data}

    async def generate_label(self, shipment_ids: List[int]) -> Dict:
        token = await self._get_access_token()
        client = self._get_http()
        resp = await client.post(
            f"{SHIPROCKET_API}/courier/generate/label",
            headers=self._headers(token),
            json={"shipment_id": shipment_ids},
        )
        resp.raise_for_status()
        return resp.json()

    async def track_by_awb(self, awb: str) -> Dict:
        token = await self._get_access_token()
        client = self._get_http()
        resp = await client.get(
            f"{SHIPROCKET_API}/courier/track/awb/{awb}",
            headers=self._headers(token),
        )
        resp.raise_for_status()
        data = resp.json()
        tracking_data = data.get("tracking_data", {})
        track_status = tracking_data.get("track_status", 0)
        shipment_status = tracking_data.get("shipment_status", "")

        status_map = {
            1: "created", 2: "picked_up", 3: "in_transit",
            4: "out_for_delivery", 5: "delivered",
            6: "cancelled", 7: "exception",
        }
        mapped = status_map.get(track_status, "in_transit")
        now = datetime.now(tz=timezone.utc).isoformat()
        row = self.db.fetch_one(
            "SELECT shipment_id FROM erp_shipments WHERE tracking_number=? AND tenant_id=?",
            (awb, self.tenant_id),
        )
        if row:
            self.db.execute(
                "UPDATE erp_shipments SET status=?, updated_at=? WHERE shipment_id=?",
                (mapped, now, row["shipment_id"]),
            )
            self._publish_event("shipment.tracking_updated",
                                {"carrier": "shiprocket", "awb": awb,
                                 "status": mapped})
        return {"awb": awb, "status": mapped, "shipment_status": shipment_status,
                "tracking_data": tracking_data}

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "shipments":
            rows = self.db.fetch_all(
                "SELECT tracking_number FROM erp_shipments "
                "WHERE carrier='shiprocket' AND tenant_id=? "
                "AND status NOT IN ('delivered','cancelled') "
                "AND tracking_number != '' AND tracking_number IS NOT NULL",
                (self.tenant_id,),
            )
            updated = 0
            for row in rows or []:
                try:
                    await self.track_by_awb(row["tracking_number"])
                    updated += 1
                except Exception:
                    pass
            return {"synced": updated, "entity": "shipments"}

        elif entity == "orders":
            token = await self._get_access_token()
            client = self._get_http()
            params: Dict[str, Any] = {"per_page": 50, "page": 1}
            if since:
                params["from"] = since.strftime("%Y-%m-%d")
            resp = await client.get(
                f"{SHIPROCKET_API}/orders",
                headers=self._headers(token),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            orders = data.get("data", {}).get("data", [])
            return {"synced": len(orders), "entity": "orders"}

        return {"synced": 0, "entity": entity}

    async def verify_webhook_signature(self, raw_body: bytes,
                                        headers: Dict) -> bool:
        return True

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                              raw_body: bytes, headers: Dict) -> None:
        awb = payload.get("awb", "")
        status = payload.get("current_status", "")
        if awb and status:
            now = datetime.now(tz=timezone.utc).isoformat()
            row = self.db.fetch_one(
                "SELECT shipment_id FROM erp_shipments WHERE tracking_number=? AND tenant_id=?",
                (awb, self.tenant_id),
            )
            if row:
                self.db.execute(
                    "UPDATE erp_shipments SET status=?, updated_at=? WHERE shipment_id=?",
                    (status.lower().replace(" ", "_"), now, row["shipment_id"]),
                )
                self._publish_event("shipment.tracking_updated",
                                    {"carrier": "shiprocket", "awb": awb,
                                     "status": status})

    async def health_check(self) -> Dict[str, Any]:
        try:
            t0 = time.monotonic()
            await self._get_access_token()
            latency = (time.monotonic() - t0) * 1000
            self._record_health(True, latency)
            return {"healthy": True, "latency_ms": round(latency, 1)}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
