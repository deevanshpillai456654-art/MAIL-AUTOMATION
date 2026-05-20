"""Tests for the notification center (backend/api/notifications.py)."""
import asyncio
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _setup(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = str(tmp_path / "notifications.db")
    monkeypatch.setattr(nc, "_DB_PATH", db_path)
    nc._init_db()
    # Reset subscription flag so each test can re-subscribe cleanly
    monkeypatch.setattr(nc, "_subscribed", False)
    return db_path


def _client(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    from backend.auth.local_auth import require_local_auth
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(nc.router, prefix="/api/v1")
    return TestClient(app)


def _seed(db_path: str, count: int = 3, unread: int = 3):
    con = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    for i in range(count):
        con.execute(
            """INSERT INTO notifications
               (id, event_type, title, body, severity, source, view_hint, is_read, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), "threat.detected",
             f"Notification {i}", f"Body {i}", "high", "test", "command",
             0 if i < unread else 1, now),
        )
    con.commit()
    con.close()


# ── _build_body unit tests ────────────────────────────────────────────────────

def test_build_body_alert_breach():
    from backend.api.notifications import _build_body
    body = _build_body("alert.threshold.breach", {
        "metric": "active_threats", "operator": ">", "threshold": 10, "value": 15,
    })
    assert "active_threats" in body


def test_build_body_threat():
    from backend.api.notifications import _build_body
    body = _build_body("threat.detected", {"impersonated_brand": "Amazon", "domain": "amaz0n.com"})
    assert "Amazon" in body
    assert "amaz0n.com" in body


def test_build_body_agent_anomaly():
    from backend.api.notifications import _build_body
    body = _build_body("agent.anomaly", {"description": "Queue backlog spike"})
    assert "Queue backlog spike" in body


# ── REST tests ────────────────────────────────────────────────────────────────

def test_list_empty(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["notifications"] == []
    assert data["unread"] == 0


def test_list_returns_notifications(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=5, unread=3)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(nc.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 5
    assert data["unread"] == 3


def test_unread_only_filter(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=5, unread=2)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(nc.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/notifications?unread_only=true")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_count_endpoint(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=4, unread=3)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(nc.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/notifications/count")
    assert resp.status_code == 200
    assert resp.json()["unread"] == 3


def test_status_reports_runtime_capacity_and_pressure(tmp_path, monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_NOTIFICATIONS_QUEUE_LIMIT", "4")
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=3, unread=2)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(nc.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.get("/api/v1/notifications/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "notifications"
    assert data["total"] == 3
    assert data["unread"] == 2
    assert data["capacity"] == 4
    assert data["pressure"] == pytest.approx(0.75)
    assert data["healthy"] is True


def test_mark_one_read(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)

    notif_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    con = sqlite3.connect(db_path)
    con.execute(
        "INSERT INTO notifications (id, event_type, title, severity, is_read, created_at) VALUES (?,?,?,?,0,?)",
        (notif_id, "threat.detected", "Mark Me", "high", now),
    )
    con.commit()
    con.close()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(nc.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post(f"/api/v1/notifications/{notif_id}/read")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    assert client.get("/api/v1/notifications/count").json()["unread"] == 0


def test_mark_all_read(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=5, unread=5)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(nc.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.post("/api/v1/notifications/read-all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["marked"] == 5
    assert client.get("/api/v1/notifications/count").json()["unread"] == 0


def test_delete_one(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=3, unread=3)

    con = sqlite3.connect(db_path)
    notif_id = con.execute("SELECT id FROM notifications LIMIT 1").fetchone()[0]
    con.close()

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(nc.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.delete(f"/api/v1/notifications/{notif_id}")
    assert resp.status_code == 204
    assert client.get("/api/v1/notifications").json()["count"] == 2


def test_clear_all(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)
    _seed(db_path, count=5)

    from backend.auth.local_auth import require_local_auth
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(nc.router, prefix="/api/v1")
    client = TestClient(app)

    resp = client.delete("/api/v1/notifications")
    assert resp.status_code == 204
    assert client.get("/api/v1/notifications").json()["count"] == 0


# ── Event subscriber tests ────────────────────────────────────────────────────

def test_on_event_stores_captured_type(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)

    async def _scenario():
        await nc._on_event({
            "type":       "alert.threshold.breach",
            "severity":   "high",
            "source":     "alert_rules_engine",
            "id":         str(uuid.uuid4()),
            "payload":    {"metric": "active_threats", "operator": ">", "threshold": 10, "value": 15, "message": "active_threats > 10 (current=15)"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    _run(_scenario())

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM notifications WHERE event_type='alert.threshold.breach'").fetchone()[0]
    con.close()
    assert count == 1


def test_on_event_ignores_uncaptured_type(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)

    async def _scenario():
        await nc._on_event({
            "type":       "email.classified",   # not in _CAPTURED
            "severity":   "low",
            "source":     "classifier",
            "id":         str(uuid.uuid4()),
            "payload":    {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    _run(_scenario())

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    con.close()
    assert count == 0


def test_notification_center_does_not_subscribe_when_service_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_NOTIFICATIONS", "false")
    from backend.api import event_bus
    from backend.api import notifications as nc
    _setup(tmp_path, monkeypatch)

    class FakeBus:
        def __init__(self):
            self.subscribed = []

        def subscribe(self, event_type, handler):
            self.subscribed.append((event_type, handler))

    fake_bus = FakeBus()
    monkeypatch.setattr(event_bus, "get_event_bus", lambda: fake_bus)

    nc.ensure_notification_center()

    assert fake_bus.subscribed == []
    assert nc._subscribed is False


def test_trim_keeps_max_500(tmp_path, monkeypatch):
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)

    # Insert 505 notifications directly then trim via _on_event
    con = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    for i in range(505):
        con.execute(
            "INSERT INTO notifications (id, event_type, title, severity, is_read, created_at) VALUES (?,?,?,?,0,?)",
            (str(uuid.uuid4()), "threat.detected", f"N{i}", "low", now),
        )
    con.commit()
    con.close()

    # Trigger trim
    async def _scenario():
        await nc._on_event({
            "type": "threat.detected", "severity": "high",
            "source": "test", "id": str(uuid.uuid4()),
            "payload": {}, "created_at": now,
        })

    _run(_scenario())

    con = sqlite3.connect(db_path)
    count = con.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    con.close()
    assert count <= nc._MAX_STORE


def test_trim_uses_runtime_notification_queue_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_NOTIFICATIONS_QUEUE_LIMIT", "3")
    from backend.api import notifications as nc
    db_path = _setup(tmp_path, monkeypatch)

    con = sqlite3.connect(db_path)
    now = datetime.now(timezone.utc).isoformat()
    for i in range(5):
        con.execute(
            "INSERT INTO notifications (id, event_type, title, severity, is_read, created_at) VALUES (?,?,?,?,0,?)",
            (str(uuid.uuid4()), "threat.detected", f"N{i}", "low", now),
        )
    nc._trim(con)
    con.commit()
    count = con.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    con.close()

    assert count == 3
