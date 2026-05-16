"""
Salesforce REST API service.
Handles authentication, token refresh, and all REST/SOQL calls.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode


class SalesforceAPI:
    """
    Thin async wrapper around the Salesforce REST API.
    All methods accept an httpx.AsyncClient and a valid access_token.
    """

    API_VERSION = "v58.0"

    @staticmethod
    def data_url(instance_url: str) -> str:
        return f"{instance_url}/services/data/{SalesforceAPI.API_VERSION}"

    @staticmethod
    async def get_auth_url(client_id: str, redirect_uri: str, state: str,
                           sandbox: bool = False) -> str:
        base = "https://test.salesforce.com" if sandbox else "https://login.salesforce.com"
        params = urlencode({
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "api refresh_token offline_access",
        })
        return f"{base}/services/oauth2/authorize?{params}"

    @staticmethod
    async def exchange_code(client, client_id: str, client_secret: str,
                            code: str, redirect_uri: str,
                            sandbox: bool = False) -> Dict[str, Any]:
        base = "https://test.salesforce.com" if sandbox else "https://login.salesforce.com"
        resp = await client.post(
            f"{base}/services/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def refresh_token(client, client_id: str, client_secret: str,
                            refresh_token: str, sandbox: bool = False) -> Dict[str, Any]:
        base = "https://test.salesforce.com" if sandbox else "https://login.salesforce.com"
        resp = await client.post(
            f"{base}/services/oauth2/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _auth_headers(access_token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    @staticmethod
    async def query(client, instance_url: str, access_token: str,
                    soql: str) -> List[Dict[str, Any]]:
        """Execute a SOQL query and return all records (handles pagination)."""
        from urllib.parse import quote
        url = f"{SalesforceAPI.data_url(instance_url)}/query?q={quote(soql)}"
        records: List[Dict] = []
        while url:
            resp = await client.get(url, headers=SalesforceAPI._auth_headers(access_token))
            resp.raise_for_status()
            data = resp.json()
            records.extend(data.get("records", []))
            next_url = data.get("nextRecordsUrl")
            url = f"{instance_url}{next_url}" if next_url else None
        return records

    @staticmethod
    async def get_contacts(client, instance_url: str, access_token: str,
                           since: Optional[datetime] = None) -> List[Dict]:
        where = ""
        if since:
            where = f"WHERE LastModifiedDate >= {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        soql = (
            f"SELECT Id,FirstName,LastName,Email,Phone,Account.Name,"
            f"Title,Department,LeadSource,LastModifiedDate "
            f"FROM Contact {where} ORDER BY LastModifiedDate DESC LIMIT 1000"
        )
        return await SalesforceAPI.query(client, instance_url, access_token, soql)

    @staticmethod
    async def get_leads(client, instance_url: str, access_token: str,
                        since: Optional[datetime] = None) -> List[Dict]:
        where = ""
        if since:
            where = f"WHERE LastModifiedDate >= {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        soql = (
            f"SELECT Id,FirstName,LastName,Email,Phone,Company,Status,"
            f"LeadSource,Rating,LastModifiedDate "
            f"FROM Lead {where} ORDER BY LastModifiedDate DESC LIMIT 1000"
        )
        return await SalesforceAPI.query(client, instance_url, access_token, soql)

    @staticmethod
    async def get_opportunities(client, instance_url: str, access_token: str,
                                since: Optional[datetime] = None) -> List[Dict]:
        where = ""
        if since:
            where = f"WHERE LastModifiedDate >= {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        soql = (
            f"SELECT Id,Name,AccountId,Amount,CloseDate,StageName,"
            f"Probability,LeadSource,LastModifiedDate "
            f"FROM Opportunity {where} ORDER BY LastModifiedDate DESC LIMIT 1000"
        )
        return await SalesforceAPI.query(client, instance_url, access_token, soql)

    @staticmethod
    async def get_accounts(client, instance_url: str, access_token: str,
                           since: Optional[datetime] = None) -> List[Dict]:
        where = ""
        if since:
            where = f"WHERE LastModifiedDate >= {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        soql = (
            f"SELECT Id,Name,Website,Industry,AnnualRevenue,"
            f"NumberOfEmployees,Phone,LastModifiedDate "
            f"FROM Account {where} ORDER BY LastModifiedDate DESC LIMIT 1000"
        )
        return await SalesforceAPI.query(client, instance_url, access_token, soql)

    @staticmethod
    async def create_contact(client, instance_url: str, access_token: str,
                             data: Dict[str, Any]) -> Dict:
        resp = await client.post(
            f"{SalesforceAPI.data_url(instance_url)}/sobjects/Contact",
            headers={**SalesforceAPI._auth_headers(access_token), "Content-Type": "application/json"},
            json=data,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    async def update_record(client, instance_url: str, access_token: str,
                            sobject: str, record_id: str, data: Dict) -> None:
        resp = await client.patch(
            f"{SalesforceAPI.data_url(instance_url)}/sobjects/{sobject}/{record_id}",
            headers={**SalesforceAPI._auth_headers(access_token), "Content-Type": "application/json"},
            json=data,
        )
        resp.raise_for_status()

    @staticmethod
    async def subscribe_to_topics(client, instance_url: str, access_token: str,
                                  topics: List[str]) -> Dict:
        """Register change-data-capture event channels via Streaming API."""
        results = {}
        for topic in topics:
            resp = await client.post(
                f"{SalesforceAPI.data_url(instance_url)}/sobjects/PushTopic",
                headers={**SalesforceAPI._auth_headers(access_token), "Content-Type": "application/json"},
                json={
                    "Name": topic.replace("/", "_"),
                    "Query": f"SELECT Id FROM {topic.split('/')[-1]}",
                    "ApiVersion": 58.0,
                    "NotifyForOperationCreate": True,
                    "NotifyForOperationUpdate": True,
                    "NotifyForOperationDelete": True,
                },
            )
            results[topic] = resp.status_code < 300
        return results

    @staticmethod
    async def ping(client, instance_url: str, access_token: str) -> bool:
        try:
            resp = await client.get(
                f"{SalesforceAPI.data_url(instance_url)}/limits",
                headers=SalesforceAPI._auth_headers(access_token),
            )
            return resp.status_code == 200
        except Exception:
            return False
