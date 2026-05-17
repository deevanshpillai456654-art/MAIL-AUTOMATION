"""Xero Connector — OAuth2 (PKCE), invoices, contacts, payments, accounts."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from ..sdk.base import ConnectorBase
from ..sdk.manifest import ConnectorManifest, OAuthConfig, SyncConfig, Permission

MANIFEST = ConnectorManifest(
    id="xero",
    name="Xero",
    category="accounting",
    description="Sync invoices, contacts, payments, and accounts from Xero.",
    version="1.0.0",
    icon="💙",
    supports_oauth=True,
    oauth=OAuthConfig(
        provider_id="xero",
        auth_url="https://login.xero.com/identity/connect/authorize",
        token_url="https://identity.xero.com/connect/token",
        scopes=["accounting.transactions", "accounting.contacts",
                "accounting.settings", "offline_access"],
        supports_refresh=True,
        extra_params={"response_type": "code"},
    ),
    sync=SyncConfig(
        entities=["invoices", "contacts", "payments", "accounts"],
        default_interval_seconds=3600,
    ),
    config_schema={
        "client_id": {"type": "string", "required": True},
        "client_secret": {"type": "string", "required": True, "secret": True},
    },
    emits_events=["invoice.created", "invoice.paid", "erp.sync.completed"],
)

XERO_API = "https://api.xero.com/api.xro/2.0"
XERO_CONNECTIONS = "https://api.xero.com/connections"


class XeroConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 5.0
    RATE_BURST = 10.0

    def _make_pkce(self) -> tuple[str, str]:
        verifier = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        return verifier, challenge

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        verifier, challenge = self._make_pkce()
        # Store verifier temporarily for exchange_code to retrieve
        from ...shared.utils import encrypt_secret
        now_str = datetime.now(tz=timezone.utc).isoformat()
        self.db.execute(
            """INSERT OR REPLACE INTO oauth_tokens
               (id, connector_id, tenant_id, provider,
                access_token_enc, refresh_token_enc,
                expires_at, scopes, is_valid, created_at)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (
                f"pkce_{state[:20]}", self.instance_id,
                self.tenant_id, "pkce",
                encrypt_secret(verifier), None, None, '["pkce"]',
                now_str,
            ),
        )
        params = urlencode({
            "response_type": "code",
            "client_id": self.config["client_id"],
            "redirect_uri": redirect_uri,
            "scope": " ".join(MANIFEST.oauth.scopes),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return f"https://login.xero.com/identity/connect/authorize?{params}"

    def _basic_auth(self) -> str:
        creds = f"{self.config['client_id']}:{self.config['client_secret']}"
        return "Basic " + base64.b64encode(creds.encode()).decode()

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        # Retrieve PKCE verifier (best-effort; fall back if missing)
        pkce_row = self.db.fetch_one(
            "SELECT access_token_enc FROM oauth_tokens WHERE connector_id=? AND provider='pkce' AND tenant_id=?",
            (self.instance_id, self.tenant_id),
        )
        if pkce_row:
            from ...shared.utils import decrypt_secret
            verifier = decrypt_secret(pkce_row["access_token_enc"])
        else:
            verifier = ""

        client = self._get_http()
        data: Dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if verifier:
            data["code_verifier"] = verifier

        resp = await client.post(
            "https://identity.xero.com/connect/token",
            headers={"Authorization": self._basic_auth(),
                     "Content-Type": "application/x-www-form-urlencoded"},
            data=data,
        )
        resp.raise_for_status()
        token_data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=token_data.get("expires_in", 1800))).isoformat()
        self._store_token(
            token_data["access_token"],
            token_data.get("refresh_token"),
            expires_at,
            token_data.get("scope", "").split(),
        )
        # Fetch and cache Xero tenant (organisation) ID
        await self._cache_tenant_id(token_data["access_token"])
        return token_data

    async def refresh_access_token(self) -> str:
        tok = self._get_token()
        if not tok or not tok.get("refresh_token"):
            raise RuntimeError("No refresh token")
        client = self._get_http()
        resp = await client.post(
            "https://identity.xero.com/connect/token",
            headers={"Authorization": self._basic_auth(),
                     "Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "refresh_token",
                  "refresh_token": tok["refresh_token"]},
        )
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 1800))).isoformat()
        self._store_token(
            data["access_token"],
            data.get("refresh_token", tok["refresh_token"]),
            expires_at,
            tok.get("scopes", []),
        )
        return data["access_token"]

    async def _cache_tenant_id(self, access_token: str) -> str:
        client = self._get_http()
        resp = await client.get(
            XERO_CONNECTIONS,
            headers={"Authorization": f"Bearer {access_token}",
                     "Accept": "application/json"},
        )
        if resp.status_code == 200:
            connections = resp.json()
            if connections:
                tid = connections[0].get("tenantId", "")
                self.config["xero_tenant_id"] = tid
                self.db.execute(
                    "UPDATE connectors SET config_json=json_set(COALESCE(config_json,'{}'), '$.xero_tenant_id', ?) "
                    "WHERE id=?",
                    (tid, self.instance_id),
                )
                return tid
        return ""

    def _xero_headers(self, access_token: str) -> Dict:
        return {
            "Authorization": f"Bearer {access_token}",
            "Xero-Tenant-Id": self.config.get("xero_tenant_id", ""),
            "Accept": "application/json",
        }

    async def _xero_get(self, path: str, params: Optional[Dict] = None) -> Any:
        token = await self.get_valid_token()
        client = self._get_http()
        resp = await client.get(
            f"{XERO_API}/{path}",
            headers=self._xero_headers(token),
            params=params or {},
        )
        resp.raise_for_status()
        return resp.json()

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "invoices":
            return await self._sync_invoices(since)
        elif entity == "contacts":
            return await self._sync_contacts(since)
        elif entity == "payments":
            return await self._sync_payments(since)
        elif entity == "accounts":
            return await self._sync_accounts()
        return {"synced": 0, "entity": entity}

    async def _sync_invoices(self, since: Optional[datetime]) -> Dict:
        params: Dict[str, Any] = {"Status": "AUTHORISED,PAID,VOIDED", "page": 1}
        if since:
            params["modifiedAfter"] = since.strftime("%Y-%m-%dT%H:%M:%S")
        all_records: List[Dict] = []
        while True:
            data = await self._xero_get("Invoices", params)
            invoices = data.get("Invoices", [])
            all_records.extend(invoices)
            if len(invoices) < 100:
                break
            params["page"] = params["page"] + 1
        for r in all_records:
            self._upsert_invoice(r)
        self._publish_event("erp.sync.completed",
                            {"entity": "invoices", "count": len(all_records)})
        return {"synced": len(all_records), "entity": "invoices"}

    def _upsert_invoice(self, r: Dict) -> None:
        inv_num = r.get("InvoiceNumber", r.get("InvoiceID", ""))
        now = datetime.now(tz=timezone.utc).isoformat()
        xero_status = r.get("Status", "")
        status_map = {
            "DRAFT": "draft", "SUBMITTED": "draft",
            "AUTHORISED": "sent", "PAID": "paid",
            "VOIDED": "cancelled", "DELETED": "cancelled",
        }
        status = status_map.get(xero_status, "sent")
        existing = self.db.fetch_one(
            "SELECT id FROM erp_invoices WHERE invoice_number=? AND tenant_id=?",
            (inv_num, self.tenant_id),
        )
        if existing:
            self.db.execute(
                "UPDATE erp_invoices SET status=?, updated_at=? WHERE id=?",
                (status, now, existing["id"]),
            )
            if status == "paid":
                self._publish_event("invoice.paid",
                                    {"source": "xero", "invoice_number": inv_num})
        else:
            iid = f"inv_{uuid.uuid4().hex}"
            contact = r.get("Contact", {})
            amount = float(r.get("Total", 0) or 0)
            inv_date = (r.get("Date", "") or now)[:10]
            self.db.execute(
                """INSERT INTO erp_invoices
                   (id, tenant_id, invoice_number, vendor_id, status,
                    amount, total_amount, currency, invoice_date, due_date,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (iid, self.tenant_id, inv_num,
                 contact.get("ContactID", ""),
                 status, amount, amount,
                 r.get("CurrencyCode", "USD"),
                 inv_date,
                 (r.get("DueDate", "") or "")[:10] or None,
                 now, now),
            )
            self._publish_event("invoice.created",
                                {"source": "xero", "invoice_number": inv_num})

    async def _sync_contacts(self, since: Optional[datetime]) -> Dict:
        params: Dict[str, Any] = {"page": 1}
        if since:
            params["modifiedAfter"] = since.strftime("%Y-%m-%dT%H:%M:%S")
        all_records: List[Dict] = []
        while True:
            data = await self._xero_get("Contacts", params)
            contacts = data.get("Contacts", [])
            all_records.extend(contacts)
            if len(contacts) < 100:
                break
            params["page"] = params["page"] + 1
        for r in all_records:
            self._upsert_contact(r)
        return {"synced": len(all_records), "entity": "contacts"}

    def _upsert_contact(self, r: Dict) -> None:
        ext_id = r.get("ContactID", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        if not self.db.fetch_one(
            "SELECT id FROM crm_contacts WHERE external_id=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        ):
            cid = f"cnt_{uuid.uuid4().hex}"
            name = r.get("Name", "")
            parts = name.split(" ", 1)
            phones = r.get("Phones", [])
            phone = next((p.get("PhoneNumber", "") for p in phones
                          if p.get("PhoneType") == "DEFAULT"), "")
            emails = r.get("EmailAddress", "")
            self.db.execute(
                """INSERT INTO crm_contacts
                   (id, tenant_id, first_name, last_name, email, phone,
                    source, external_id, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,'xero',?,'active',?,?)""",
                (cid, self.tenant_id,
                 parts[0], parts[1] if len(parts) > 1 else "",
                 emails, phone, ext_id, now, now),
            )

    async def _sync_payments(self, since: Optional[datetime]) -> Dict:
        params: Dict[str, Any] = {}
        if since:
            params["modifiedAfter"] = since.strftime("%Y-%m-%dT%H:%M:%S")
        data = await self._xero_get("Payments", params)
        payments = data.get("Payments", [])
        for p in payments:
            inv = p.get("Invoice", {})
            if inv.get("InvoiceNumber"):
                self._publish_event("invoice.paid",
                                    {"source": "xero",
                                     "invoice_number": inv["InvoiceNumber"],
                                     "amount": p.get("Amount")})
        return {"synced": len(payments), "entity": "payments"}

    async def _sync_accounts(self) -> Dict:
        data = await self._xero_get("Accounts")
        accounts = data.get("Accounts", [])
        return {"synced": len(accounts), "entity": "accounts"}

    async def verify_webhook_signature(self, raw_body: bytes, headers: Dict) -> bool:
        sig = headers.get("x-xero-signature", "")
        if not sig:
            return False
        key = self.config.get("client_secret", "")
        if not key:
            return False
        expected = base64.b64encode(
            hmac.new(key.encode(), raw_body, hashlib.sha256).digest()
        ).decode()
        return hmac.compare_digest(sig, expected)

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                              raw_body: bytes, headers: Dict) -> None:
        for event in payload.get("events", []):
            resource_type = event.get("resourceType", "").lower()
            event_category = event.get("eventCategory", "").lower()
            self._publish_event(
                f"xero.{resource_type}.{event_category}",
                {"source": "xero", "resource_id": event.get("resourceId"),
                 "tenant_id": event.get("tenantId")},
            )
            if resource_type == "invoice" and event_category == "update":
                self._enqueue("sync", {"entity": "invoices"}, 0, 3)

    async def health_check(self) -> Dict[str, Any]:
        try:
            token = await self.get_valid_token()
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(
                XERO_CONNECTIONS,
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/json"},
            )
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code == 200
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1)}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
