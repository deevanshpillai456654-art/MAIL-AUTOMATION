"""Tests for backend/api/budget_tracking.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.budget_tracking as bt_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "bud_test.db")
    monkeypatch.setattr(bt_mod, "_DB_PATH", db_path)
    bt_mod._init_db()

    app = FastAPI()
    app.include_router(bt_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"name": "Q2 Infrastructure", **kwargs}
    r = c.post("/api/v1/budgets", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, bud_id, status, **kwargs):
    return c.post(f"/api/v1/budgets/{bud_id}/transition",
                  json={"status": status, **kwargs})


def _add_entry(c, bud_id, amount=100.0, **kwargs):
    return c.post(f"/api/v1/budgets/{bud_id}/entries",
                  json={"amount": amount, **kwargs})


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Annual Software", category="software",
                amount=50000.0, currency="USD", owner="cto", team="Engineering")
    bud_id = d["id"]
    assert d["status"] == "draft"

    r = c.get(f"/api/v1/budgets/{bud_id}")
    assert r.status_code == 200
    b = r.json()
    assert b["name"] == "Annual Software"
    assert b["category"] == "software"
    assert b["amount"] == 50000.0
    assert b["currency"] == "USD"
    assert b["owner"] == "cto"
    assert b["spent"] == 0.0
    assert b["remaining"] == 50000.0
    assert b["utilization_pct"] == 0.0


def test_create_defaults(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    assert d["status"] == "draft"
    r = c.get(f"/api/v1/budgets/{d['id']}").json()
    assert r["category"] == "other"
    assert r["currency"] == "USD"
    assert r["amount"] == 0.0


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Budget A")
    _create(c, name="Budget B")
    r = c.get("/api/v1/budgets")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_list_returns_budget_spend_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Budget A", amount=500.0)
    _add_entry(c, d["id"], amount=125.0)

    r = c.get("/api/v1/budgets")

    assert r.status_code == 200
    budget = r.json()["budgets"][0]
    assert budget["spent"] == 125.0
    assert budget["remaining"] == 375.0
    assert budget["utilization_pct"] == 25.0


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A")
    _create(c, name="B")
    _transition(c, d1["id"], "active")
    r = c.get("/api/v1/budgets?status=active")
    assert r.json()["total"] == 1
    assert r.json()["budgets"][0]["id"] == d1["id"]


def test_list_filter_by_category(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="Infra", category="infrastructure")
    _create(c, name="Staff", category="personnel")
    r = c.get("/api/v1/budgets?category=infrastructure")
    assert r.json()["total"] == 1


def test_list_search(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="cloud spend", owner="devops")
    _create(c, name="office budget")
    r = c.get("/api/v1/budgets?q=cloud")
    assert r.json()["total"] == 1


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, name=f"Budget {i}")
    r = c.get("/api/v1/budgets?limit=3&offset=0")
    assert len(r.json()["budgets"]) == 3
    r2 = c.get("/api/v1/budgets?limit=3&offset=3")
    assert len(r2.json()["budgets"]) == 2


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, name="Old Name")
    r = c.patch(f"/api/v1/budgets/{d['id']}", json={
        "name": "New Name", "owner": "new-owner", "amount": 99999.0
    })
    assert r.status_code == 200
    b = c.get(f"/api/v1/budgets/{d['id']}").json()
    assert b["name"] == "New Name"
    assert b["owner"] == "new-owner"
    assert b["amount"] == 99999.0


def test_patch_returns_enriched(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, amount=1000.0)
    _transition(c, d["id"], "active")
    _add_entry(c, d["id"], amount=200.0)
    r = c.patch(f"/api/v1/budgets/{d['id']}", json={"owner": "updated"})
    assert r.status_code == 200
    b = r.json()
    assert b["spent"] == 200.0
    assert b["remaining"] == 800.0
    assert b["utilization_pct"] == 20.0


def test_delete_removes_budget(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/budgets/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/budgets/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/budgets/no-id").status_code == 404


def test_invalid_category_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/budgets", json={"name": "X", "category": "moonshot"})
    assert r.status_code == 400


def test_negative_amount_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/budgets", json={"name": "X", "amount": -100.0})
    assert r.status_code == 422


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_draft_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200
    assert c.get(f"/api/v1/budgets/{d['id']}").json()["status"] == "active"


def test_transition_draft_to_cancelled(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "cancelled")
    assert r.status_code == 200


def test_transition_active_to_frozen(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "frozen")
    assert r.status_code == 200


def test_transition_frozen_back_to_active(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "frozen")
    r = _transition(c, d["id"], "active")
    assert r.status_code == 200


def test_transition_active_to_closed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    r = _transition(c, d["id"], "closed")
    assert r.status_code == 200
    assert c.get(f"/api/v1/budgets/{d['id']}").json()["status"] == "closed"


def test_closed_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "active")
    _transition(c, d["id"], "closed")
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
    r = _transition(c, d["id"], "frozen")
    assert r.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "eliminated")
    assert r.status_code == 400


def test_transition_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-id", "active")
    assert r.status_code == 404


# ── Cost entries ──────────────────────────────────────────────────────────────

def test_add_and_list_entries(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, amount=1000.0)
    r = _add_entry(c, d["id"], amount=250.0, description="AWS bill",
                   category="compute", vendor="AWS", entry_date="2026-05-01")
    assert r.status_code == 201
    assert r.json()["spent"] == 250.0

    entries = c.get(f"/api/v1/budgets/{d['id']}/entries").json()
    assert entries["total"] == 1
    assert entries["entries"][0]["description"] == "AWS bill"
    assert entries["entries"][0]["vendor"] == "AWS"
    assert entries["spent"] == 250.0


def test_multiple_entries_accumulate_spend(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, amount=1000.0)
    _add_entry(c, d["id"], amount=100.0)
    _add_entry(c, d["id"], amount=200.0)
    _add_entry(c, d["id"], amount=300.0)
    b = c.get(f"/api/v1/budgets/{d['id']}").json()
    assert b["spent"] == 600.0
    assert b["remaining"] == 400.0
    assert b["utilization_pct"] == 60.0


def test_delete_entry_reduces_spend(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, amount=1000.0)
    _add_entry(c, d["id"], amount=400.0)
    r2 = _add_entry(c, d["id"], amount=100.0)
    # get entry id from entries list
    entries = c.get(f"/api/v1/budgets/{d['id']}/entries").json()["entries"]
    entry_id = entries[0]["id"]
    dr = c.delete(f"/api/v1/budgets/{d['id']}/entries/{entry_id}")
    assert dr.status_code in (200, 204)
    b = c.get(f"/api/v1/budgets/{d['id']}").json()
    assert b["spent"] == pytest.approx(500.0 - entries[0]["amount"], abs=0.01)


def test_entry_negative_amount_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _add_entry(c, d["id"], amount=-50.0)
    assert r.status_code == 422


def test_entry_on_nonexistent_budget_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _add_entry(c, "no-id", amount=10.0)
    assert r.status_code == 404


def test_delete_entry_wrong_budget_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="B1")
    d2 = _create(c, name="B2")
    _add_entry(c, d1["id"], amount=50.0)
    eid = c.get(f"/api/v1/budgets/{d1['id']}/entries").json()["entries"][0]["id"]
    r = c.delete(f"/api/v1/budgets/{d2['id']}/entries/{eid}")
    assert r.status_code == 404


def test_delete_budget_cascades_entries(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    bud_id = d["id"]
    _add_entry(c, bud_id, amount=100.0)
    _add_entry(c, bud_id, amount=200.0)
    c.delete(f"/api/v1/budgets/{bud_id}")
    con = sqlite3.connect(bt_mod._DB_PATH)
    count = con.execute(
        "SELECT COUNT(*) FROM cost_entries WHERE budget_id=?", (bud_id,)
    ).fetchone()[0]
    con.close()
    assert count == 0


# ── Global recent entries ──────────────────────────────────────────────────────

def test_global_recent_entries(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="B1")
    d2 = _create(c, name="B2")
    _add_entry(c, d1["id"], amount=10.0, description="entry1")
    _add_entry(c, d2["id"], amount=20.0, description="entry2")
    r = c.get("/api/v1/cost_entries")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 2


def test_global_recent_entries_limit(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    for i in range(5):
        _add_entry(c, d["id"], amount=float(i + 1))
    r = c.get("/api/v1/cost_entries?limit=3")
    assert len(r.json()["entries"]) == 3


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/budgets/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 0
    assert s["active"] == 0
    assert s["total_allocated"] == 0
    assert s["total_spent"] == 0
    assert s["over_budget"] == 0


def test_stats_counts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="A", amount=1000.0)
    d2 = _create(c, name="B", amount=500.0)
    _transition(c, d1["id"], "active")
    _transition(c, d2["id"], "active")
    s = c.get("/api/v1/budgets/stats").json()
    assert s["total"] == 2
    assert s["active"] == 2
    assert s["total_allocated"] == pytest.approx(1500.0)


def test_stats_total_spent(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, amount=1000.0)
    _transition(c, d["id"], "active")
    _add_entry(c, d["id"], amount=300.0)
    _add_entry(c, d["id"], amount=150.0)
    s = c.get("/api/v1/budgets/stats").json()
    assert s["total_spent"] == pytest.approx(450.0)


def test_stats_over_budget(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, amount=100.0)
    _transition(c, d["id"], "active")
    _add_entry(c, d["id"], amount=150.0)
    s = c.get("/api/v1/budgets/stats").json()
    assert s["over_budget"] == 1


def test_stats_by_category(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, name="A", category="software")
    _create(c, name="B", category="software")
    _create(c, name="C", category="infrastructure")
    s = c.get("/api/v1/budgets/stats").json()
    cats = {row["category"]: row["count"] for row in s["by_category"]}
    assert cats["software"] == 2
    assert cats["infrastructure"] == 1


def test_stats_excludes_non_active_from_totals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, name="Active", amount=1000.0)
    d2 = _create(c, name="Draft",  amount=5000.0)
    _transition(c, d1["id"], "active")
    _add_entry(c, d1["id"], amount=200.0)
    s = c.get("/api/v1/budgets/stats").json()
    assert s["total_allocated"] == pytest.approx(1000.0)
    assert s["total_spent"] == pytest.approx(200.0)
