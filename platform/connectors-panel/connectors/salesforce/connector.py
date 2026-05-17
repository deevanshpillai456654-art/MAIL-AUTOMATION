"""
Salesforce Connector — full OAuth2, contact/lead/opportunity sync,
webhook subscriptions, health checks.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from ..sdk.base import ConnectorBase
from ..sdk.manifest import (
    ConnectorManifest, OAuthConfig, WebhookConfig,
    SyncConfig, Permission, HealthCheck,
)
from .service import SalesforceAPI

MANIFEST = ConnectorManifest(
    id="salesforce",
    name="Salesforce CRM",
    category="crm",
    description="Sync contacts, leads, opportunities, and accounts from Salesforce.",
    version="1.0.0",
    author="MailPilot",
    icon="☁️",
    supports_oauth=True,
    supports_webhook=True,
    oauth=OAuthConfig(
        provider_id="salesforce",
        auth_url="https://login.salesforce.com/services/oauth2/authorize",
        token_url="https://login.salesforce.com/services/oauth2/token",
        scopes=["api", "refresh_token", "offline_access"],
        supports_refresh=True,
    ),
    webhook=WebhookConfig(
        events=["contact.created", "contact.updated",
                "lead.created", "lead.converted",
                "opportunity.created", "opportunity.updated",
                "opportunity.closed_won", "opportunity.closed_lost"],
        signature_header="X-Salesforce-Signature",
    ),
    sync=SyncConfig(
        entities=["contacts", "leads", "opportunities", "accounts"],
        default_interval_seconds=3600,
    ),
    health_checks=[HealthCheck("API Limits", "/services/data/v58.0/limits")],
    permissions=[
        Permission("api", "API Access", "Read/write Salesforce objects", True),
        Permission("offline_access", "Offline Access", "Refresh tokens without re-auth", True),
    ],
    config_schema={
        "client_id": {"type": "string", "required": True},
        "client_secret": {"type": "string", "required": True, "secret": True},
        "sandbox": {"type": "boolean", "default": False},
        "sync_interval": {"type": "integer", "default": 3600},
    },
    emits_events=[
        "salesforce.contact.synced", "salesforce.lead.synced",
        "salesforce.opportunity.synced", "salesforce.sync.completed",
        "salesforce.sync.failed",
    ],
)


class SalesforceConnector(ConnectorBase):
    MANIFEST = MANIFEST
    RATE_PER_SECOND = 5.0
    RATE_BURST = 15.0

    def _sf_client_creds(self):
        return (
            self.config.get("client_id", ""),
            self.config.get("client_secret", ""),
            self.config.get("sandbox", False),
        )

    async def get_auth_url(self, redirect_uri: str, state: str) -> str:
        client_id, _, sandbox = self._sf_client_creds()
        return await SalesforceAPI.get_auth_url(client_id, redirect_uri, state, sandbox)

    async def exchange_code(self, code: str, redirect_uri: str) -> Dict[str, Any]:
        client_id, client_secret, sandbox = self._sf_client_creds()
        client = self._get_http()
        data = await SalesforceAPI.exchange_code(
            client, client_id, client_secret, code, redirect_uri, sandbox
        )
        # SF returns: access_token, refresh_token, instance_url, issued_at
        expires_at = None
        if "issued_at" in data:
            from datetime import timezone as tz
            issued_ms = int(data["issued_at"])
            exp_ts = issued_ms / 1000 + 7200  # 2h default SF token life
            expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc).isoformat()

        self._store_token(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            scopes=["api", "refresh_token", "offline_access"],
        )
        # Store instance_url in config
        self.config["instance_url"] = data.get("instance_url", "")
        from ...shared.utils import encrypt_config
        self.db.execute(
            "UPDATE connectors SET config_json=? WHERE id=?",
            (encrypt_config(self.config), self.instance_id),
        )
        return data

    async def refresh_access_token(self) -> str:
        client_id, client_secret, sandbox = self._sf_client_creds()
        tok = self._get_token()
        if not tok or not tok.get("refresh_token"):
            raise RuntimeError("No refresh token available")
        client = self._get_http()
        data = await SalesforceAPI.refresh_token(
            client, client_id, client_secret, tok["refresh_token"], sandbox
        )
        expires_at = None
        if "issued_at" in data:
            exp_ts = int(data["issued_at"]) / 1000 + 7200
            expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc).isoformat()
        self._store_token(
            access_token=data["access_token"],
            refresh_token=tok["refresh_token"],
            expires_at=expires_at,
            scopes=tok.get("scopes", []),
        )
        return data["access_token"]

    def _instance_url(self) -> str:
        return self.config.get("instance_url", "https://na1.salesforce.com")

    async def sync(self, entity: str,
                   since: Optional[datetime] = None) -> Dict[str, Any]:
        access_token = await self.get_valid_token()
        client = self._get_http()
        instance_url = self._instance_url()

        if entity == "contacts":
            records = await SalesforceAPI.get_contacts(client, instance_url, access_token, since)
            self._upsert_crm_contacts(records)
            self._publish_event("salesforce.contact.synced", {"count": len(records)})
            return {"synced": len(records), "entity": "contacts"}

        elif entity == "leads":
            records = await SalesforceAPI.get_leads(client, instance_url, access_token, since)
            self._upsert_crm_leads(records)
            self._publish_event("salesforce.lead.synced", {"count": len(records)})
            return {"synced": len(records), "entity": "leads"}

        elif entity == "opportunities":
            records = await SalesforceAPI.get_opportunities(client, instance_url, access_token, since)
            self._upsert_crm_opportunities(records)
            self._publish_event("salesforce.opportunity.synced", {"count": len(records)})
            return {"synced": len(records), "entity": "opportunities"}

        elif entity == "accounts":
            records = await SalesforceAPI.get_accounts(client, instance_url, access_token, since)
            self._publish_event("salesforce.account.synced", {"count": len(records)})
            return {"synced": len(records), "entity": "accounts"}

        return {"synced": 0, "entity": entity, "error": "unknown entity"}

    def _upsert_crm_contacts(self, records: List[Dict]) -> None:
        import uuid as _uuid
        for rec in records:
            existing = self.db.fetch_one(
                "SELECT id FROM crm_contacts WHERE external_id=? AND tenant_id=?",
                (rec["Id"], self.tenant_id),
            )
            now = datetime.now(tz=timezone.utc).isoformat()
            if existing:
                self.db.execute(
                    """UPDATE crm_contacts SET
                       first_name=?, last_name=?, email=?, phone=?,
                       company=?, job_title=?, updated_at=?
                       WHERE id=?""",
                    (rec.get("FirstName", ""), rec.get("LastName", ""),
                     rec.get("Email", ""), rec.get("Phone", ""),
                     (rec.get("Account") or {}).get("Name", ""),
                     rec.get("Title", ""), now, existing["id"]),
                )
            else:
                cid = f"cnt_{_uuid.uuid4().hex}"
                self.db.execute(
                    """INSERT INTO crm_contacts
                       (id, tenant_id, first_name, last_name, email, phone,
                        company, job_title, source, external_id, status, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,'salesforce',?,?,?,?)""",
                    (cid, self.tenant_id,
                     rec.get("FirstName", ""), rec.get("LastName", ""),
                     rec.get("Email", ""), rec.get("Phone", ""),
                     (rec.get("Account") or {}).get("Name", ""),
                     rec.get("Title", ""), rec["Id"], "active", now, now),
                )

    def _upsert_crm_leads(self, records: List[Dict]) -> None:
        import uuid as _uuid
        for rec in records:
            existing = self.db.fetch_one(
                "SELECT id FROM crm_leads WHERE external_id=? AND tenant_id=?",
                (rec["Id"], self.tenant_id),
            )
            now = datetime.now(tz=timezone.utc).isoformat()
            status_map = {"Open - Not Contacted": "new", "Working - Contacted": "contacted",
                          "Closed - Converted": "qualified", "Closed - Not Converted": "unqualified"}
            status = status_map.get(rec.get("Status", ""), "new")
            if existing:
                self.db.execute(
                    "UPDATE crm_leads SET status=?, updated_at=? WHERE id=?",
                    (status, now, existing["id"]),
                )
            else:
                lid = f"ld_{_uuid.uuid4().hex}"
                self.db.execute(
                    """INSERT INTO crm_leads
                       (id, tenant_id, title, source,
                        status, score, external_id, created_at, updated_at)
                       VALUES (?,?,?,'salesforce',?,50,?,?,?)""",
                    (lid, self.tenant_id,
                     f"{rec.get('FirstName','')} {rec.get('LastName','')}".strip(),
                     status, rec["Id"], now, now),
                )

    def _upsert_crm_opportunities(self, records: List[Dict]) -> None:
        import uuid as _uuid
        stage_map = {
            "Prospecting": "prospecting", "Qualification": "qualification",
            "Needs Analysis": "qualification", "Value Proposition": "proposal",
            "Id. Decision Makers": "proposal", "Perception Analysis": "negotiation",
            "Proposal/Price Quote": "proposal", "Negotiation/Review": "negotiation",
            "Closed Won": "closed_won", "Closed Lost": "closed_lost",
        }
        for rec in records:
            existing = self.db.fetch_one(
                "SELECT id FROM crm_opportunities WHERE external_id=? AND tenant_id=?",
                (rec["Id"], self.tenant_id),
            )
            now = datetime.now(tz=timezone.utc).isoformat()
            stage = stage_map.get(rec.get("StageName", ""), "prospecting")
            if existing:
                self.db.execute(
                    """UPDATE crm_opportunities SET
                       stage=?, value=?, probability=?, updated_at=?
                       WHERE id=?""",
                    (stage, float(rec.get("Amount") or 0),
                     int(rec.get("Probability") or 0), now, existing["id"]),
                )
            else:
                oid = f"opp_{_uuid.uuid4().hex}"
                close = rec.get("CloseDate", "")
                self.db.execute(
                    """INSERT INTO crm_opportunities
                       (id, tenant_id, title, stage, value, probability,
                        close_date, external_id, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (oid, self.tenant_id, rec.get("Name", ""),
                     stage, float(rec.get("Amount") or 0),
                     int(rec.get("Probability") or 0),
                     close or None, rec["Id"], now, now),
                )

    async def verify_webhook_signature(self, raw_body: bytes,
                                       headers: Dict[str, str]) -> bool:
        secret = self.config.get("webhook_secret", "")
        if not secret:
            return False  # fail-closed: no secret means no verified webhooks
        sig = headers.get("X-Salesforce-Signature", "")
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    async def handle_webhook(self, event_type: str, payload: Dict[str, Any],
                             raw_body: bytes, headers: Dict[str, str]) -> None:
        sf_type = payload.get("sobjectType", "").lower()
        sf_id = payload.get("Id", "")

        if sf_type == "contact":
            self._publish_event("crm.contact.updated",
                                {"source": "salesforce", "id": sf_id, "data": payload})
        elif sf_type == "lead":
            self._publish_event("crm.lead.created",
                                {"source": "salesforce", "id": sf_id, "data": payload})
        elif sf_type == "opportunity":
            stage = payload.get("StageName", "")
            ev = "crm.opportunity.closed_won" if stage == "Closed Won" else "crm.opportunity.updated"
            self._publish_event(ev, {"source": "salesforce", "id": sf_id, "data": payload})

        self._log("INFO", f"Webhook processed: {event_type} / {sf_type} {sf_id}")

    async def health_check(self) -> Dict[str, Any]:
        try:
            access_token = await self.get_valid_token()
            client = self._get_http()
            instance_url = self._instance_url()
            t0 = time.monotonic()
            ok = await SalesforceAPI.ping(client, instance_url, access_token)
            latency = (time.monotonic() - t0) * 1000
            self._record_health(ok, latency)
            return {"healthy": ok, "latency_ms": round(latency, 1), "message": "API reachable"}
        except Exception as exc:
            self._record_health(False)
            return {"healthy": False, "latency_ms": None, "message": str(exc)}

    async def on_install(self) -> None:
        await super().on_install()
        self._log("INFO", "Salesforce connector installed. Authorize via OAuth to start syncing.")
