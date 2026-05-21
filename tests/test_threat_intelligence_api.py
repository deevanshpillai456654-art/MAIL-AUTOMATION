"""Tests for the threat intelligence API (blacklist, whitelist, stats, scan, lookalike)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth.local_auth import require_local_auth_or_localhost


@pytest.fixture
def client():
    from backend.api.threat_intelligence import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth_or_localhost] = lambda: None
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def test_stats_returns_structure(client):
    resp = client.get("/api/v1/threat/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    stats = body.get("stats", body)
    assert "blacklisted_entries" in stats or "blacklisted" in stats or "total_scanned" in stats


# ---------------------------------------------------------------------------
# Blacklist CRUD
# ---------------------------------------------------------------------------

def test_blacklist_initially_empty_or_returns_list(client):
    resp = client.get("/api/v1/threat/blacklist")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_add_domain_to_blacklist(client):
    payload = {
        "entry_type": "domain",
        "value": "evil-test-domain.example",
        "reason": "test",
        "threat_type": "phishing",
        "score": 90,
        "auto_block": True,
    }
    resp = client.post("/api/v1/threat/blacklist", json=payload)
    assert resp.status_code == 200
    assert resp.json().get("ok") is True


def test_add_sender_to_blacklist(client):
    payload = {"entry_type": "sender", "value": "spammer@evil.example"}
    resp = client.post("/api/v1/threat/blacklist", json=payload)
    assert resp.status_code == 200


def test_blacklist_entry_appears_in_list(client):
    client.post("/api/v1/threat/blacklist", json={
        "entry_type": "domain", "value": "findme.example", "score": 50,
    })
    resp = client.get("/api/v1/threat/blacklist")
    values = [item["value"] for item in resp.json()["items"]]
    assert "findme.example" in values


def test_blacklist_entry_type_filter(client):
    client.post("/api/v1/threat/blacklist", json={"entry_type": "domain", "value": "domain-only.example"})
    client.post("/api/v1/threat/blacklist", json={"entry_type": "sender", "value": "sender@only.example"})
    resp = client.get("/api/v1/threat/blacklist?entry_type=domain")
    for item in resp.json()["items"]:
        assert item["entry_type"] == "domain"


def test_delete_blacklist_entry(client):
    client.post("/api/v1/threat/blacklist", json={"entry_type": "domain", "value": "delete-me.example"})
    items = client.get("/api/v1/threat/blacklist").json()["items"]
    entry = next((i for i in items if i["value"] == "delete-me.example"), None)
    assert entry is not None, "Entry should exist after add"
    del_resp = client.delete(f"/api/v1/threat/blacklist/{entry['id']}")
    assert del_resp.status_code == 200
    remaining = [i["value"] for i in client.get("/api/v1/threat/blacklist").json()["items"]]
    assert "delete-me.example" not in remaining


def test_blacklist_rejects_invalid_entry_type(client):
    resp = client.post("/api/v1/threat/blacklist", json={
        "entry_type": "ip",  # not allowed
        "value": "1.2.3.4",
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Whitelist CRUD
# ---------------------------------------------------------------------------

def test_whitelist_returns_list(client):
    resp = client.get("/api/v1/threat/whitelist")
    assert resp.status_code == 200
    assert "items" in resp.json()


def test_add_domain_to_whitelist(client):
    resp = client.post("/api/v1/threat/whitelist", json={
        "entry_type": "domain", "value": "trusted.example", "reason": "partner",
    })
    assert resp.status_code == 200
    assert resp.json().get("ok") is True


def test_delete_whitelist_entry(client):
    client.post("/api/v1/threat/whitelist", json={"entry_type": "domain", "value": "removable-trusted.example"})
    items = client.get("/api/v1/threat/whitelist").json()["items"]
    entry = next((i for i in items if i["value"] == "removable-trusted.example"), None)
    assert entry is not None
    resp = client.delete(f"/api/v1/threat/whitelist/{entry['id']}")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Domain analysis
# ---------------------------------------------------------------------------

def test_domain_lookup_known_safe(client):
    resp = client.get("/api/v1/threat/domain/google.com")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    result = body.get("result", body)
    assert "domain" in result or "classification" in result


def test_domain_bulk_analysis(client):
    resp = client.post("/api/v1/threat/domain/bulk", json={"domains": ["google.com", "microsoft.com"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert "results" in body


# ---------------------------------------------------------------------------
# Lookalike monitoring
# ---------------------------------------------------------------------------

def test_lookalike_monitor_returns_list(client):
    resp = client.get("/api/v1/threat/lookalike/monitor")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert "alerts" in body


def test_lookalike_record(client):
    resp = client.post("/api/v1/threat/lookalike/record", json={
        "detected_domain": "g00gle.com",
        "impersonated_brand": "Google",
        "impersonated_domain": "google.com",
    })
    assert resp.status_code == 200


def test_lookalike_dismiss(client):
    # Record first
    rec = client.post("/api/v1/threat/lookalike/record", json={
        "detected_domain": "micosoft.com",
        "impersonated_brand": "Microsoft",
    })
    alert_id = rec.json().get("id") or rec.json().get("alert_id")
    if alert_id:
        resp = client.post(f"/api/v1/threat/lookalike/{alert_id}/dismiss")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def test_audit_log_returns_entries(client):
    client.post("/api/v1/threat/blacklist", json={"entry_type": "domain", "value": "audit-test.example"})
    resp = client.get("/api/v1/threat/audit")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert "items" in body


# ---------------------------------------------------------------------------
# Scan endpoint
# ---------------------------------------------------------------------------

def test_scan_clean_email(client):
    resp = client.post("/api/v1/threat/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert "scan_result" in body


def test_scan_returns_total_scanned(client):
    resp = client.post("/api/v1/threat/scan")
    assert resp.status_code == 200
    result = resp.json().get("scan_result", {})
    assert "total_scanned" in result
