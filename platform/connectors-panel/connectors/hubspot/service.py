"""HubSpot API v3 service layer."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode


class HubSpotAPI:
    BASE = "https://api.hubapi.com"
    AUTH_URL = "https://app.hubspot.com/oauth/authorize"
    TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"

    @staticmethod
    def get_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
        params = urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "contacts crm.objects.deals.read crm.objects.deals.write "
                     "crm.objects.contacts.read crm.objects.contacts.write",
            "state": state,
        })
        return f"{HubSpotAPI.AUTH_URL}?{params}"

    @staticmethod
    async def exchange_code(client, client_id: str, client_secret: str,
                            code: str, redirect_uri: str) -> Dict[str, Any]:
        resp = await client.post(HubSpotAPI.TOKEN_URL, data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        })
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def refresh_token(client, client_id: str, client_secret: str,
                            refresh_token: str) -> Dict[str, Any]:
        resp = await client.post(HubSpotAPI.TOKEN_URL, data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        })
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _h(token: str) -> Dict:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    @staticmethod
    async def get_contacts(client, token: str,
                           after: Optional[str] = None) -> Dict[str, Any]:
        params = {"limit": 100, "properties": "firstname,lastname,email,phone,company,jobtitle,hs_lead_status"}
        if after:
            params["after"] = after
        resp = await client.get(f"{HubSpotAPI.BASE}/crm/v3/objects/contacts",
                                headers=HubSpotAPI._h(token), params=params)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def get_deals(client, token: str,
                        after: Optional[str] = None) -> Dict[str, Any]:
        params = {"limit": 100,
                  "properties": "dealname,amount,dealstage,closedate,pipeline,hubspot_owner_id"}
        if after:
            params["after"] = after
        resp = await client.get(f"{HubSpotAPI.BASE}/crm/v3/objects/deals",
                                headers=HubSpotAPI._h(token), params=params)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def get_companies(client, token: str,
                            after: Optional[str] = None) -> Dict[str, Any]:
        params = {"limit": 100, "properties": "name,domain,industry,annualrevenue,numberofemployees"}
        if after:
            params["after"] = after
        resp = await client.get(f"{HubSpotAPI.BASE}/crm/v3/objects/companies",
                                headers=HubSpotAPI._h(token), params=params)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def create_contact(client, token: str, props: Dict) -> Dict:
        resp = await client.post(f"{HubSpotAPI.BASE}/crm/v3/objects/contacts",
                                 headers=HubSpotAPI._h(token),
                                 json={"properties": props})
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def update_contact(client, token: str, contact_id: str, props: Dict) -> Dict:
        resp = await client.patch(
            f"{HubSpotAPI.BASE}/crm/v3/objects/contacts/{contact_id}",
            headers=HubSpotAPI._h(token), json={"properties": props},
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def get_pipelines(client, token: str) -> Dict:
        resp = await client.get(f"{HubSpotAPI.BASE}/crm/v3/pipelines/deals",
                                headers=HubSpotAPI._h(token))
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def ping(client, token: str) -> bool:
        try:
            resp = await client.get(f"{HubSpotAPI.BASE}/crm/v3/objects/contacts?limit=1",
                                    headers=HubSpotAPI._h(token))
            return resp.status_code == 200
        except Exception:
            return False

    @staticmethod
    def verify_webhook(secret: str, raw_body: bytes, sig: str) -> bool:
        import hashlib, hmac as _hmac
        expected = _hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return _hmac.compare_digest(expected, sig.lstrip("sha256="))
