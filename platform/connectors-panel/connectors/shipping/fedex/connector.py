"""FedEx Connector — REST API v1, rate quotes, shipment booking, tracking."""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...sdk.base import ConnectorBase
from ...sdk.manifest import ConnectorManifest, SyncConfig

MANIFEST = ConnectorManifest(
    id="fedex",
    name="FedEx",
    category="shipping",
    description="Create FedEx shipments, get rate quotes, and track packages.",
    version="1.0.0",
    icon="🟣",
    supports_api_key=True,
    sync=SyncConfig(entities=["shipments"], default_interval_seconds=3600),
    config_schema={
        "client_id": {"type": "string", "required": True,
                       "description": "FedEx API Key (developer.fedex.com)"},
        "client_secret": {"type": "string", "required": True, "secret": True,
                           "description": "FedEx Secret Key"},
        "account_number": {"type": "string", "required": True},
        "sandbox": {"type": "boolean", "default": False},
    },
    emits_events=["shipment.created", "shipment.tracking_updated"],
)

FEDEX_PROD = "https://apis.fedex.com"
FEDEX_SANDBOX = "https://apis-sandbox.fedex.com"


class FedExConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 3.0
    RATE_BURST = 10.0

    def _base(self) -> str:
        return FEDEX_SANDBOX if self.config.get("sandbox") else FEDEX_PROD

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
        # Request new token via client credentials
        client = self._get_http()
        resp = await client.post(
            f"{self._base()}/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.config["client_id"],
                "client_secret": self.config["client_secret"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        self._store_token(data["access_token"], None, expires_at, [])
        return data["access_token"]

    def _headers(self, token: str) -> Dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-locale": "en_US",
        }

    async def get_rates(self, shipper: Dict, recipient: Dict,
                         packages: List[Dict],
                         service_type: Optional[str] = None) -> List[Dict]:
        token = await self._get_access_token()
        client = self._get_http()
        payload = {
            "accountNumber": {"value": self.config["account_number"]},
            "requestedShipment": {
                "shipper": {"address": shipper},
                "recipient": {"address": recipient},
                "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
                "requestedPackageLineItems": [
                    {
                        "weight": {"units": p.get("weight_unit", "LB"),
                                   "value": p.get("weight", 1)},
                        "dimensions": {
                            "length": p.get("length", 10),
                            "width": p.get("width", 10),
                            "height": p.get("height", 10),
                            "units": p.get("dim_unit", "IN"),
                        },
                    }
                    for p in packages
                ],
                "rateRequestType": ["PREFERRED"],
            },
        }
        if service_type:
            payload["requestedShipment"]["serviceType"] = service_type
        resp = await client.post(
            f"{self._base()}/rate/v1/rates/quotes",
            headers=self._headers(token),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        rates = []
        for detail in data.get("output", {}).get("rateReplyDetails", []):
            for rate in detail.get("ratedShipmentDetails", []):
                rates.append({
                    "service_type": detail.get("serviceType"),
                    "service_name": detail.get("serviceName"),
                    "total_charge": rate.get("totalNetCharge"),
                    "currency": rate.get("currency", "USD"),
                    "transit_days": detail.get("operationalDetail",
                                               {}).get("transitTime"),
                })
        return rates

    async def create_shipment(self, shipper: Dict, recipient: Dict,
                               packages: List[Dict], service_type: str,
                               label_format: str = "PDF") -> Dict:
        token = await self._get_access_token()
        client = self._get_http()
        acct = self.config["account_number"]
        payload = {
            "labelResponseOptions": "LABEL",
            "requestedShipment": {
                "shipper": shipper,
                "recipients": [recipient],
                "serviceType": service_type,
                "packagingType": "YOUR_PACKAGING",
                "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
                "shippingChargesPayment": {
                    "paymentType": "SENDER",
                    "payor": {"responsibleParty": {"accountNumber": {"value": acct}}},
                },
                "labelSpecification": {
                    "labelFormatType": "COMMON2D",
                    "imageType": label_format,
                    "labelStockType": "PAPER_7X4.75",
                },
                "requestedPackageLineItems": packages,
            },
            "accountNumber": {"value": acct},
        }
        resp = await client.post(
            f"{self._base()}/ship/v1/shipments",
            headers=self._headers(token),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        output = data.get("output", {})
        tx_detail = output.get("transactionShipments", [{}])[0]
        tracking_number = tx_detail.get("masterTrackingNumber", "")

        shipment_id = f"shp_{uuid.uuid4().hex}"
        now = datetime.now(tz=timezone.utc).isoformat()
        self.db.execute(
            """INSERT INTO erp_shipments
               (shipment_id, tenant_id, carrier, tracking_number, status,
                shipper_name, shipper_address, recipient_name, recipient_address,
                service_type, label_url, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                shipment_id, self.tenant_id, "fedex", tracking_number, "created",
                shipper.get("contact", {}).get("companyName", ""),
                shipper.get("address", {}).get("streetLines", [""])[0],
                recipient.get("contact", {}).get("companyName", ""),
                recipient.get("address", {}).get("streetLines", [""])[0],
                service_type, "", now, now,
            ),
        )
        self._publish_event("shipment.created",
                            {"carrier": "fedex", "tracking_number": tracking_number,
                             "service": service_type})
        return {"shipment_id": shipment_id, "tracking_number": tracking_number,
                "output": output}

    async def track_shipment(self, tracking_number: str) -> Dict:
        token = await self._get_access_token()
        client = self._get_http()
        payload = {
            "includeDetailedScans": True,
            "trackingInfo": [
                {"trackingNumberInfo": {"trackingNumber": tracking_number}}
            ],
        }
        resp = await client.post(
            f"{self._base()}/track/v1/trackingnumbers",
            headers=self._headers(token),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("output", {}).get("completeTrackResults", [])
        if results:
            track = results[0].get("trackResults", [{}])[0]
            status = track.get("latestStatusDetail", {}).get("code", "")
            events = track.get("dateAndTimes", [])
            self._upsert_tracking(tracking_number, status, events)
            return {"tracking_number": tracking_number, "status": status,
                    "events": events}
        return {"tracking_number": tracking_number, "status": "unknown"}

    def _upsert_tracking(self, tracking_number: str, status: str,
                          events: List) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        row = self.db.fetch_one(
            "SELECT shipment_id FROM erp_shipments WHERE tracking_number=? AND tenant_id=?",
            (tracking_number, self.tenant_id),
        )
        fedex_status_map = {
            "OC": "created", "PU": "picked_up", "IT": "in_transit",
            "DL": "delivered", "DE": "exception", "CA": "cancelled",
        }
        mapped = fedex_status_map.get(status, "in_transit")
        if row:
            self.db.execute(
                "UPDATE erp_shipments SET status=?, updated_at=? WHERE shipment_id=?",
                (mapped, now, row["shipment_id"]),
            )
            self._publish_event("shipment.tracking_updated",
                                {"carrier": "fedex",
                                 "tracking_number": tracking_number,
                                 "status": mapped})

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "shipments":
            rows = self.db.fetch_all(
                "SELECT tracking_number FROM erp_shipments "
                "WHERE carrier='fedex' AND tenant_id=? AND status NOT IN ('delivered','cancelled')",
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
        return True  # FedEx uses IP allowlisting

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                              raw_body: bytes, headers: Dict) -> None:
        for event in payload.get("events", [payload]):
            tracking = event.get("trackingNumber", "")
            status = event.get("eventType", "")
            if tracking:
                self._upsert_tracking(tracking, status, [])

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
