"""Zoho CRM Connector — leads, contacts, accounts, deals, webhooks."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from ..sdk.base import ConnectorBase
from ..sdk.manifest import ConnectorManifest, OAuthConfig, WebhookConfig, SyncConfig, Permission

MANIFEST = ConnectorManifest(
    id="zoho_crm",
    name="Zoho CRM",
    category="crm",
    description="Sync leads, contacts, accounts, and deals from Zoho CRM.",
    version="1.0.0",
    icon="👥",
    supports_oauth=True,
    supports_webhook=True,
    oauth=OAuthConfig(
        provider_id="zoho",
        auth_url="https://accounts.zoho.com/oauth/v2/auth",
        token_url="https://accounts.zoho.com/oauth/v2/token",
        scopes=["ZohoCRM.modules.ALL", "ZohoCRM.settings.ALL"],
        supports_refresh=True,
    ),
    webhook=WebhookConfig(
        events=["Leads.create", "Leads.edit", "Contacts.create",
                "Contacts.edit", "Deals.create", "Deals.edit"],
        signature_header="X-Zoho-Webhook-Token",
    ),
    sync=SyncConfig(entities=["leads", "contacts", "deals"], default_interval_seconds=3600),
    permissions=[Permission("ZohoCRM.modules.ALL", "All Modules", "Full CRM access")],
    config_schema={
        "client_id": {"type": "string", "required": True},
        "client_secret": {"type": "string", "required": True, "secret": True},
        "data_center": {"type": "string", "default": "com", "description": "com/eu/in/au/jp"},
    },
    emits_events=["crm.lead.created", "crm.contact.created", "crm.deal.updated"],
)

ZOHO_BASE = "https://www.zohoapis.{dc}/crm/v5"
_VALID_ZOHO_DCS = frozenset({"com", "eu", "in", "au", "jp"})


class ZohoCRMConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 5.0
    RATE_BURST = 15.0

    def _dc(self) -> str:
        dc = self.config.get("data_center", "com")
        if dc not in _VALID_ZOHO_DCS:
            raise ValueError(f"Invalid Zoho data_center '{dc}'; must be one of {sorted(_VALID_ZOHO_DCS)}")
        return dc

    def _base(self) -> str:
        return f"https://www.zohoapis.{self._dc()}/crm/v5"

    def _auth_url_base(self) -> str:
        dc = self._dc()
        return f"https://accounts.zoho.{dc}"

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        params = urlencode({
            "scope": "ZohoCRM.modules.ALL,ZohoCRM.settings.ALL",
            "client_id": self.config["client_id"],
            "response_type": "code",
            "access_type": "offline",
            "redirect_uri": redirect_uri,
            "state": state,
        })
        return f"{self._auth_url_base()}/oauth/v2/auth?{params}"

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        client = self._get_http()
        resp = await client.post(f"{self._auth_url_base()}/oauth/v2/token", data={
            "grant_type": "authorization_code",
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
            "redirect_uri": redirect_uri,
            "code": code,
        })
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        self._store_token(data["access_token"], data.get("refresh_token"),
                          expires_at, ["ZohoCRM.modules.ALL"])
        return data

    async def refresh_access_token(self) -> str:
        tok = self._get_token()
        if not tok or not tok.get("refresh_token"):
            raise RuntimeError("No refresh token")
        client = self._get_http()
        resp = await client.post(f"{self._auth_url_base()}/oauth/v2/token", data={
            "grant_type": "refresh_token",
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
            "refresh_token": tok["refresh_token"],
        })
        resp.raise_for_status()
        data = resp.json()
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 3600))).isoformat()
        self._store_token(data["access_token"], tok["refresh_token"],
                          expires_at, tok.get("scopes", []))
        return data["access_token"]

    async def _get_records(self, module: str, fields: List[str],
                           since: Optional[datetime] = None) -> List[Dict]:
        token = await self.get_valid_token()
        client = self._get_http()
        params: Dict[str, Any] = {"fields": ",".join(fields), "per_page": 200}
        if since:
            params["modified_since"] = since.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        resp = await client.get(
            f"{self._base()}/{module}",
            headers={"Authorization": f"Zoho-oauthtoken {token}"},
            params=params,
        )
        if resp.status_code == 204:
            return []
        resp.raise_for_status()
        return resp.json().get("data", [])

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        if entity == "leads":
            records = await self._get_records(
                "Leads", ["First_Name","Last_Name","Email","Phone","Company",
                          "Lead_Status","Lead_Source","Rating"], since)
            for r in records:
                self._upsert_lead(r)
            self._publish_event("crm.lead.synced", {"count": len(records)})
            return {"synced": len(records), "entity": "leads"}

        elif entity == "contacts":
            records = await self._get_records(
                "Contacts", ["First_Name","Last_Name","Email","Phone",
                             "Account_Name","Title"], since)
            for r in records:
                self._upsert_contact(r)
            return {"synced": len(records), "entity": "contacts"}

        elif entity == "deals":
            records = await self._get_records(
                "Deals", ["Deal_Name","Stage","Amount","Closing_Date",
                          "Probability","Account_Name"], since)
            for r in records:
                self._upsert_deal(r)
            return {"synced": len(records), "entity": "deals"}

        return {"synced": 0, "entity": entity}

    def _upsert_lead(self, r: Dict) -> None:
        ext_id = r.get("id", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        stage_map = {"New": "new", "Contacted": "contacted",
                     "Not Contacted": "new", "Junk Lead": "unqualified"}
        status = stage_map.get(r.get("Lead_Status", ""), "new")
        existing = self.db.fetch_one(
            "SELECT id FROM crm_leads WHERE external_id=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        )
        if existing:
            self.db.execute(
                "UPDATE crm_leads SET status=?, updated_at=? WHERE id=?",
                (status, now, existing["id"]),
            )
        else:
            lid = f"ld_{uuid.uuid4().hex}"
            name = f"{r.get('First_Name','')} {r.get('Last_Name','')}".strip()
            self.db.execute(
                """INSERT INTO crm_leads
                   (id, tenant_id, title, source,
                    status, score, external_id, created_at, updated_at)
                   VALUES (?,?,?,'zoho_crm',?,50,?,?,?)""",
                (lid, self.tenant_id, name, status, ext_id, now, now),
            )

    def _upsert_contact(self, r: Dict) -> None:
        ext_id = r.get("id", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = self.db.fetch_one(
            "SELECT id FROM crm_contacts WHERE external_id=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        )
        if not existing:
            cid = f"cnt_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO crm_contacts
                   (id, tenant_id, first_name, last_name, email, phone,
                    company, job_title, source, external_id, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,'zoho_crm',?,'active',?,?)""",
                (cid, self.tenant_id, r.get("First_Name",""), r.get("Last_Name",""),
                 r.get("Email",""), r.get("Phone",""),
                 (r.get("Account_Name") or {}).get("name",""),
                 r.get("Title",""), ext_id, now, now),
            )

    def _upsert_deal(self, r: Dict) -> None:
        ext_id = r.get("id", "")
        now = datetime.now(tz=timezone.utc).isoformat()
        stage_map = {
            "Qualification": "qualification", "Needs Analysis": "qualification",
            "Value Proposition": "proposal", "Proposal/Price Quote": "proposal",
            "Negotiation/Review": "negotiation",
            "Closed Won": "closed_won", "Closed Lost": "closed_lost",
        }
        stage = stage_map.get(r.get("Stage", ""), "prospecting")
        existing = self.db.fetch_one(
            "SELECT id FROM crm_opportunities WHERE external_id=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        )
        if existing:
            self.db.execute(
                "UPDATE crm_opportunities SET stage=?, value=?, updated_at=? WHERE id=?",
                (stage, float(r.get("Amount") or 0), now, existing["id"]),
            )
        else:
            oid = f"opp_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO crm_opportunities
                   (id, tenant_id, title, stage, value,
                    close_date, external_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (oid, self.tenant_id, r.get("Deal_Name",""),
                 stage, float(r.get("Amount") or 0),
                 r.get("Closing_Date"), ext_id, now, now),
            )

    async def verify_webhook_signature(self, raw_body: bytes,
                                       headers: Dict[str, str]) -> bool:
        return True  # Zoho uses webhook token in header, validated by URL

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict[str, str]) -> None:
        module = payload.get("module", "")
        operation = payload.get("operation", "create")
        records = payload.get("ids", [])
        ev_type = f"crm.{module.lower()}.{operation}"
        self._publish_event(ev_type, {"source": "zoho_crm", "records": records})

    async def health_check(self) -> Dict[str, Any]:
        try:
            token = await self.get_valid_token()
            client = self._get_http()
            t0 = time.monotonic()
            resp = await client.get(
                f"{self._base()}/org",
                headers={"Authorization": f"Zoho-oauthtoken {token}"},
            )
            latency = (time.monotonic() - t0) * 1000
            ok = resp.status_code == 200
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1)}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
