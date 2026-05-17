"""UPS Connector — REST API (2024), rate quotes, shipment booking, tracking."""
from __future__ import annotations

import base64
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ...sdk.base import ConnectorBase
from ...sdk.manifest import ConnectorManifest, SyncConfig

MANIFEST = ConnectorManifest(
    id="ups",
    name="UPS",
    category="shipping",
    description="Create UPS shipments, get rate quotes, and track packages.",
    version="1.0.0",
    icon="🟤",
    supports_api_key=True,
    sync=SyncConfig(entities=["shipments"], default_interval_seconds=3600),
    config_schema={
        "client_id": {"type": "string", "required": True,
                       "description": "UPS Client ID (developer.ups.com)"},
        "client_secret": {"type": "string", "required": True, "secret": True,
                           "description": "UPS Client Secret"},
        "account_number": {"type": "string", "required": True,
                            "description": "UPS Shipper Account Number"},
        "sandbox": {"type": "boolean", "default": False},
    },
    emits_events=["shipment.created", "shipment.tracking_updated"],
)

UPS_PROD = "https://onlinetools.ups.com/api"
UPS_SANDBOX = "https://wwwcie.ups.com/api"


class UPSConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 3.0
    RATE_BURST = 10.0

    def _base(self) -> str:
        return UPS_SANDBOX if self.config.get("sandbox") else UPS_PROD

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
        creds = base64.b64encode(
            f"{self.config['client_id']}:{self.config['client_secret']}".encode()
        ).decode()
        client = self._get_http()
        resp = await client.post(
            f"{self._base()}/security/v1/oauth/token",
            headers={"Authorization": f"Basic {creds}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 14399))).isoformat()
        self._store_token(data["access_token"], None, expires_at, [])
        return data["access_token"]

    def _headers(self, token: str) -> Dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "transId": uuid.uuid4().hex,
            "transactionSrc": "mailpilot",
        }

    async def get_rates(self, shipper: Dict, recipient: Dict,
                         packages: List[Dict]) -> List[Dict]:
        token = await self._get_access_token()
        client = self._get_http()
        payload = {
            "RateRequest": {
                "Shipment": {
                    "Shipper": {
                        "Address": shipper,
                        "ShipperNumber": self.config["account_number"],
                    },
                    "ShipTo": {"Address": recipient},
                    "ShipFrom": {"Address": shipper},
                    "Service": {"Code": "03", "Description": "UPS Ground"},
                    "Package": [
                        {
                            "PackagingType": {"Code": "02"},
                            "PackageWeight": {
                                "UnitOfMeasurement": {"Code": p.get("weight_unit", "LBS")},
                                "Weight": str(p.get("weight", 1)),
                            },
                        }
                        for p in packages
                    ],
                }
            }
        }
        resp = await client.post(
            f"{self._base()}/rating/v1/Shop",
            headers=self._headers(token),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        rates = []
        for service in data.get("RateResponse", {}).get("RatedShipment", []):
            rates.append({
                "service_code": service.get("Service", {}).get("Code"),
                "total_charge": service.get("TotalCharges", {}).get("MonetaryValue"),
                "currency": service.get("TotalCharges", {}).get("CurrencyCode", "USD"),
                "billing_weight": service.get("BillingWeight", {}).get("Weight"),
            })
        return rates

    async def create_shipment(self, shipper: Dict, ship_to: Dict,
                               packages: List[Dict],
                               service_code: str = "03") -> Dict:
        token = await self._get_access_token()
        client = self._get_http()
        acct = self.config["account_number"]
        payload = {
            "ShipmentRequest": {
                "Shipment": {
                    "Shipper": {**shipper, "ShipperNumber": acct},
                    "ShipTo": ship_to,
                    "ShipFrom": shipper,
                    "PaymentInformation": {
                        "ShipmentCharge": {
                            "Type": "01",
                            "BillShipper": {"AccountNumber": acct},
                        }
                    },
                    "Service": {"Code": service_code},
                    "Package": [
                        {
                            "PackagingType": {"Code": "02"},
                            "PackageWeight": {
                                "UnitOfMeasurement": {"Code": "LBS"},
                                "Weight": str(p.get("weight", 1)),
                            },
                        }
                        for p in packages
                    ],
                },
                "LabelSpecification": {
                    "LabelImageFormat": {"Code": "GIF"},
                    "HTTPUserAgent": "MailPilot",
                },
            }
        }
        resp = await client.post(
            f"{self._base()}/shipments/v1/ship",
            headers=self._headers(token),
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("ShipmentResponse", {}).get("ShipmentResults", {})
        tracking_number = result.get("ShipmentIdentificationNumber", "")

        shipment_id = f"shp_{uuid.uuid4().hex}"
        now = datetime.now(tz=timezone.utc).isoformat()
        self.db.execute(
            """INSERT INTO shipments
               (id, tenant_id, carrier, tracking_number, status,
                shipper_name, consignee_name, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (shipment_id, self.tenant_id, "ups", tracking_number, "created",
             shipper.get("Name", ""), ship_to.get("Name", ""),
             now, now),
        )
        self._publish_event("shipment.created",
                            {"carrier": "ups", "tracking_number": tracking_number})
        return {"shipment_id": shipment_id, "tracking_number": tracking_number,
                "result": result}

    async def track_shipment(self, tracking_number: str) -> Dict:
        token = await self._get_access_token()
        client = self._get_http()
        resp = await client.get(
            f"{self._base()}/track/v1/details/{tracking_number}",
            headers=self._headers(token),
            params={"locale": "en_US", "returnSignature": "false"},
        )
        resp.raise_for_status()
        data = resp.json()
        shipment = (data.get("trackResponse", {})
                       .get("shipment", [{}])[0])
        packages_data = shipment.get("package", [{}])
        pkg = packages_data[0] if packages_data else {}
        activity = pkg.get("activity", [{}])[0] if pkg.get("activity") else {}
        status_code = activity.get("status", {}).get("code", "")
        status_desc = activity.get("status", {}).get("description", "")

        ups_status_map = {
            "I": "in_transit", "O": "in_transit", "D": "delivered",
            "P": "picked_up", "M": "created", "X": "exception",
        }
        mapped = ups_status_map.get(status_code[:1] if status_code else "", "in_transit")
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
                                {"carrier": "ups", "tracking_number": tracking_number,
                                 "status": mapped, "description": status_desc})
        return {"tracking_number": tracking_number, "status": mapped,
                "description": status_desc}

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "shipments":
            rows = self.db.fetch_all(
                "SELECT tracking_number FROM shipments "
                "WHERE carrier='ups' AND tenant_id=? AND status NOT IN ('delivered','cancelled')",
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
        tracking = payload.get("trackingNumber", "")
        status = payload.get("localActivityScan", {}).get("activityStatus", "")
        if tracking:
            now = datetime.now(tz=timezone.utc).isoformat()
            row = self.db.fetch_one(
                "SELECT id FROM shipments WHERE tracking_number=? AND tenant_id=?",
                (tracking, self.tenant_id),
            )
            if row:
                self.db.execute(
                    "UPDATE shipments SET status=?, updated_at=? WHERE id=?",
                    (status.lower() or "in_transit", now, row["id"]),
                )

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
