"""Tests for backend/api/vendor_management.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.vendor_management as vm_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "vm_test.db")
    monkeypatch.setattr(vm_mod, "_DB_PATH", db_path)
    vm_mod._init_db()

    app = FastAPI()
    app.include_router(vm_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"name": "Acme Corp", "category": "software", **kwargs}
    r = c.post("/api/v1/vendors", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, ven_id, status, **kwargs):
    return c.post(f"/api/v1/vendors/{ven_id}/transition",
                  json={"status": status, **kwargs})


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="CloudCo", category="cloud", website="https://cloud.co",
                contract_start="2025-01-01", contract_end="2026-01-01",
                contract_value=50000.0, sla_tier="premium", owner="procurement")
    ven_id = d["id"]
    assert d["status"] == "active"

    r = c.get(f"/api/v1/vendors/{ven_id}")
    assert r.status_code == 200
    v = r.json()
    assert v["name"] == "CloudCo"
    assert v["category"] == "cloud"
    assert v["contract_end"] == "2026-01-01"
    assert v["contract_value"] == 50000.0
    assert v["sla_tier"] == "premium"
    assert v["status"] == "active"


def test_default_status_is_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    assert d["status"] == "active"


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Alpha Inc")
    _create(c, name="Beta LLC")
    r = c.get("/api/v1/vendors")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    _create(c, name="B")
    _transition(c, d1["id"], "suspended")
    r = c.get("/api/v1/vendors?status=suspended")
    assert r.json()["total"] == 1
    assert r.json()["vendors"][0]["id"] == d1["id"]


def test_list_filter_by_category(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="SaaS Co", category="software")
    _create(c, name="Consultants", category="consulting")
    r = c.get("/api/v1/vendors?category=software")
    assert r.json()["total"] == 1


def test_list_search(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="DataSystems Inc", owner="alice")
    _create(c, name="WebServices Ltd", owner="bob")
    r = c.get("/api/v1/vendors?q=DataSystems")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, name=f"Vendor {i}")
    r = c.get("/api/v1/vendors?limit=3&offset=0")
    assert len(r.json()["vendors"]) == 3
    r2 = c.get("/api/v1/vendors?limit=3&offset=3")
    assert len(r2.json()["vendors"]) == 2


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Old Name")
    r = c.patch(f"/api/v1/vendors/{d['id']}", json={
        "name": "New Name", "sla_tier": "enhanced", "contract_value": 99999.0
    })
    assert r.status_code == 200
    v = c.get(f"/api/v1/vendors/{d['id']}").json()
    assert v["name"] == "New Name"
    assert v["sla_tier"] == "enhanced"
    assert v["contract_value"] == 99999.0


def test_patch_invalid_category_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.patch(f"/api/v1/vendors/{d['id']}", json={"category": "unicorn"})
    assert r.status_code == 400


def test_delete_removes_vendor(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/vendors/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/vendors/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/vendors/no-such-id").status_code == 404


def test_create_invalid_category_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/vendors", json={"name": "X", "category": "spaceship"})
    assert r.status_code == 400


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_active_to_under_review(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "under_review")
    assert r.status_code == 200
    assert c.get(f"/api/v1/vendors/{d['id']}").json()["status"] == "under_review"


def test_transition_under_review_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "under_review")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200


def test_transition_active_to_suspended(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "suspended")
    assert r.status_code == 200


def test_transition_suspended_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "suspended")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200


def test_transition_to_terminated(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "terminated")
    assert r.status_code == 200
    assert c.get(f"/api/v1/vendors/{d['id']}").json()["status"] == "terminated"


def test_terminated_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "terminated")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 400


def test_invalid_transition_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "terminated")
    assert r.status_code == 200
    r2 = _transition(c, d["id"], "suspended")
    assert r2.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "bankrupt")
    assert r.status_code == 400


def test_transition_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-id", "suspended")
    assert r.status_code == 404


# ── Contacts ──────────────────────────────────────────────────────────────────

def test_add_and_list_contact(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/vendors/{d['id']}/contacts", json={
        "name": "Jane Smith", "email": "jane@acme.com", "role": "Account Manager"
    })
    assert r.status_code == 201
    contacts = c.get(f"/api/v1/vendors/{d['id']}/contacts").json()["contacts"]
    assert len(contacts) == 1
    assert contacts[0]["name"] == "Jane Smith"
    assert contacts[0]["email"] == "jane@acme.com"


def test_primary_contact_flag(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    c.post(f"/api/v1/vendors/{d['id']}/contacts",
           json={"name": "Primary", "is_primary": True})
    c.post(f"/api/v1/vendors/{d['id']}/contacts",
           json={"name": "Secondary", "is_primary": False})
    contacts = c.get(f"/api/v1/vendors/{d['id']}/contacts").json()["contacts"]
    assert contacts[0]["name"] == "Primary"
    assert contacts[0]["is_primary"] == 1


def test_delete_contact(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    ct = c.post(f"/api/v1/vendors/{d['id']}/contacts",
                json={"name": "To Remove"}).json()
    r = c.delete(f"/api/v1/vendors/{d['id']}/contacts/{ct['id']}")
    assert r.status_code in (200, 204)
    contacts = c.get(f"/api/v1/vendors/{d['id']}/contacts").json()["contacts"]
    assert len(contacts) == 0


def test_delete_nonexistent_contact_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/vendors/{d['id']}/contacts/no-id")
    assert r.status_code == 404


def test_contact_on_nonexistent_vendor_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/vendors/no-id/contacts", json={"name": "X"})
    assert r.status_code == 404


# ── Reviews ───────────────────────────────────────────────────────────────────

def test_add_and_list_review(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/vendors/{d['id']}/reviews", json={
        "rating": 4, "notes": "Good SLA compliance", "reviewer": "alice"
    })
    assert r.status_code == 201
    revs = c.get(f"/api/v1/vendors/{d['id']}/reviews").json()
    assert len(revs["reviews"]) == 1
    assert revs["reviews"][0]["rating"] == 4
    assert revs["avg_rating"] == 4.0


def test_avg_rating_computed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    c.post(f"/api/v1/vendors/{d['id']}/reviews", json={"rating": 5})
    c.post(f"/api/v1/vendors/{d['id']}/reviews", json={"rating": 3})
    revs = c.get(f"/api/v1/vendors/{d['id']}/reviews").json()
    assert revs["avg_rating"] == 4.0


def test_invalid_rating_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/vendors/{d['id']}/reviews", json={"rating": 6})
    assert r.status_code == 422


def test_rating_zero_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.post(f"/api/v1/vendors/{d['id']}/reviews", json={"rating": 0})
    assert r.status_code == 422


def test_review_on_nonexistent_vendor_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/vendors/no-id/reviews", json={"rating": 3})
    assert r.status_code == 404


# ── Stats & expiring ──────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/vendors/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 0
    assert s["active"] == 0
    assert s["expiring_30"] == 0


def test_stats_counts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    _create(c, name="B")
    _transition(c, d1["id"], "suspended")
    r = c.get("/api/v1/vendors/stats")
    s = r.json()
    assert s["total"] == 2
    assert s["active"] == 1
    by_status = {x["status"]: x["count"] for x in s["by_status"]}
    assert by_status.get("suspended", 0) == 1


def test_stats_by_category(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, category="cloud")
    _create(c, category="cloud")
    _create(c, category="software")
    r = c.get("/api/v1/vendors/stats")
    by_cat = {x["category"]: x["count"] for x in r.json()["by_category"]}
    assert by_cat.get("cloud", 0) == 2
    assert by_cat.get("software", 0) == 1


def test_stats_avg_rating(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    c.post(f"/api/v1/vendors/{d['id']}/reviews", json={"rating": 4})
    c.post(f"/api/v1/vendors/{d['id']}/reviews", json={"rating": 2})
    r = c.get("/api/v1/vendors/stats")
    assert r.json()["avg_rating"] == 3.0


def test_expiring_endpoint(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Expires Soon", contract_end="2026-05-25")
    _create(c, name="Far Future",   contract_end="2030-01-01")
    _create(c, name="No Contract")
    r = c.get("/api/v1/vendors/expiring?days=30")
    assert r.status_code == 200
    names = [v["name"] for v in r.json()["vendors"]]
    assert "Expires Soon" in names
    assert "Far Future" not in names


# ── Cascade delete ─────────────────────────────────────────────────────────────

def test_delete_cascades_contacts_and_reviews(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    ven_id = d["id"]
    c.post(f"/api/v1/vendors/{ven_id}/contacts", json={"name": "Jane"})
    c.post(f"/api/v1/vendors/{ven_id}/reviews",  json={"rating": 5})
    c.delete(f"/api/v1/vendors/{ven_id}")
    con = sqlite3.connect(vm_mod._DB_PATH)
    ct_count  = con.execute("SELECT COUNT(*) FROM vendor_contacts WHERE vendor_id=?", (ven_id,)).fetchone()[0]
    rev_count = con.execute("SELECT COUNT(*) FROM vendor_reviews WHERE vendor_id=?", (ven_id,)).fetchone()[0]
    con.close()
    assert ct_count  == 0
    assert rev_count == 0
