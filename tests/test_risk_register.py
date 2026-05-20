"""Tests for backend/api/risk_register.py"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.risk_register as rr_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "risk_test.db")
    monkeypatch.setattr(rr_mod, "_DB_PATH", db_path)
    rr_mod._init_db()

    app = FastAPI()
    app.include_router(rr_mod.router, prefix="/api/v1")

    from backend.auth.local_auth import require_local_auth
    app.dependency_overrides[require_local_auth] = lambda: True

    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    payload = {"title": "Unpatched CVE in auth service", **kwargs}
    r = c.post("/api/v1/risks", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _transition(c, risk_id, status, **kwargs):
    return c.post(f"/api/v1/risks/{risk_id}/transition",
                  json={"status": status, **kwargs})


def _review(c, risk_id, likelihood=3, impact=3, **kwargs):
    return c.post(f"/api/v1/risks/{risk_id}/reviews",
                  json={"likelihood": likelihood, "impact": impact, **kwargs})


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_get(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, title="SQL Injection in payments", category="security",
                likelihood=4, impact=5, owner="security-team", team="Engineering")
    risk_id = d["id"]
    assert d["status"] == "identified"
    assert d["risk_score"] == 20
    assert d["risk_level"] == "critical"

    r = c.get(f"/api/v1/risks/{risk_id}")
    assert r.status_code == 200
    risk = r.json()
    assert risk["title"] == "SQL Injection in payments"
    assert risk["category"] == "security"
    assert risk["likelihood"] == 4
    assert risk["impact"] == 5
    assert risk["risk_score"] == 20
    assert risk["risk_level"] == "critical"
    assert risk["owner"] == "security-team"


def test_create_defaults(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.get(f"/api/v1/risks/{d['id']}").json()
    assert r["category"] == "operational"
    assert r["likelihood"] == 3
    assert r["impact"] == 3
    assert r["risk_score"] == 9
    assert r["risk_level"] == "medium"
    assert r["status"] == "identified"


def test_list_returns_created(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="Risk A")
    _create(c, title="Risk B")
    r = c.get("/api/v1/risks")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, title="A")
    _create(c, title="B")
    _transition(c, d1["id"], "assessed")
    r = c.get("/api/v1/risks?status=assessed")
    assert r.json()["total"] == 1
    assert r.json()["risks"][0]["id"] == d1["id"]


def test_list_filter_by_category(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="A", category="security")
    _create(c, title="B", category="financial")
    r = c.get("/api/v1/risks?category=security")
    assert r.json()["total"] == 1


def test_list_filter_by_level_critical(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="Critical", likelihood=5, impact=5)
    _create(c, title="Low",      likelihood=1, impact=1)
    r = c.get("/api/v1/risks?level=critical")
    assert r.json()["total"] == 1
    assert r.json()["risks"][0]["risk_level"] == "critical"


def test_list_filter_by_level_low(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="High", likelihood=4, impact=4)
    _create(c, title="Low",  likelihood=1, impact=2)
    r = c.get("/api/v1/risks?level=low")
    assert r.json()["total"] == 1
    assert r.json()["risks"][0]["title"] == "Low"


def test_list_search(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="GDPR data breach", tags="gdpr,privacy")
    _create(c, title="Server outage")
    r = c.get("/api/v1/risks?q=gdpr")
    assert r.json()["total"] == 1


def test_list_sorted_by_score_desc(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="Low",  likelihood=1, impact=1)
    _create(c, title="High", likelihood=5, impact=5)
    risks = c.get("/api/v1/risks").json()["risks"]
    assert risks[0]["title"] == "High"
    assert risks[1]["title"] == "Low"


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, title=f"Risk {i}")
    r = c.get("/api/v1/risks?limit=3&offset=0")
    assert len(r.json()["risks"]) == 3
    r2 = c.get("/api/v1/risks?limit=3&offset=3")
    assert len(r2.json()["risks"]) == 2


def test_list_includes_computed_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, likelihood=3, impact=4)
    r = c.get("/api/v1/risks").json()["risks"][0]
    assert r["risk_score"] == 12
    assert r["risk_level"] == "high"


def test_patch_updates_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, title="Old Title")
    r = c.patch(f"/api/v1/risks/{d['id']}", json={
        "title": "New Title", "owner": "new-owner", "mitigation_plan": "patch it"
    })
    assert r.status_code == 200
    risk = c.get(f"/api/v1/risks/{d['id']}").json()
    assert risk["title"] == "New Title"
    assert risk["owner"] == "new-owner"
    assert risk["mitigation_plan"] == "patch it"


def test_patch_likelihood_impact_updates_score(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, likelihood=1, impact=1)
    r = c.patch(f"/api/v1/risks/{d['id']}", json={"likelihood": 5, "impact": 5})
    assert r.status_code == 200
    assert r.json()["risk_score"] == 25
    assert r.json()["risk_level"] == "critical"


def test_delete_removes_risk(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = c.delete(f"/api/v1/risks/{d['id']}")
    assert r.status_code in (200, 204)
    assert c.get(f"/api/v1/risks/{d['id']}").status_code == 404


def test_get_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.get("/api/v1/risks/no-id").status_code == 404


def test_invalid_category_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/risks", json={"title": "X", "category": "reputational"})
    assert r.status_code == 400


def test_likelihood_out_of_range_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/risks", json={"title": "X", "likelihood": 6})
    assert r.status_code == 422


def test_impact_out_of_range_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/risks", json={"title": "X", "impact": 0})
    assert r.status_code == 422


# ── Risk level thresholds ──────────────────────────────────────────────────────

def test_risk_level_low(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, likelihood=1, impact=2)
    assert c.get(f"/api/v1/risks/{d['id']}").json()["risk_level"] == "low"


def test_risk_level_medium(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, likelihood=3, impact=2)
    r = c.get(f"/api/v1/risks/{d['id']}").json()
    assert r["risk_score"] == 6
    assert r["risk_level"] == "medium"


def test_risk_level_high(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, likelihood=2, impact=5)
    r = c.get(f"/api/v1/risks/{d['id']}").json()
    assert r["risk_score"] == 10
    assert r["risk_level"] == "high"


def test_risk_level_critical(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, likelihood=5, impact=3)
    r = c.get(f"/api/v1/risks/{d['id']}").json()
    assert r["risk_score"] == 15
    assert r["risk_level"] == "critical"


# ── State machine ─────────────────────────────────────────────────────────────

def test_transition_identified_to_assessed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "assessed")
    assert r.status_code == 200
    assert c.get(f"/api/v1/risks/{d['id']}").json()["status"] == "assessed"


def test_transition_identified_to_closed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "closed")
    assert r.status_code == 200


def test_transition_assessed_to_mitigating(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "assessed")
    r = _transition(c, d["id"], "mitigating")
    assert r.status_code == 200


def test_transition_assessed_to_accepted(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "assessed")
    r = _transition(c, d["id"], "accepted")
    assert r.status_code == 200


def test_transition_mitigating_to_resolved(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "assessed")
    _transition(c, d["id"], "mitigating")
    r = _transition(c, d["id"], "resolved")
    assert r.status_code == 200


def test_transition_accepted_to_mitigating(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "assessed")
    _transition(c, d["id"], "accepted")
    r = _transition(c, d["id"], "mitigating")
    assert r.status_code == 200


def test_transition_resolved_to_identified(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "assessed")
    _transition(c, d["id"], "mitigating")
    _transition(c, d["id"], "resolved")
    r = _transition(c, d["id"], "identified")
    assert r.status_code == 200


def test_closed_is_terminal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _transition(c, d["id"], "closed")
    r = _transition(c, d["id"], "identified")
    assert r.status_code == 400


def test_invalid_transition_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "mitigating")
    assert r.status_code == 400


def test_unknown_status_returns_400(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _transition(c, d["id"], "ignored")
    assert r.status_code == 400


def test_transition_nonexistent_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "no-id", "assessed")
    assert r.status_code == 404


# ── Reviews ───────────────────────────────────────────────────────────────────

def test_add_and_list_reviews(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, likelihood=3, impact=3)
    r = _review(c, d["id"], likelihood=4, impact=5,
                reviewer="risk-committee", notes="Escalated after audit")
    assert r.status_code == 201
    assert r.json()["risk_score"] == 20
    assert r.json()["risk_level"] == "critical"

    revs = c.get(f"/api/v1/risks/{d['id']}/reviews").json()["reviews"]
    assert len(revs) == 1
    assert revs[0]["likelihood"] == 4
    assert revs[0]["impact"] == 5
    assert revs[0]["reviewer"] == "risk-committee"


def test_review_updates_risk_likelihood_and_impact(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, likelihood=2, impact=2)
    _review(c, d["id"], likelihood=5, impact=5)
    risk = c.get(f"/api/v1/risks/{d['id']}").json()
    assert risk["likelihood"] == 5
    assert risk["impact"] == 5
    assert risk["risk_score"] == 25
    assert risk["risk_level"] == "critical"


def test_review_decreases_score(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c, likelihood=5, impact=5)
    _review(c, d["id"], likelihood=1, impact=1)
    risk = c.get(f"/api/v1/risks/{d['id']}").json()
    assert risk["risk_score"] == 1
    assert risk["risk_level"] == "low"


def test_multiple_reviews(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    _review(c, d["id"], likelihood=2, impact=2)
    _review(c, d["id"], likelihood=3, impact=3)
    revs = c.get(f"/api/v1/risks/{d['id']}/reviews").json()["reviews"]
    assert len(revs) == 2


def test_review_likelihood_out_of_range_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _review(c, d["id"], likelihood=6, impact=3)
    assert r.status_code == 422


def test_review_impact_out_of_range_returns_422(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    r = _review(c, d["id"], likelihood=3, impact=0)
    assert r.status_code == 422


def test_review_nonexistent_risk_returns_404(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _review(c, "no-id")
    assert r.status_code == 404


# ── Cascade delete ────────────────────────────────────────────────────────────

def test_delete_cascades_reviews(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d = _create(c)
    risk_id = d["id"]
    _review(c, risk_id, likelihood=4, impact=4)
    _review(c, risk_id, likelihood=2, impact=2)
    c.delete(f"/api/v1/risks/{risk_id}")
    con = sqlite3.connect(rr_mod._DB_PATH)
    count = con.execute(
        "SELECT COUNT(*) FROM risk_reviews WHERE risk_id=?", (risk_id,)
    ).fetchone()[0]
    con.close()
    assert count == 0


# ── Stats ──────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/risks/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["total"] == 0
    assert s["critical"] == 0
    assert s["high"] == 0
    assert s["avg_score"] == 0.0


def test_stats_counts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="Critical", likelihood=5, impact=5)
    _create(c, title="High",     likelihood=2, impact=5)
    _create(c, title="Medium",   likelihood=3, impact=2)
    s = c.get("/api/v1/risks/stats").json()
    assert s["total"] == 3
    assert s["critical"] == 1
    assert s["high"] == 1
    assert s["by_level"]["critical"] == 1
    assert s["by_level"]["high"] == 1
    assert s["by_level"]["medium"] == 1


def test_stats_open_count(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    d1 = _create(c, title="Open")
    d2 = _create(c, title="Closed")
    _transition(c, d2["id"], "closed")
    s = c.get("/api/v1/risks/stats").json()
    assert s["open"] == 1


def test_stats_avg_score(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, likelihood=2, impact=2)
    _create(c, likelihood=4, impact=4)
    s = c.get("/api/v1/risks/stats").json()
    assert s["avg_score"] == pytest.approx(10.0)


def test_stats_by_category(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="A", category="security")
    _create(c, title="B", category="security")
    _create(c, title="C", category="financial")
    s = c.get("/api/v1/risks/stats").json()
    cats = {row["category"]: row["count"] for row in s["by_category"]}
    assert cats["security"] == 2
    assert cats["financial"] == 1
