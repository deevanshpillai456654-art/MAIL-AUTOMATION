"""Tests for backend/api/license_management.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.license_management as lm_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "lic_test.db")
    monkeypatch.setattr(lm_mod, "_DB_PATH", db_path)
    lm_mod._init_db()

    app = FastAPI()
    app.include_router(lm_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"name": "Jira Software Cloud", **kwargs}
    r = c.post("/api/v1/licenses", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, lic_id, status, **kwargs):
    return c.post(f"/api/v1/licenses/{lic_id}/transition",
                  json={"status": status, **kwargs})


def _assign(c, lic_id, **kwargs):
    return c.post(f"/api/v1/licenses/{lic_id}/assignments",
                  json={"user": "alice", **kwargs})


def _renew(c, lic_id, **kwargs):
    return c.post(f"/api/v1/licenses/{lic_id}/renewals",
                  json={"amount": 1000.0, **kwargs})


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="GitHub Enterprise", product="GitHub",
                vendor="Microsoft", type="enterprise", seats_total=100,
                cost=21000.0, currency="USD", owner="devops")
    lic_id = d["id"]
    assert d["status"] == "draft"

    r = c.get(f"/api/v1/licenses/{lic_id}")
    assert r.status_code == 200
    l = r.json()
    assert l["name"] == "GitHub Enterprise"
    assert l["product"] == "GitHub"
    assert l["vendor"] == "Microsoft"
    assert l["type"] == "enterprise"
    assert l["seats_total"] == 100
    assert l["seats_used"] == 0
    assert l["seats_available"] == 100
    assert l["utilization_pct"] == 0.0
    assert l["cost"] == 21000.0
    assert l["status"] == "draft"


def test_create_defaults(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.get(f"/api/v1/licenses/{d['id']}").json()
    assert r["type"] == "subscription"
    assert r["currency"] == "USD"
    assert r["seats_total"] == 0
    assert r["seats_used"] == 0
    assert r["cost"] == 0.0


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="License A")
    _create(c, name="License B")
    r = c.get("/api/v1/licenses")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    _create(c, name="B")
    _transition(c, d1["id"], "active")
    r = c.get("/api/v1/licenses?status=active")
    assert r.json()["total"] == 1
    assert r.json()["licenses"][0]["id"] == d1["id"]


def test_list_filter_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="A", type="perpetual")
    _create(c, name="B", type="subscription")
    r = c.get("/api/v1/licenses?type=perpetual")
    assert r.json()["total"] == 1


def test_list_search(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Jira Cloud", vendor="Atlassian")
    _create(c, name="Slack", vendor="Salesforce")
    r = c.get("/api/v1/licenses?q=atlassian")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, name=f"Lic {i}")
    r = c.get("/api/v1/licenses?limit=3&offset=0")
    assert len(r.json()["licenses"]) == 3
    r2 = c.get("/api/v1/licenses?limit=3&offset=3")
    assert len(r2.json()["licenses"]) == 2


def test_list_includes_enriched_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, seats_total=10)
    r = c.get("/api/v1/licenses").json()["licenses"][0]
    assert "seats_available" in r
    assert "utilization_pct" in r


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Old")
    r = c.patch(f"/api/v1/licenses/{d['id']}", json={
        "name": "New Name", "vendor": "ACME", "cost": 9999.0
    })
    assert r.status_code == 200
    l = c.get(f"/api/v1/licenses/{d['id']}").json()
    assert l["name"] == "New Name"
    assert l["vendor"] == "ACME"
    assert l["cost"] == 9999.0


def test_patch_returns_enriched(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, seats_total=10)
    _transition(c, d["id"], "active")
    _assign(c, d["id"], user="user1")
    r = c.patch(f"/api/v1/licenses/{d['id']}", json={"owner": "updated"})
    assert r.status_code == 200
    l = r.json()
    assert l["seats_used"] == 1
    assert l["seats_available"] == 9
    assert l["utilization_pct"] == 10.0


def test_delete_removes_license(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/licenses/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/licenses/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/licenses/no-id").status_code == 404


def test_invalid_type_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/licenses", json={"name": "X", "type": "freemium"})
    assert r.status_code == 400


def test_negative_seats_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/licenses", json={"name": "X", "seats_total": -1})
    assert r.status_code == 422


def test_negative_cost_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/licenses", json={"name": "X", "cost": -100.0})
    assert r.status_code == 422


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_draft_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200
    assert c.get(f"/api/v1/licenses/{d['id']}").json()["status"] == "active"


def test_transition_draft_to_cancelled(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "cancelled")
    assert r.status_code == 200


def test_transition_active_to_expired(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "expired")
    assert r.status_code == 200
    assert c.get(f"/api/v1/licenses/{d['id']}").json()["status"] == "expired"


def test_transition_expired_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "expired")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200


def test_transition_active_to_suspended(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "suspended")
    assert r.status_code == 200


def test_transition_suspended_back_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "suspended")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200


def test_terminated_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "terminated")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 400


def test_cancelled_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "cancelled")
    r = _transition(c, d["id"], "draft")
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


# ── Seat assignments ──────────────────────────────────────────────────────────

def test_add_and_list_assignments(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, seats_total=10)
    r = _assign(c, d["id"], user="alice", email="alice@example.com",
                assigned_date="2026-01-01")
    assert r.status_code == 201
    asns = c.get(f"/api/v1/licenses/{d['id']}/assignments").json()["assignments"]
    assert len(asns) == 1
    assert asns[0]["user"] == "alice"
    assert asns[0]["email"] == "alice@example.com"


def test_assignment_increments_seats_used(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, seats_total=10)
    _assign(c, d["id"], user="alice")
    _assign(c, d["id"], user="bob")
    l = c.get(f"/api/v1/licenses/{d['id']}").json()
    assert l["seats_used"] == 2
    assert l["seats_available"] == 8
    assert l["utilization_pct"] == 20.0


def test_delete_assignment_decrements_seats_used(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, seats_total=10)
    _assign(c, d["id"], user="alice")
    _assign(c, d["id"], user="bob")
    asns = c.get(f"/api/v1/licenses/{d['id']}/assignments").json()["assignments"]
    asn_id = asns[0]["id"]
    dr = c.delete(f"/api/v1/licenses/{d['id']}/assignments/{asn_id}")
    assert dr.status_code in (200, 204)
    l = c.get(f"/api/v1/licenses/{d['id']}").json()
    assert l["seats_used"] == 1


def test_assignment_wrong_license_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="L1")
    d2 = _create(c, name="L2")
    _assign(c, d1["id"], user="alice")
    asn_id = c.get(f"/api/v1/licenses/{d1['id']}/assignments").json()["assignments"][0]["id"]
    r = c.delete(f"/api/v1/licenses/{d2['id']}/assignments/{asn_id}")
    assert r.status_code == 404


def test_assignment_on_nonexistent_license_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _assign(c, "no-id", user="alice")
    assert r.status_code == 404


# ── Renewals ──────────────────────────────────────────────────────────────────

def test_add_and_list_renewals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _renew(c, d["id"], amount=5000.0, renewal_date="2026-06-01",
               author="finance", notes="Annual renewal")
    assert r.status_code == 201
    rens = c.get(f"/api/v1/licenses/{d['id']}/renewals").json()["renewals"]
    assert len(rens) == 1
    assert rens[0]["amount"] == 5000.0
    assert rens[0]["author"] == "finance"


def test_multiple_renewals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _renew(c, d["id"], amount=1000.0)
    _renew(c, d["id"], amount=1100.0)
    rens = c.get(f"/api/v1/licenses/{d['id']}/renewals").json()["renewals"]
    assert len(rens) == 2


def test_renewal_negative_amount_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/licenses/{d['id']}/renewals", json={"amount": -100.0})
    assert r.status_code == 422


def test_renewal_on_nonexistent_license_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _renew(c, "no-id")
    assert r.status_code == 404


# ── Cascade delete ────────────────────────────────────────────────────────────

def test_delete_cascades_assignments_and_renewals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    lic_id = d["id"]
    _assign(c, lic_id, user="alice")
    _assign(c, lic_id, user="bob")
    _renew(c, lic_id, amount=500.0)
    c.delete(f"/api/v1/licenses/{lic_id}")
    con = sqlite3.connect(lm_mod._DB_PATH)
    asn_count = con.execute(
        "SELECT COUNT(*) FROM assignments WHERE license_id=?", (lic_id,)
    ).fetchone()[0]
    ren_count = con.execute(
        "SELECT COUNT(*) FROM renewals WHERE license_id=?", (lic_id,)
    ).fetchone()[0]
    con.close()
    assert asn_count == 0
    assert ren_count == 0


# ── Expiring ──────────────────────────────────────────────────────────────────

def test_expiring_returns_active_licenses(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="Expiring Soon", expiry_date="2026-05-25")
    _transition(c, d1["id"], "active")
    d2 = _create(c, name="Far Future", expiry_date="2030-01-01")
    _transition(c, d2["id"], "active")
    r = c.get("/api/v1/licenses/expiring?days=30")
    assert r.status_code == 200
    ids = [l["id"] for l in r.json()["licenses"]]
    assert d1["id"] in ids
    assert d2["id"] not in ids


def test_expiring_excludes_terminated(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Terminated", expiry_date="2026-05-20")
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "terminated")
    r = c.get("/api/v1/licenses/expiring?days=30")
    ids = [l["id"] for l in r.json()["licenses"]]
    assert d["id"] not in ids


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/licenses/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 0
    assert s["active"] == 0
    assert s["total_cost"] == 0
    assert s["total_seats"] == 0


def test_stats_counts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A", cost=1000.0, seats_total=10)
    d2 = _create(c, name="B", cost=2000.0, seats_total=20)
    _transition(c, d1["id"], "active")
    _transition(c, d2["id"], "active")
    s = c.get("/api/v1/licenses/stats").json()
    assert s["total"] == 2
    assert s["active"] == 2
    assert s["total_cost"] == pytest.approx(3000.0)
    assert s["total_seats"] == 30


def test_stats_used_seats(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, seats_total=20)
    _transition(c, d["id"], "active")
    _assign(c, d["id"], user="alice")
    _assign(c, d["id"], user="bob")
    s = c.get("/api/v1/licenses/stats").json()
    assert s["used_seats"] == 2


def test_stats_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="A", type="subscription")
    _create(c, name="B", type="subscription")
    _create(c, name="C", type="perpetual")
    s = c.get("/api/v1/licenses/stats").json()
    types = {row["type"]: row["count"] for row in s["by_type"]}
    assert types["subscription"] == 2
    assert types["perpetual"] == 1


def test_stats_excludes_non_active_cost(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="Active", cost=1000.0, seats_total=5)
    d2 = _create(c, name="Draft",  cost=9999.0, seats_total=50)
    _transition(c, d1["id"], "active")
    s = c.get("/api/v1/licenses/stats").json()
    assert s["total_cost"] == pytest.approx(1000.0)
    assert s["total_seats"] == 5
