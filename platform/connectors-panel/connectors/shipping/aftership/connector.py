"""AfterShip Connector — REST API v4, multi-carrier tracking aggregator."""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...sdk.base import ConnectorBase
from ...sdk.manifest import ConnectorManifest, SyncConfig, WebhookConfig

MANIFEST = ConnectorManifest(
    id="aftership",
    name="AfterShip",
    category="shipping",
    description="Unified multi-carrier tracking via AfterShip API.",
    version="1.0.0",
    icon="📦",
    supports_api_key=True,
    supports_webhook=True,
    webhook=WebhookConfig(
        events=["tracking_update"],
        signature_header="aftership-hmac-sha256",
    ),
    sync=SyncConfig(entities=["trackings"], default_interval_seconds=1800),
    config_schema={
        "api_key": {"type": "string", "required": True, "secret": True,
                     "description": "AfterShip API Key"},
        "hmac_secret": {"type": "string", "required": False, "secret": True,
                         "description": "AfterShip HMAC secret for webhook verification"},
    },
    emits_events=["shipment.tracking_updated", "shipment.delivered"],
)

AFTERSHIP_API = "https://api.aftership.com/v4"


class AfterShipConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 3.0
    RATE_BURST = 10.0

    def _headers(self) -> Dict:
        return {
            "aftership-api-key": self.config["api_key"],
            "Content-Type": "application/json",
        }

    async def add_tracking(self, tracking_number: str, slug: str,
                            title: Optional[str] = None,
                            order_id: Optional[str] = None,
                            customer_name: Optional[str] = None) -> Dict:
        client = self._get_http()
        tracking_payload: Dict[str, Any] = {
            "tracking_number": tracking_number,
            "slug": slug,
        }
        if title:
            tracking_payload["title"] = title
        if order_id:
            tracking_payload["order_id"] = order_id
        if customer_name:
            tracking_payload["customer_name"] = customer_name

        resp = await client.post(
            f"{AFTERSHIP_API}/trackings",
            headers=self._headers(),
            json={"tracking": tracking_payload},
        )
        if resp.status_code == 409:
            # Already exists — return the existing tracking
            return await self.get_tracking(tracking_number, slug)
        resp.raise_for_status()
        data = resp.json()
        tracking = data.get("data", {}).get("tracking", {})

        # Persist in our shipments table
        shipment_id = f"shp_{uuid.uuid4().hex}"
        now = datetime.now(tz=timezone.utc).isoformat()
        self.db.execute(
            """INSERT OR IGNORE INTO erp_shipments
               (shipment_id, tenant_id, carrier, tracking_number, status,
                service_type, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (shipment_id, self.tenant_id, slug, tracking_number,
             tracking.get("tag", "InfoReceived").lower(),
             tracking.get("service_type_name", ""), now, now),
        )
        self._publish_event("shipment.created",
                            {"carrier": slug, "tracking_number": tracking_number,
                             "source": "aftership"})
        return {"shipment_id": shipment_id, "tracking": tracking}

    async def get_tracking(self, tracking_number: str, slug: str) -> Dict:
        client = self._get_http()
        resp = await client.get(
            f"{AFTERSHIP_API}/trackings/{slug}/{tracking_number}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("tracking", {})

    async def get_all_trackings(self, page: int = 1,
                                  limit: int = 100,
                                  tag: Optional[str] = None) -> List[Dict]:
        client = self._get_http()
        params: Dict[str, Any] = {"page": page, "limit": limit}
        if tag:
            params["tag"] = tag
        resp = await client.get(
            f"{AFTERSHIP_API}/trackings",
            headers=self._headers(),
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("trackings", [])

    async def delete_tracking(self, tracking_number: str, slug: str) -> bool:
        client = self._get_http()
        resp = await client.delete(
            f"{AFTERSHIP_API}/trackings/{slug}/{tracking_number}",
            headers=self._headers(),
        )
        return resp.status_code == 200

    def _map_tag(self, tag: str) -> str:
        tag_map = {
            "InfoReceived": "created",
            "InTransit": "in_transit",
            "OutForDelivery": "out_for_delivery",
            "AttemptFail": "exception",
            "Delivered": "delivered",
            "Exception": "exception",
            "Expired": "exception",
            "Pending": "created",
        }
        return tag_map.get(tag, "in_transit")

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "trackings":
            # Fetch non-delivered trackings and update statuses
            trackings = await self.get_all_trackings(
                limit=200,
                tag="InTransit",
            )
            updated = 0
            now = datetime.now(tz=timezone.utc).isoformat()
            for t in trackings:
                tracking_number = t.get("tracking_number", "")
                slug = t.get("slug", "")
                tag = t.get("tag", "")
                mapped = self._map_tag(tag)
                row = self.db.fetch_one(
                    "SELECT shipment_id FROM erp_shipments "
                    "WHERE tracking_number=? AND carrier=? AND tenant_id=?",
                    (tracking_number, slug, self.tenant_id),
                )
                if row:
                    self.db.execute(
                        "UPDATE erp_shipments SET status=?, updated_at=? WHERE shipment_id=?",
                        (mapped, now, row["shipment_id"]),
                    )
                    updated += 1
                    self._publish_event("shipment.tracking_updated",
                                        {"carrier": slug,
                                         "tracking_number": tracking_number,
                                         "status": mapped,
                                         "source": "aftership"})
            return {"synced": updated, "entity": "trackings"}
        return {"synced": 0, "entity": entity}

    async def verify_webhook_signature(self, raw_body: bytes,
                                        headers: Dict) -> bool:
        secret = self.config.get("hmac_secret", "")
        if not secret:
            return True
        sig = headers.get("aftership-hmac-sha256", "")
        expected = hmac.new(
            secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, sig)

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                              raw_body: bytes, headers: Dict) -> None:
        msg = payload.get("msg", {})
        tracking_number = msg.get("tracking_number", "")
        slug = msg.get("slug", "")
        tag = msg.get("tag", "")
        if not tracking_number:
            return

        mapped = self._map_tag(tag)
        now = datetime.now(tz=timezone.utc).isoformat()

        # Upsert
        row = self.db.fetch_one(
            "SELECT shipment_id FROM erp_shipments "
            "WHERE tracking_number=? AND carrier=? AND tenant_id=?",
            (tracking_number, slug, self.tenant_id),
        )
        if row:
            self.db.execute(
                "UPDATE erp_shipments SET status=?, updated_at=? WHERE shipment_id=?",
                (mapped, now, row["shipment_id"]),
            )
        else:
            shp_id = f"shp_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO erp_shipments
                   (shipment_id, tenant_id, carrier, tracking_number, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (shp_id, self.tenant_id, slug, tracking_number, mapped, now, now),
            )

        self._publish_event("shipment.tracking_updated",
                            {"carrier": slug, "tracking_number": tracking_number,
                             "status": mapped, "tag": tag, "source": "aftership"})
        if mapped == "delivered":
            self._publish_event("shipment.delivered",
                                {"carrier": slug, "tracking_number": tracking_number,
                                 "source": "aftership"})

    async def health_check(self) -> Dict[str, Any]:
        try:
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(
                f"{AFTERSHIP_API}/couriers/all",
                headers=self._headers(),
            )
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code == 200
            data = resp.json() if ok else {}
            couriers_count = len(data.get("data", {}).get("couriers", []))
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1),
                    "couriers_available": couriers_count}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
