"""Tests for the operational event bus (backend/api/event_bus.py)."""
import asyncio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _run(coro):
    return asyncio.run(coro)


def _bus(tmp_path, monkeypatch):
    """Return a fresh OperationalEventBus backed by a temp DB."""
    from backend.api import event_bus as eb
    monkeypatch.setattr(eb, "_DB_PATH", str(tmp_path / "test_events.db"))
    bus = eb.OperationalEventBus()
    return bus


# ── publish / history ──────────────────────────────────────────────────────────

def test_publish_stores_event_and_returns_id(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    async def _go():
        event_id = await bus.publish("test.ping", "pytest", {"msg": "hello"}, "low", None, {})
        await bus.stop()
        return event_id
    event_id = asyncio.run(_go())
    assert isinstance(event_id, str) and len(event_id) == 36  # UUID


def test_history_returns_published_events(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    async def _go():
        await bus.publish("ev.alpha", "src1", {"x": 1}, "low",  None, {})
        await bus.publish("ev.beta",  "src2", {"x": 2}, "high", None, {})
        history = bus.get_history(limit=50)
        await bus.stop()
        return history
    history = asyncio.run(_go())
    types = [e["type"] for e in history]
    assert "ev.alpha" in types
    assert "ev.beta" in types


def test_history_filters_by_severity(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    async def _go():
        await bus.publish("ev.low",  "src", {}, "low",  None, {})
        await bus.publish("ev.high", "src", {}, "high", None, {})
        result = bus.get_history(limit=50, severity="high")
        await bus.stop()
        return result
    high_only = asyncio.run(_go())
    assert all(e["severity"] == "high" for e in high_only)
    assert any(e["type"] == "ev.high" for e in high_only)


def test_history_filters_by_event_type(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    async def _go():
        await bus.publish("target.event", "src", {}, "low", None, {})
        await bus.publish("other.event",  "src", {}, "low", None, {})
        result = bus.get_history(limit=50, event_types=["target.event"])
        await bus.stop()
        return result
    filtered = asyncio.run(_go())
    assert all(e["type"] == "target.event" for e in filtered)


# ── subscribers ────────────────────────────────────────────────────────────────

def test_subscribe_callback_receives_published_event(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    received = []

    async def handler(event):
        received.append(event)

    async def _scenario():
        bus.subscribe("sub.test", handler)
        await bus.publish("sub.test", "src", {"key": "val"}, "low", None, {})
        # Give the dispatch loop one iteration to call the subscriber
        await asyncio.sleep(0.05)
        await bus.stop()

    asyncio.run(_scenario())
    assert len(received) == 1
    assert received[0]["payload"]["key"] == "val"


def test_subscribe_wildcard_receives_all_events(tmp_path, monkeypatch):
    bus = _bus(tmp_path, monkeypatch)
    received = []

    async def handler(event):
        received.append(event["type"])

    async def _scenario():
        bus.subscribe("*", handler)
        await bus.publish("ev.one", "src", {}, "low", None, {})
        await bus.publish("ev.two", "src", {}, "low", None, {})
        await asyncio.sleep(0.05)
        await bus.stop()

    asyncio.run(_scenario())
    assert "ev.one" in received
    assert "ev.two" in received


# ── REST endpoints ─────────────────────────────────────────────────────────────

def _client(tmp_path, monkeypatch):
    from backend.api import event_bus as eb
    from backend.auth.local_auth import require_local_auth

    monkeypatch.setattr(eb, "_DB_PATH", str(tmp_path / "test_events.db"))
    monkeypatch.setattr(eb, "_bus", eb.OperationalEventBus())

    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(eb.router, prefix="/api/v1")
    return TestClient(app)


def test_publish_endpoint_creates_event(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/api/v1/events/publish", json={
        "type": "api.test",
        "source": "test_client",
        "payload": {"n": 42},
        "severity": "medium",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "event_id" in data


def test_history_endpoint_returns_events(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/v1/events/publish", json={"type": "h.test", "source": "s", "payload": {}})
    resp = client.get("/api/v1/events/history?limit=10")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert any(e["type"] == "h.test" for e in events)


def test_stats_endpoint_returns_counts(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    client.post("/api/v1/events/publish", json={"type": "stat.x", "source": "s", "payload": {}})
    resp = client.get("/api/v1/events/stats")
    assert resp.status_code == 200
    stats = resp.json()
    assert stats["total_events"] >= 1


def test_types_endpoint_lists_known_event_types(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/api/v1/events/types")
    assert resp.status_code == 200
    names = [t["type"] for t in resp.json()["types"]]  # key is "type" not "name"
    assert "email.received" in names
    assert "threat.detected" in names


# ── emit_sync ──────────────────────────────────────────────────────────────────

def test_emit_sync_does_not_raise_outside_loop(tmp_path, monkeypatch):
    """emit_sync must silently drop if no running loop is available."""
    from backend.api import event_bus as eb
    monkeypatch.setattr(eb, "_DB_PATH", str(tmp_path / "test_events.db"))
    from backend.api.event_bus import emit_sync
    emit_sync("noop.event", "test", {"x": 1})  # should not raise
