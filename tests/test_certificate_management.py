"""Tests for backend/api/certificate_management.py"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.certificate_management as cert_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "cert_test.db")
    monkeypatch.setattr(cert_mod, "_DB_PATH", db_path)
    cert_mod._init_db()

    app = FastAPI()
    app.include_router(cert_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _create(c, **kwargs):
    payload = {"name": "api.example.com TLS", **kwargs}
    r = c.post("/api/v1/certificates", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, cert_id, status, **kwargs):
    return c.post(f"/api/v1/certificates/{cert_id}/transition",
                  json={"status": status, **kwargs})


def _renew(c, cert_id, new_expires_at, **kwargs):
    return c.post(f"/api/v1/certificates/{cert_id}/renew",
                  json={"new_expires_at": new_expires_at, **kwargs})


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    exp = _future(365)
    d = _create(c, name="api.example.com", domain="api.example.com",
                issuer="Let's Encrypt", type="ssl", environment="production",
                expires_at=exp, owner="infra-team", auto_renew=True)
    cert_id = d["id"]
    assert d["status"] == "pending"

    r = c.get(f"/api/v1/certificates/{cert_id}")
    assert r.status_code == 200
    cert = r.json()
    assert cert["name"] == "api.example.com"
    assert cert["domain"] == "api.example.com"
    assert cert["issuer"] == "Let's Encrypt"
    assert cert["type"] == "ssl"
    assert cert["status"] == "pending"
    assert cert["auto_renew"] == 1
    assert cert["days_until_expiry"] == 365


def test_create_defaults(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.get(f"/api/v1/certificates/{d['id']}").json()
    assert r["type"] == "ssl"
    assert r["environment"] == "production"
    assert r["status"] == "pending"
    assert r["auto_renew"] == 0
    assert r["days_until_expiry"] is None


def test_days_until_expiry_computed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, expires_at=_future(90))
    r = c.get(f"/api/v1/certificates/{d['id']}").json()
    assert r["days_until_expiry"] == 90


def test_days_until_expiry_negative_for_expired(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    past = (date.today() - timedelta(days=10)).isoformat()
    d = _create(c, expires_at=past)
    r = c.get(f"/api/v1/certificates/{d['id']}").json()
    assert r["days_until_expiry"] == -10


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="A")
    _create(c, name="B")
    r = c.get("/api/v1/certificates")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    _create(c, name="B")
    _transition(c, d1["id"], "active")
    r = c.get("/api/v1/certificates?status=active")
    assert r.json()["total"] == 1
    assert r.json()["certificates"][0]["id"] == d1["id"]


def test_list_filter_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="A", type="ssl")
    _create(c, name="B", type="wildcard")
    r = c.get("/api/v1/certificates?type=wildcard")
    assert r.json()["total"] == 1


def test_list_filter_by_environment(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="A", environment="production")
    _create(c, name="B", environment="staging")
    r = c.get("/api/v1/certificates?environment=staging")
    assert r.json()["total"] == 1


def test_list_search_by_domain(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="API cert", domain="api.example.com")
    _create(c, name="Web cert", domain="www.example.com")
    r = c.get("/api/v1/certificates?q=api")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, name=f"Cert {i}")
    r = c.get("/api/v1/certificates?limit=3&offset=0")
    assert len(r.json()["certificates"]) == 3
    r2 = c.get("/api/v1/certificates?limit=3&offset=3")
    assert len(r2.json()["certificates"]) == 2


def test_list_includes_days_until_expiry(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, expires_at=_future(60))
    r = c.get("/api/v1/certificates").json()["certificates"][0]
    assert "days_until_expiry" in r
    assert r["days_until_expiry"] == 60


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.patch(f"/api/v1/certificates/{d['id']}", json={
        "domain": "new.example.com", "owner": "cert-team", "auto_renew": True
    })
    assert r.status_code == 200
    cert = c.get(f"/api/v1/certificates/{d['id']}").json()
    assert cert["domain"] == "new.example.com"
    assert cert["owner"] == "cert-team"
    assert cert["auto_renew"] == 1


def test_delete_removes_certificate(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/certificates/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/certificates/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/certificates/no-id").status_code == 404


def test_invalid_type_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/certificates", json={"name": "X", "type": "token"})
    assert r.status_code == 400


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_pending_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200
    assert c.get(f"/api/v1/certificates/{d['id']}").json()["status"] == "active"


def test_transition_pending_to_cancelled(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "cancelled")
    assert r.status_code == 200


def test_transition_active_to_expiring(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "expiring")
    assert r.status_code == 200


def test_transition_active_to_revoked(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "revoked")
    assert r.status_code == 200


def test_transition_active_to_archived(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "archived")
    assert r.status_code == 200


def test_transition_expiring_to_expired(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "expiring")
    r = _transition(c, d["id"], "expired")
    assert r.status_code == 200
    assert c.get(f"/api/v1/certificates/{d['id']}").json()["status"] == "expired"


def test_transition_expired_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "expiring")
    _transition(c, d["id"], "expired")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200


def test_revoked_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "revoked")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 400


def test_cancelled_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "cancelled")
    r = _transition(c, d["id"], "pending")
    assert r.status_code == 400


def test_archived_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "archived")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 400


def test_invalid_transition_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "expired")
    assert r.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "deleted")
    assert r.status_code == 400


def test_transition_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-id", "active")
    assert r.status_code == 404


# ── Renew ──────────────────────────────────────────────────────────────────────

def test_renew_updates_expiry_and_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    old_exp = _future(10)
    new_exp = _future(375)
    d = _create(c, expires_at=old_exp)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "expiring")
    r = _renew(c, d["id"], new_exp, renewed_by="certbot", notes="Auto-renewed")
    assert r.status_code == 201
    assert r.json()["old_expires_at"] == old_exp
    assert r.json()["new_expires_at"] == new_exp
    assert r.json()["status"] == "active"
    cert = c.get(f"/api/v1/certificates/{d['id']}").json()
    assert cert["expires_at"] == new_exp
    assert cert["status"] == "active"
    assert cert["days_until_expiry"] == 375


def test_renew_logs_renewal_record(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, expires_at=_future(30))
    _renew(c, d["id"], _future(395), renewed_by="certbot")
    rens = c.get(f"/api/v1/certificates/{d['id']}/renewals").json()["renewals"]
    assert len(rens) == 1
    assert rens[0]["renewed_by"] == "certbot"


def test_multiple_renewals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, expires_at=_future(30))
    _renew(c, d["id"], _future(395))
    _renew(c, d["id"], _future(760))
    rens = c.get(f"/api/v1/certificates/{d['id']}/renewals").json()["renewals"]
    assert len(rens) == 2


def test_renew_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _renew(c, "no-id", _future(365))
    assert r.status_code == 404


# ── Expiring ──────────────────────────────────────────────────────────────────

def test_expiring_returns_near_expiry(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="Soon",    expires_at=_future(20))
    d2 = _create(c, name="Later",   expires_at=_future(200))
    _transition(c, d1["id"], "active")
    _transition(c, d2["id"], "active")
    r = c.get("/api/v1/certificates/expiring?days=30")
    assert r.status_code == 200
    ids = [cert["id"] for cert in r.json()["certificates"]]
    assert d1["id"] in ids
    assert d2["id"] not in ids


def test_expiring_excludes_revoked_and_archived(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, expires_at=_future(5))
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "revoked")
    r = c.get("/api/v1/certificates/expiring?days=30")
    ids = [cert["id"] for cert in r.json()["certificates"]]
    assert d["id"] not in ids


# ── Cascade delete ────────────────────────────────────────────────────────────

def test_delete_cascades_renewals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, expires_at=_future(30))
    cert_id = d["id"]
    _renew(c, cert_id, _future(395))
    _renew(c, cert_id, _future(760))
    c.delete(f"/api/v1/certificates/{cert_id}")
    con = sqlite3.connect(cert_mod._DB_PATH)
    count = con.execute(
        "SELECT COUNT(*) FROM cert_renewals WHERE cert_id=?", (cert_id,)
    ).fetchone()[0]
    con.close()
    assert count == 0


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/certificates/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 0
    assert s["active"] == 0
    assert s["expired"] == 0
    assert s["revoked"] == 0
    assert s["auto_renew"] == 0


def test_stats_counts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A", auto_renew=True)
    d2 = _create(c, name="B", auto_renew=True)
    d3 = _create(c, name="C")
    _transition(c, d1["id"], "active")
    _transition(c, d2["id"], "active")
    s = c.get("/api/v1/certificates/stats").json()
    assert s["total"] == 3
    assert s["active"] == 2
    assert s["auto_renew"] == 2


def test_stats_expiring_30(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, expires_at=_future(15))
    d2 = _create(c, expires_at=_future(200))
    _transition(c, d1["id"], "active")
    _transition(c, d2["id"], "active")
    s = c.get("/api/v1/certificates/stats").json()
    assert s["expiring_30"] == 1


def test_stats_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="A", type="ssl")
    _create(c, name="B", type="ssl")
    _create(c, name="C", type="wildcard")
    s = c.get("/api/v1/certificates/stats").json()
    types = {row["type"]: row["count"] for row in s["by_type"]}
    assert types["ssl"] == 2
    assert types["wildcard"] == 1
