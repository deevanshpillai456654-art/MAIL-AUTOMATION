"""QuickBooks Online Connector — OAuth2, invoices, payments, customers, expenses."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from ..sdk.base import ConnectorBase
from ..sdk.manifest import ConnectorManifest, OAuthConfig, SyncConfig, Permission

MANIFEST = ConnectorManifest(
    id="quickbooks",
    name="QuickBooks",
    category="accounting",
    description="Sync invoices, customers, payments, and expenses from QuickBooks Online.",
    version="1.0.0",
    icon="💰",
    supports_oauth=True,
    oauth=OAuthConfig(
        provider_id="intuit",
        auth_url="https://appcenter.intuit.com/connect/oauth2",
        token_url="https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
        scopes=["com.intuit.quickbooks.accounting"],
        supports_refresh=True,
        extra_params={"response_type": "code"},
    ),
    sync=SyncConfig(
        entities=["invoices", "customers", "payments", "expenses"],
        default_interval_seconds=3600,
    ),
    config_schema={
        "client_id": {"type": "string", "required": True},
        "client_secret": {"type": "string", "required": True, "secret": True},
        "realm_id": {"type": "string", "required": True, "description": "QuickBooks company ID"},
        "sandbox": {"type": "boolean", "default": False},
    },
    emits_events=["invoice.created", "invoice.paid", "erp.sync.completed"],
)

QB_API_BASE = "https://quickbooks.api.intuit.com/v3/company/{realm_id}"
QB_SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company/{realm_id}"


class QuickBooksConnector(ConnectorBase):
    MANIFEST = MANIFEST

    def _base(self) -> str:
        realm_id = self.config.get("realm_id", "")
        base = QB_SANDBOX_BASE if self.config.get("sandbox") else QB_API_BASE
        return base.format(realm_id=realm_id)

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        params = urlencode({
            "client_id": self.config["client_id"],
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "com.intuit.quickbooks.accounting",
            "state": state,
        })
        return f"https://appcenter.intuit.com/connect/oauth2?{params}"

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        client = self._get_http()
        import base64
        creds = base64.b64encode(
            f"{self.config['client_id']}:{self.config['client_secret']}".encode()
        ).decode()
        resp = await client.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            headers={"Authorization": f"Basic {creds}",
                     "Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": code,
                  "redirect_uri": redirect_uri},
        )
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        self._store_token(data["access_token"], data.get("refresh_token"),
                          expires_at, ["com.intuit.quickbooks.accounting"])
        return data

    async def refresh_access_token(self) -> str:
        tok = self._get_token()
        if not tok or not tok.get("refresh_token"):
            raise RuntimeError("No refresh token")
        client = self._get_http()
        import base64
        creds = base64.b64encode(
            f"{self.config['client_id']}:{self.config['client_secret']}".encode()
        ).decode()
        resp = await client.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            headers={"Authorization": f"Basic {creds}",
                     "Accept": "application/json",
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token",
                  "refresh_token": tok["refresh_token"]},
        )
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        self._store_token(data["access_token"],
                          data.get("refresh_token", tok["refresh_token"]),
                          expires_at, tok.get("scopes", []))
        return data["access_token"]

    async def _qb_query(self, query: str) -> List[Dict]:
        token = await self.get_valid_token()
        client = self._get_http()
        resp = await client.get(
            f"{self._base()}/query",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"query": query},
        )
        resp.raise_for_status()
        data = resp.json()
        # QB wraps results in QueryResponse
        qr = data.get("QueryResponse", {})
        # Find first non-startPosition key with list value
        for k, v in qr.items():
            if isinstance(v, list):
                return v
        return []

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "invoices":
            where = ""
            if since:
                where = f" WHERE MetaData.LastUpdatedTime >= '{since.strftime('%Y-%m-%d')}'"
            records = await self._qb_query(
                f"SELECT * FROM Invoice{where} MAXRESULTS 500"
            )
            for r in records:
                self._upsert_invoice(r)
            return {"synced": len(records), "entity": "invoices"}

        elif entity == "customers":
            records = await self._qb_query(
                "SELECT * FROM Customer WHERE Active = true MAXRESULTS 500"
            )
            for r in records:
                self._upsert_contact(r)
            return {"synced": len(records), "entity": "customers"}

        elif entity == "payments":
            records = await self._qb_query(
                "SELECT * FROM Payment MAXRESULTS 500"
            )
            for r in records:
                self._publish_event("invoice.paid",
                                    {"source": "quickbooks",
                                     "payment_id": r.get("Id"),
                                     "amount": r.get("TotalAmt")})
            return {"synced": len(records), "entity": "payments"}

        return {"synced": 0, "entity": entity}

    def _upsert_invoice(self, r: Dict) -> None:
        ext_id = r.get("Id", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        status_map = {
            "Draft": "draft", "Pending": "sent",
            "Voided": "cancelled",
        }
        # QB status via Balance
        balance = float(r.get("Balance", 0) or 0)
        total = float(r.get("TotalAmt", 0) or 0)
        status = "paid" if balance == 0 and total > 0 else "sent"
        if r.get("EmailStatus") == "NotSet":
            status = "draft"
        existing = self.db.fetch_one(
            "SELECT invoice_id FROM erp_invoices WHERE invoice_number=? AND tenant_id=?",
            (r.get("DocNumber", ext_id), self.tenant_id),
        )
        if existing:
            self.db.execute(
                "UPDATE erp_invoices SET status=?, updated_at=? WHERE invoice_id=?",
                (status, now, existing["invoice_id"]),
            )
        else:
            iid = f"inv_{uuid.uuid4().hex}"
            customer = r.get("CustomerRef", {})
            due = r.get("DueDate", "")
            self.db.execute(
                """INSERT INTO erp_invoices
                   (invoice_id, tenant_id, invoice_number, vendor_id, status,
                    amount, due_date, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (iid, self.tenant_id, r.get("DocNumber", ext_id),
                 customer.get("value", ""), status,
                 total, due or None, now, now),
            )
            self._publish_event("invoice.created",
                                {"source": "quickbooks", "id": ext_id, "amount": total})

    def _upsert_contact(self, r: Dict) -> None:
        ext_id = r.get("Id", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        if not self.db.fetch_one(
            "SELECT contact_id FROM crm_contacts WHERE external_id=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        ):
            cid = f"cnt_{uuid.uuid4().hex}"
            bill_addr = r.get("BillAddr", {}) or {}
            self.db.execute(
                """INSERT INTO crm_contacts
                   (contact_id, tenant_id, first_name, last_name, email, phone,
                    company, source, external_id, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,'quickbooks',?,'active',?,?)""",
                (cid, self.tenant_id,
                 r.get("GivenName", ""), r.get("FamilyName", ""),
                 r.get("PrimaryEmailAddr", {}).get("Address", ""),
                 r.get("PrimaryPhone", {}).get("FreeFormNumber", ""),
                 r.get("CompanyName", ""),
                 ext_id, now, now),
            )

    async def verify_webhook_signature(self, raw_body: bytes, headers: Dict) -> bool:
        return True

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict) -> None:
        entities = payload.get("eventNotifications", [])
        for notification in entities:
            for e in notification.get("dataChangeEvent", {}).get("entities", []):
                self._publish_event(f"quickbooks.{e.get('name','').lower()}.updated",
                                    {"id": e.get("id"), "operation": e.get("operation")})

    async def health_check(self) -> Dict[str, Any]:
        try:
            token = await self.get_valid_token()
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(
                f"{self._base()}/companyinfo/{self.config.get('realm_id','')}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code == 200
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1)}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
