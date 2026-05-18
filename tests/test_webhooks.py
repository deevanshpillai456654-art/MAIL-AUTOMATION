"""Tests for the outbound webhook system (backend/api/webhooks.py)."""
import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _allowed_decision():
    from backend.security.ssrf import OutboundURLDecision
    return OutboundURLDecision(allowed=True, reason="ok", resolved_ips=["93.184.216.34"])


def _setup_db(tmp_path, monkeypatch):
    from backend.api import webhooks as wh
    db_path = str(tmp_path / "webhooks.db")
    monkeypatch.setattr(wh, "_DB_PATH", db_path)
    wh._init_db()
    return db_path


def _client(tmp_path, monkeypatch):
    from backend.api import webhooks as wh
    from backend.auth.local_auth import require_local_auth
    from backend.security.ssrf import OutboundURLDecision

    _setup_db(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "backend.api.webhooks.validate_outbound_url",
        lambda url, **kw: _allowed_decision(),
    )

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(wh.router, prefix="/api/v1")
    return TestClient(app)


# ── pattern-matching unit tests ───────────────────────────────────────────────

def test_event_matches_wildcard():
    from backend.api.webhooks import _event_matches
    assert _event_matches("*", "threat.detected") is True
    assert _event_matches("*", "email.received") is True
    assert _event_matches("*", "anything") is True


def test_event_matches_dotstar():
    from backend.api.webhooks import _event_matches
    assert _event_matches("threat.*", "threat.detected") is True
    assert _event_matches("threat.*", "threat.escalated") is True
    assert _event_matches("threat.*", "email.received") is False


def test_event_matches_exact():
    from backend.api.webhooks import _event_matches
    assert _event_matches("email.received", "email.received") is True
    assert _event_matches("email.received", "email.classified") is False


def test_webhook_matches_severity_filter():
    from backend.api.webhooks import _webhook_matches
    wh = {"events": '["*"]', "min_severity": "high"}
    assert _webhook_matches(wh, "threat.detected", "high") is True
    assert _webhook_matches(wh, "threat.detected", "critical") is True
    assert _webhook_matches(wh, "threat.detected", "low") is False
    assert _webhook_matches(wh, "threat.detected", "medium") is False


def test_webhook_matches_pattern_and_severity():
    from backend.api.webhooks import _webhook_matches
    wh = {"events": '["threat.*"]', "min_severity": "medium"}
    assert _webhook_matches(wh, "threat.detected", "high") is True
    assert _webhook_matches(wh, "email.received", "high") is False
    assert _webhook_matches(wh, "threat.detected", "low") is False


def test_sign_payload_empty_secret():
    from backend.api.webhooks import _sign_payload
    assert _sign_payload("", b"payload") == ""


def test_sign_payload_with_secret():
    from backend.api.webhooks import _sign_payload
    sig = _sign_payload("mysecret", b"hello")
    assert sig.startswith("sha256=")
    assert len(sig) == 7 + 64  # "sha256=" + 64 hex chars


# ── CRUD REST tests ───────────────────────────────────────────────────────────

def test_list_webhooks_empty(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/webhooks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["webhooks"] == []
    assert data["count"] == 0


def test_create_webhook(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/webhooks", json={
        "name": "Slack Alerts",
        "url":  "https://hooks.slack.com/test",
        "events": ["threat.*"],
        "min_severity": "high",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Slack Alerts"
    assert data["events"] == ["threat.*"]
    assert data["min_severity"] == "high"
    assert data["is_active"] is True
    assert "id" in data


def test_list_webhooks_after_create(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/v1/webhooks", json={"name": "WH1", "url": "https://example.com/1", "events": ["*"]})
    client.post("/api/v1/webhooks", json={"name": "WH2", "url": "https://example.com/2", "events": ["email.*"]})
    resp = client.get("/api/v1/webhooks")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_get_webhook(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/webhooks", json={
        "name": "GetTest", "url": "https://example.com/get", "events": ["*"],
    }).json()
    resp = client.get(f"/api/v1/webhooks/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_webhook_not_found(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/webhooks/does-not-exist")
    assert resp.status_code == 404


def test_update_webhook(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/webhooks", json={
        "name": "BeforeEdit", "url": "https://example.com/edit", "events": ["*"],
    }).json()
    resp = client.patch(f"/api/v1/webhooks/{created['id']}", json={"name": "AfterEdit", "min_severity": "medium"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "AfterEdit"
    assert data["min_severity"] == "medium"


def test_update_is_active(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/webhooks", json={
        "name": "Toggleable", "url": "https://example.com/toggle", "events": ["*"],
    }).json()
    resp = client.patch(f"/api/v1/webhooks/{created['id']}", json={"is_active": False})
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_delete_webhook(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/webhooks", json={
        "name": "ToDel", "url": "https://example.com/del", "events": ["*"],
    }).json()
    resp = client.delete(f"/api/v1/webhooks/{created['id']}")
    assert resp.status_code == 204
    # Should no longer appear in list
    assert client.get("/api/v1/webhooks").json()["count"] == 0


def test_delete_webhook_not_found(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.delete("/api/v1/webhooks/no-such-id")
    assert resp.status_code == 404


def test_update_no_fields_returns_400(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/webhooks", json={
        "name": "NoFields", "url": "https://example.com/nf", "events": ["*"],
    }).json()
    resp = client.patch(f"/api/v1/webhooks/{created['id']}", json={})
    assert resp.status_code == 400


# ── Delivery log tests ────────────────────────────────────────────────────────

def test_deliveries_empty(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    created = client.post("/api/v1/webhooks", json={
        "name": "DelivWH", "url": "https://example.com/deliv", "events": ["*"],
    }).json()
    resp = client.get(f"/api/v1/webhooks/{created['id']}/deliveries")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deliveries"] == []
    assert data["total"] == 0


def test_deliveries_seeded(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "backend.api.webhooks.validate_outbound_url",
        lambda url, **kw: _allowed_decision(),
    )
    # Seed a delivery record directly
    wh_id  = str(uuid.uuid4())
    del_id = str(uuid.uuid4())
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO webhooks (id, name, url, events, min_severity, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (wh_id, "SeedTest", "https://example.com", '["*"]', "low",
         datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
    )
    con.execute(
        """INSERT INTO webhook_deliveries
           (id, webhook_id, event_type, url, status_code, success, attempt, duration_ms, created_at)
           VALUES (?,?,?,?,200,1,1,120,?)""",
        (del_id, wh_id, "threat.detected", "https://example.com",
         datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    con.close()

    from backend.api import webhooks as wh
    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(wh.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get(f"/api/v1/webhooks/{wh_id}/deliveries")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["deliveries"][0]["success"] is True
    assert data["deliveries"][0]["status_code"] == 200


# ── Dispatch tests ────────────────────────────────────────────────────────────

def test_dispatch_event_calls_post_for_matching(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, monkeypatch)
    wh_id = str(uuid.uuid4())
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO webhooks (id, name, url, events, min_severity, is_active, created_at, updated_at) VALUES (?,?,?,?,?,1,?,?)",
        (wh_id, "Dispatch", "https://example.com/hook", '["*"]', "low",
         datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    con.close()

    from backend.api import webhooks as wh
    posted = []

    async def _fake_post(**kwargs):
        posted.append(kwargs["webhook_id"])

    async def _scenario():
        with patch("backend.api.webhooks._post_one", _fake_post):
            with patch("asyncio.create_task", lambda coro: asyncio.ensure_future(coro)):
                await wh.dispatch_event({
                    "type": "threat.detected",
                    "severity": "high",
                    "id": "ev-001",
                    "source": "test",
                    "payload": {},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })

    _run(_scenario())
    assert wh_id in posted


def test_dispatch_event_skips_inactive(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, monkeypatch)
    wh_id = str(uuid.uuid4())
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO webhooks (id, name, url, events, min_severity, is_active, created_at, updated_at) VALUES (?,?,?,?,?,0,?,?)",
        (wh_id, "Inactive", "https://example.com/hook", '["*"]', "low",
         datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    con.close()

    from backend.api import webhooks as wh
    posted = []

    async def _fake_post(**kwargs):
        posted.append(kwargs["webhook_id"])

    async def _scenario():
        with patch("backend.api.webhooks._post_one", _fake_post):
            with patch("asyncio.create_task", lambda coro: asyncio.ensure_future(coro)):
                await wh.dispatch_event({
                    "type": "threat.detected", "severity": "high",
                    "id": "ev-002", "source": "test", "payload": {}, "created_at": "",
                })

    _run(_scenario())
    assert len(posted) == 0


def test_dispatch_event_skips_non_matching_severity(tmp_path, monkeypatch):
    db_path = _setup_db(tmp_path, monkeypatch)
    wh_id = str(uuid.uuid4())
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO webhooks (id, name, url, events, min_severity, is_active, created_at, updated_at) VALUES (?,?,?,?,?,1,?,?)",
        (wh_id, "HighOnly", "https://example.com/high", '["*"]', "critical",
         datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    con.close()

    from backend.api import webhooks as wh
    posted = []

    async def _fake_post(**kwargs):
        posted.append(kwargs["webhook_id"])

    async def _scenario():
        with patch("backend.api.webhooks._post_one", _fake_post):
            with patch("asyncio.create_task", lambda coro: asyncio.ensure_future(coro)):
                await wh.dispatch_event({
                    "type": "email.received", "severity": "low",
                    "id": "ev-003", "source": "test", "payload": {}, "created_at": "",
                })

    _run(_scenario())
    assert len(posted) == 0
