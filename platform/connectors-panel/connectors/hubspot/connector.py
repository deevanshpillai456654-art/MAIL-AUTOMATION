"""HubSpot CRM Connector — OAuth2, contacts/deals/companies sync, webhooks."""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..sdk.base import ConnectorBase
from ..sdk.manifest import (
    ConnectorManifest, OAuthConfig, WebhookConfig,
    SyncConfig, Permission, HealthCheck,
)
from .service import HubSpotAPI

MANIFEST = ConnectorManifest(
    id="hubspot",
    name="HubSpot CRM",
    category="crm",
    description="Sync contacts, deals, companies, and notes from HubSpot.",
    version="1.0.0",
    icon="🟠",
    supports_oauth=True,
    supports_webhook=True,
    oauth=OAuthConfig(
        provider_id="hubspot",
        auth_url="https://app.hubspot.com/oauth/authorize",
        token_url="https://api.hubapi.com/oauth/v1/token",
        scopes=["contacts", "crm.objects.deals.read", "crm.objects.deals.write",
                "crm.objects.contacts.read", "crm.objects.contacts.write"],
        supports_refresh=True,
    ),
    webhook=WebhookConfig(
        events=["contact.creation", "contact.propertyChange",
                "deal.creation", "deal.propertyChange",
                "deal.deletion"],
        signature_header="X-HubSpot-Signature",
    ),
    sync=SyncConfig(
        entities=["contacts", "deals", "companies"],
        default_interval_seconds=1800,
    ),
    permissions=[
        Permission("contacts", "Contacts", "Read/write contacts"),
        Permission("crm.objects.deals.read", "Deals Read", "Read deals"),
        Permission("crm.objects.deals.write", "Deals Write", "Write deals"),
    ],
    config_schema={
        "client_id": {"type": "string", "required": True},
        "client_secret": {"type": "string", "required": True, "secret": True},
        "webhook_secret": {"type": "string", "required": False, "secret": True},
    },
    emits_events=["hubspot.contact.synced", "hubspot.deal.synced",
                  "crm.contact.created", "crm.deal.updated"],
)


class HubSpotConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 8.0
    RATE_BURST = 20.0

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        return HubSpotAPI.get_auth_url(self.config["client_id"], redirect_uri, state)

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        client = self._get_http()
        data = await HubSpotAPI.exchange_code(
            client, self.config["client_id"], self.config["client_secret"],
            code, redirect_uri,
        )
        expires_at = None
        if data.get("expires_in"):
            from datetime import timedelta
            expires_at = (datetime.now(tz=timezone.utc) +
                          timedelta(seconds=data["expires_in"])).isoformat()
        self._store_token(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scopes=data.get("scope", "").split(" "),
        )
        return data

    async def refresh_access_token(self) -> str:
        tok = self._get_token()
        if not tok or not tok.get("refresh_token"):
            raise RuntimeError("No refresh token")
        client = self._get_http()
        data = await HubSpotAPI.refresh_token(
            client, self.config["client_id"], self.config["client_secret"],
            tok["refresh_token"],
        )
        from datetime import timedelta
        expires_at = (datetime.now(tz=timezone.utc) +
                      timedelta(seconds=data.get("expires_in", 1800))).isoformat()
        self._store_token(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", tok["refresh_token"]),
            expires_at=expires_at,
            scopes=tok.get("scopes", []),
        )
        return data["access_token"]

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        token = await self.get_valid_token()
        client = self._get_http()
        total = 0

        if entity == "contacts":
            after = None
            while True:
                data = await HubSpotAPI.get_contacts(client, token, after)
                results = data.get("results", [])
                for r in results:
                    self._upsert_contact(r)
                total += len(results)
                paging = data.get("paging", {})
                after = paging.get("next", {}).get("after")
                if not after:
                    break
            self._publish_event("hubspot.contact.synced", {"count": total})
            return {"synced": total, "entity": "contacts"}

        elif entity == "deals":
            after = None
            while True:
                data = await HubSpotAPI.get_deals(client, token, after)
                results = data.get("results", [])
                for r in results:
                    self._upsert_deal(r)
                total += len(results)
                paging = data.get("paging", {})
                after = paging.get("next", {}).get("after")
                if not after:
                    break
            self._publish_event("hubspot.deal.synced", {"count": total})
            return {"synced": total, "entity": "deals"}

        elif entity == "companies":
            after = None
            while True:
                data = await HubSpotAPI.get_companies(client, token, after)
                results = data.get("results", [])
                total += len(results)
                paging = data.get("paging", {})
                after = paging.get("next", {}).get("after")
                if not after:
                    break
            return {"synced": total, "entity": "companies"}

        return {"synced": 0, "entity": entity}

    def _upsert_contact(self, r: Dict) -> None:
        props = r.get("properties", {})
        ext_id = r["id"]
        now = datetime.now(tz=timezone.utc).isoformat()
        existing = self.db.fetch_one(
            "SELECT contact_id FROM crm_contacts WHERE external_id=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        )
        if existing:
            self.db.execute(
                """UPDATE crm_contacts SET
                   first_name=?, last_name=?, email=?, company=?, job_title=?, updated_at=?
                   WHERE contact_id=?""",
                (props.get("firstname", ""), props.get("lastname", ""),
                 props.get("email", ""), props.get("company", ""),
                 props.get("jobtitle", ""), now, existing["contact_id"]),
            )
        else:
            cid = f"cnt_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO crm_contacts
                   (contact_id, tenant_id, first_name, last_name, email, company, job_title,
                    source, external_id, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,'hubspot',?,'active',?,?)""",
                (cid, self.tenant_id,
                 props.get("firstname", ""), props.get("lastname", ""),
                 props.get("email", ""), props.get("company", ""),
                 props.get("jobtitle", ""), ext_id, now, now),
            )

    def _upsert_deal(self, r: Dict) -> None:
        props = r.get("properties", {})
        ext_id = r["id"]
        now = datetime.now(tz=timezone.utc).isoformat()
        stage_map = {
            "appointmentscheduled": "prospecting",
            "qualifiedtobuy": "qualification",
            "presentationscheduled": "proposal",
            "decisionmakerboughtin": "negotiation",
            "contractsent": "negotiation",
            "closedwon": "closed_won",
            "closedlost": "closed_lost",
        }
        stage = stage_map.get(props.get("dealstage", "").lower(), "prospecting")
        existing = self.db.fetch_one(
            "SELECT opportunity_id FROM crm_opportunities WHERE external_id=? AND tenant_id=?",
            (ext_id, self.tenant_id),
        )
        if existing:
            self.db.execute(
                "UPDATE crm_opportunities SET stage=?, value=?, updated_at=? WHERE opportunity_id=?",
                (stage, props.get("amount"), now, existing["opportunity_id"]),
            )
        else:
            oid = f"opp_{uuid.uuid4().hex}"
            self.db.execute(
                """INSERT INTO crm_opportunities
                   (opportunity_id, tenant_id, title, stage, value, close_date,
                    external_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (oid, self.tenant_id, props.get("dealname", ""),
                 stage, props.get("amount"),
                 props.get("closedate", "")[:10] if props.get("closedate") else None,
                 ext_id, now, now),
            )

    async def verify_webhook_signature(self, raw_body: bytes,
                                       headers: Dict[str, str]) -> bool:
        secret = self.config.get("webhook_secret", "")
        if not secret:
            return True
        sig = headers.get("X-HubSpot-Signature", "")
        return HubSpotAPI.verify_webhook(secret, raw_body, sig)

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict[str, str]) -> None:
        events = payload if isinstance(payload, list) else [payload]
        for ev in events:
            obj_type = ev.get("subscriptionType", "")
            obj_id = str(ev.get("objectId", ""))
            if "contact" in obj_type:
                self._publish_event("crm.contact.updated",
                                    {"source": "hubspot", "id": obj_id})
            elif "deal" in obj_type:
                self._publish_event("crm.deal.updated",
                                    {"source": "hubspot", "id": obj_id})

    async def health_check(self) -> Dict[str, Any]:
        try:
            token = await self.get_valid_token()
            client = self._get_http()
            t0 = time.monotonic()
            ok = await HubSpotAPI.ping(client, token)
            latency = (time.monotonic() - t0) * 1000
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1), "message": "API reachable"}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}
