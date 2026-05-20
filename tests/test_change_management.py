"""Tests for backend/api/change_management.py"""
from __future__ import annotations

import sqlite3
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── helpers ──────────────────────────────────────────────────────────────────

def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = str(tmp_path / "change_management.db")
    if "backend.api.change_management" in sys.modules:
        del sys.modules["backend.api.change_management"]
    import backend.api.change_management as cm_mod
    monkeypatch.setattr(cm_mod, "_DB_PATH", db)
    cm_mod._init_db()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.include_router(cm_mod.router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: "test"
    return TestClient(app, raise_server_exceptions=True)


def _create(c, **kwargs):
    body = {"title": "Test Change", "change_type": "normal", "risk_level": "low"}
    body.update(kwargs)
    r = c.post("/api/v1/changes", json=body)
    assert r.status_code == 201
    return r.json()


def _transition(c, cr_id, status, **kwargs):
    body = {"status": status}
    body.update(kwargs)
    return c.post(f"/api/v1/changes/{cr_id}/transition", json=body)


# ── create ────────────────────────────────────────────────────────────────────

def test_create_minimal(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/changes", json={"title": "Deploy v2"})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "Deploy v2"
    assert body["status"] == "draft"
    assert "id" in body


def test_create_defaults(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    r = c.get(f"/api/v1/changes/{cr_id}")
    assert r.json()["change_type"] == "normal"
    assert r.json()["risk_level"] == "low"
    assert r.json()["status"] == "draft"


def test_create_all_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/changes", json={
        "title": "Full Change",
        "description": "Deploy new auth service",
        "change_type": "emergency",
        "risk_level": "critical",
        "owner": "ops-team",
        "assignee": "alice",
        "planned_start": "2026-06-01T00:00:00Z",
        "planned_end": "2026-06-01T02:00:00Z",
        "rollback_plan": "Revert to previous tag",
        "linked_incident_id": "inc-001",
        "linked_runbook_id": "rb-001",
        "change_note": "Emergency auth fix",
    })
    assert r.status_code == 201
    detail = c.get(f"/api/v1/changes/{r.json()['id']}").json()
    assert detail["change_type"] == "emergency"
    assert detail["risk_level"] == "critical"
    assert detail["owner"] == "ops-team"
    assert detail["rollback_plan"] == "Revert to previous tag"


def test_create_invalid_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/changes", json={"title": "X", "change_type": "invalid"})
    assert r.status_code == 400


def test_create_invalid_risk(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/v1/changes", json={"title": "X", "risk_level": "extreme"})
    assert r.status_code == 400


# ── list ─────────────────────────────────────────────────────────────────────

def test_list_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/changes")
    assert r.status_code == 200
    assert r.json()["changes"] == []
    assert r.json()["total"] == 0


def test_list_returns_all(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="A")
    _create(c, title="B")
    r = c.get("/api/v1/changes")
    assert r.json()["total"] == 2


def test_list_filter_by_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c, title="To Review")["id"]
    _transition(c, cr_id, "review")
    _create(c, title="Stays Draft")
    r = c.get("/api/v1/changes?status=review")
    assert r.json()["total"] == 1
    assert r.json()["changes"][0]["title"] == "To Review"


def test_list_filter_by_risk(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="High Risk", risk_level="high")
    _create(c, title="Low Risk", risk_level="low")
    r = c.get("/api/v1/changes?risk_level=high")
    assert r.json()["total"] == 1
    assert r.json()["changes"][0]["title"] == "High Risk"


def test_list_filter_by_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="Emergency", change_type="emergency")
    _create(c, title="Normal", change_type="normal")
    r = c.get("/api/v1/changes?change_type=emergency")
    assert r.json()["total"] == 1


def test_list_search_by_title(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    _create(c, title="Alpha Deploy")
    _create(c, title="Beta Rollout")
    r = c.get("/api/v1/changes?q=Alpha")
    assert r.json()["total"] == 1
    assert r.json()["changes"][0]["title"] == "Alpha Deploy"


def test_list_pagination(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    for i in range(5):
        _create(c, title=f"CR {i}")
    r = c.get("/api/v1/changes?limit=2&offset=0")
    assert len(r.json()["changes"]) == 2
    assert r.json()["total"] == 5


# ── get detail ────────────────────────────────────────────────────────────────

def test_get_by_id(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c, title="Detail Test")["id"]
    r = c.get(f"/api/v1/changes/{cr_id}")
    assert r.status_code == 200
    assert r.json()["title"] == "Detail Test"


def test_get_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/changes/nonexistent")
    assert r.status_code == 404


def test_get_includes_approvals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice"})
    r = c.get(f"/api/v1/changes/{cr_id}")
    assert len(r.json()["approvals"]) == 1
    assert r.json()["approvals"][0]["approver"] == "alice"


# ── patch ─────────────────────────────────────────────────────────────────────

def test_patch_title(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c, title="Original")["id"]
    c.patch(f"/api/v1/changes/{cr_id}", json={"title": "Updated"})
    assert c.get(f"/api/v1/changes/{cr_id}").json()["title"] == "Updated"


def test_patch_multiple_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    c.patch(f"/api/v1/changes/{cr_id}", json={"risk_level": "high", "owner": "ops", "assignee": "bob"})
    detail = c.get(f"/api/v1/changes/{cr_id}").json()
    assert detail["risk_level"] == "high"
    assert detail["owner"] == "ops"
    assert detail["assignee"] == "bob"


def test_patch_invalid_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    r = c.patch(f"/api/v1/changes/{cr_id}", json={"change_type": "bad"})
    assert r.status_code == 400


def test_patch_empty_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    r = c.patch(f"/api/v1/changes/{cr_id}", json={})
    assert r.status_code == 400


def test_patch_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.patch("/api/v1/changes/missing", json={"title": "X"})
    assert r.status_code == 404


# ── delete ────────────────────────────────────────────────────────────────────

def test_delete(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    r = c.delete(f"/api/v1/changes/{cr_id}")
    assert r.status_code == 204
    assert c.get(f"/api/v1/changes/{cr_id}").status_code == 404


def test_delete_cascades_approvals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    import backend.api.change_management as cm_mod
    cr_id = _create(c)["id"]
    c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice"})
    c.delete(f"/api/v1/changes/{cr_id}")
    with sqlite3.connect(cm_mod._DB_PATH) as con:
        count = con.execute("SELECT COUNT(*) FROM change_approvals WHERE change_id=?", (cr_id,)).fetchone()[0]
    assert count == 0


def test_delete_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.delete("/api/v1/changes/missing")
    assert r.status_code == 404


def test_delete_in_progress_blocked(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    _transition(c, cr_id, "review")
    _transition(c, cr_id, "approved")
    _transition(c, cr_id, "in_progress")
    r = c.delete(f"/api/v1/changes/{cr_id}")
    assert r.status_code == 409


# ── transitions ───────────────────────────────────────────────────────────────

def test_transition_draft_to_review(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    r = _transition(c, cr_id, "review")
    assert r.status_code == 200
    assert c.get(f"/api/v1/changes/{cr_id}").json()["status"] == "review"


def test_transition_full_happy_path(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    _transition(c, cr_id, "review")
    _transition(c, cr_id, "approved", approved_by="mgr")
    _transition(c, cr_id, "in_progress")
    r = _transition(c, cr_id, "completed")
    assert r.status_code == 200
    detail = c.get(f"/api/v1/changes/{cr_id}").json()
    assert detail["status"] == "completed"
    assert detail["actual_start"] is not None
    assert detail["actual_end"] is not None


def test_transition_approved_sets_approved_by(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    _transition(c, cr_id, "review")
    _transition(c, cr_id, "approved", approved_by="mgr@example.com")
    detail = c.get(f"/api/v1/changes/{cr_id}").json()
    assert detail["approved_by"] == "mgr@example.com"
    assert detail["approved_at"] is not None


def test_transition_invalid_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    r = _transition(c, cr_id, "nonexistent")
    assert r.status_code == 400


def test_transition_not_allowed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    r = _transition(c, cr_id, "completed")  # can't go draft → completed
    assert r.status_code == 400


def test_transition_terminal_blocked(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    _transition(c, cr_id, "cancelled")
    r = _transition(c, cr_id, "review")  # terminal — no transitions allowed
    assert r.status_code == 400


def test_transition_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = _transition(c, "nonexistent", "review")
    assert r.status_code == 404


def test_transition_failed_sets_actual_end(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    _transition(c, cr_id, "review")
    _transition(c, cr_id, "approved")
    _transition(c, cr_id, "in_progress")
    _transition(c, cr_id, "failed")
    detail = c.get(f"/api/v1/changes/{cr_id}").json()
    assert detail["actual_end"] is not None


# ── stats ─────────────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/changes/stats")
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["pending_approvals"] == 0


def test_stats_counts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c, risk_level="high", change_type="emergency")["id"]
    _transition(c, cr_id, "review")
    r = c.get("/api/v1/changes/stats")
    assert r.json()["total"] == 1
    by_status = {x["status"]: x["count"] for x in r.json()["by_status"]}
    assert by_status.get("review") == 1
    by_risk = {x["risk_level"]: x["count"] for x in r.json()["by_risk"]}
    assert by_risk.get("high") == 1
    by_type = {x["change_type"]: x["count"] for x in r.json()["by_type"]}
    assert by_type.get("emergency") == 1


def test_stats_pending_approvals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice"})
    c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "bob"})
    r = c.get("/api/v1/changes/stats")
    assert r.json()["pending_approvals"] == 2


# ── approvals ─────────────────────────────────────────────────────────────────

def test_add_approver(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    r = c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice", "note": "LGTM"})
    assert r.status_code == 201
    assert r.json()["status"] == "pending"


def test_add_approver_duplicate_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice"})
    r = c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice"})
    assert r.status_code == 409


def test_add_approver_empty_name_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    r = c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "   "})
    assert r.status_code == 400


def test_list_approvals(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice"})
    c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "bob"})
    r = c.get(f"/api/v1/changes/{cr_id}/approvals")
    assert r.status_code == 200
    assert len(r.json()["approvals"]) == 2


def test_list_approvals_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api/v1/changes/missing/approvals")
    assert r.status_code == 404


def test_update_approval_approve(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    apr_id = c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice"}).json()["id"]
    r = c.patch(f"/api/v1/changes/{cr_id}/approvals/{apr_id}", json={"status": "approved", "note": "LGTM"})
    assert r.status_code == 200
    detail = c.get(f"/api/v1/changes/{cr_id}").json()
    apr = next(a for a in detail["approvals"] if a["id"] == apr_id)
    assert apr["status"] == "approved"
    assert apr["decided_at"] is not None


def test_update_approval_reject(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    apr_id = c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice"}).json()["id"]
    r = c.patch(f"/api/v1/changes/{cr_id}/approvals/{apr_id}", json={"status": "rejected", "note": "not ready"})
    assert r.status_code == 200
    assert c.get(f"/api/v1/changes/{cr_id}").json()["approvals"][0]["status"] == "rejected"


def test_update_approval_invalid_status(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    apr_id = c.post(f"/api/v1/changes/{cr_id}/approvals", json={"approver": "alice"}).json()["id"]
    r = c.patch(f"/api/v1/changes/{cr_id}/approvals/{apr_id}", json={"status": "maybe"})
    assert r.status_code == 400


def test_update_approval_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    cr_id = _create(c)["id"]
    r = c.patch(f"/api/v1/changes/{cr_id}/approvals/missing", json={"status": "approved"})
    assert r.status_code == 404
