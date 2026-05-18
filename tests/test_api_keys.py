"""Tests for backend/api/api_keys.py"""
from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.api_keys as ak


def _setup(tmp_path: Path, monkeypatch):
    db = str(tmp_path / "api_keys.db")
    monkeypatch.setattr(ak, "_DB_PATH", db)
    ak._init_db()
    return db


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(ak.router)
    app.dependency_overrides[ak.require_local_auth] = lambda: "test"
    return TestClient(app, raise_server_exceptions=True)


def _future_ts(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past_ts(days: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


# ── Key generation ────────────────────────────────────────────────────────────

def test_generate_key_format():
    full, prefix, digest = ak._generate_key()
    assert full.startswith("ak_")
    assert len(full) == 51                      # "ak_" + 48 hex chars
    assert prefix.endswith("...")
    assert prefix.startswith("ak_")
    assert len(digest) == 64                    # SHA-256 hex


def test_generate_key_unique():
    k1, _, _ = ak._generate_key()
    k2, _, _ = ak._generate_key()
    assert k1 != k2


def test_hash_key_deterministic():
    full, _, digest = ak._generate_key()
    assert ak._hash_key(full) == digest


# ── verify_api_key ────────────────────────────────────────────────────────────

def test_verify_valid_key(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(ak.router)
    app.dependency_overrides[ak.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    full_key = c.post("/api-keys", json={"name": "Test"}).json()["key"]
    result = ak.verify_api_key(full_key)
    assert result is not None
    assert result["name"] == "Test"
    assert "key_hash" not in result


def test_verify_invalid_key_returns_none(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert ak.verify_api_key("ak_notarealkey00000000000000000000000000000000000000") is None


def test_verify_wrong_prefix_returns_none(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert ak.verify_api_key("sk_something") is None


def test_verify_empty_returns_none(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert ak.verify_api_key("") is None


def test_verify_disabled_key_returns_none(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(ak.router)
    app.dependency_overrides[ak.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    r = c.post("/api-keys", json={"name": "Disabled", "enabled": False})
    full_key = r.json()["key"]
    assert ak.verify_api_key(full_key) is None


def test_verify_expired_key_returns_none(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(ak.router)
    app.dependency_overrides[ak.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    # Create with future expiry, then manually backdate it
    r = c.post("/api-keys", json={"name": "Expiring", "expires_at": _future_ts(1)})
    key_id  = r.json()["id"]
    full_key = r.json()["key"]
    con = sqlite3.connect(db)
    con.execute("UPDATE api_keys SET expires_at=? WHERE id=?", (_past_ts(1), key_id))
    con.commit()
    con.close()
    assert ak.verify_api_key(full_key) is None


def test_verify_bumps_use_count(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(ak.router)
    app.dependency_overrides[ak.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    r = c.post("/api-keys", json={"name": "Counter"})
    key_id   = r.json()["id"]
    full_key = r.json()["key"]
    ak.verify_api_key(full_key)
    ak.verify_api_key(full_key)
    con = sqlite3.connect(db)
    count = con.execute("SELECT use_count FROM api_keys WHERE id=?", (key_id,)).fetchone()[0]
    con.close()
    assert count == 2


# ── _validate_scopes ──────────────────────────────────────────────────────────

def test_validate_scopes_valid():
    ak._validate_scopes(["read", "write"])  # no exception


def test_validate_scopes_invalid():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        ak._validate_scopes(["read", "superpower"])
    assert exc_info.value.status_code == 400


# ── _validate_expires_at ──────────────────────────────────────────────────────

def test_validate_expires_at_none_ok():
    ak._validate_expires_at(None)  # no exception


def test_validate_expires_at_future_ok():
    ak._validate_expires_at(_future_ts(30))


def test_validate_expires_at_past_raises():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        ak._validate_expires_at(_past_ts(1))


def test_validate_expires_at_bad_format_raises():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        ak._validate_expires_at("not-a-date")


# ── REST: list ────────────────────────────────────────────────────────────────

def test_list_keys_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api-keys")
    assert r.status_code == 200
    assert r.json()["keys"] == []
    assert r.json()["total"] == 0


def test_list_keys_returns_item(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api-keys", json={"name": "MyKey"})
    r = c.get("/api-keys")
    items = r.json()["keys"]
    assert len(items) == 1
    assert items[0]["name"] == "MyKey"
    assert "key_hash" not in items[0]


def test_list_keys_hash_never_exposed(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api-keys", json={"name": "K"})
    r = c.get("/api-keys")
    for k in r.json()["keys"]:
        assert "key_hash" not in k


def test_list_keys_enabled_only_filter(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api-keys", json={"name": "Active"})
    c.post("/api-keys", json={"name": "Disabled", "enabled": False})
    r = c.get("/api-keys?enabled_only=true")
    items = r.json()["keys"]
    assert all(k["enabled"] for k in items)
    assert len(items) == 1


# ── REST: create ──────────────────────────────────────────────────────────────

def test_create_key_201(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api-keys", json={"name": "CI Key"})
    assert r.status_code == 201
    data = r.json()
    assert "key" in data
    assert data["key"].startswith("ak_")
    assert "warning" in data


def test_create_key_returns_full_key_once(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api-keys", json={"name": "K"})
    full_key = r.json()["key"]
    assert len(full_key) == 51


def test_create_key_with_scopes(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api-keys", json={"name": "K", "scopes": ["read", "webhooks"]})
    assert r.status_code == 201
    key_id = r.json()["id"]
    detail = c.get(f"/api-keys/{key_id}").json()
    assert "read" in detail["scopes"]
    assert "webhooks" in detail["scopes"]


def test_create_key_invalid_scope(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api-keys", json={"name": "K", "scopes": ["teleport"]})
    assert r.status_code == 400


def test_create_key_with_expiry(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api-keys", json={"name": "K", "expires_at": _future_ts(30)})
    assert r.status_code == 201


def test_create_key_past_expiry_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api-keys", json={"name": "K", "expires_at": _past_ts(1)})
    assert r.status_code == 400


# ── REST: stats ───────────────────────────────────────────────────────────────

def test_stats_empty(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api-keys/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    assert data["total_calls"] == 0


def test_stats_counts(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    c.post("/api-keys", json={"name": "A"})
    c.post("/api-keys", json={"name": "B", "enabled": False})
    r = c.get("/api-keys/stats")
    data = r.json()
    assert data["total"]    == 2
    assert data["enabled"]  == 1
    assert data["disabled"] == 1


# ── REST: get ─────────────────────────────────────────────────────────────────

def test_get_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    key_id = c.post("/api-keys", json={"name": "Fetch Me"}).json()["id"]
    r = c.get(f"/api-keys/{key_id}")
    assert r.status_code == 200
    assert r.json()["name"] == "Fetch Me"
    assert "key_hash" not in r.json()
    assert isinstance(r.json()["scopes"], list)


def test_get_key_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/api-keys/nonexistent")
    assert r.status_code == 404


# ── REST: patch ───────────────────────────────────────────────────────────────

def test_patch_key_name(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    key_id = c.post("/api-keys", json={"name": "Old"}).json()["id"]
    r = c.patch(f"/api-keys/{key_id}", json={"name": "New"})
    assert r.status_code == 200
    assert c.get(f"/api-keys/{key_id}").json()["name"] == "New"


def test_patch_key_disable(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    key_id = c.post("/api-keys", json={"name": "X"}).json()["id"]
    c.patch(f"/api-keys/{key_id}", json={"enabled": False})
    assert c.get(f"/api-keys/{key_id}").json()["enabled"] == 0


def test_patch_key_no_fields(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    key_id = c.post("/api-keys", json={"name": "X"}).json()["id"]
    r = c.patch(f"/api-keys/{key_id}", json={})
    assert r.status_code == 400


def test_patch_key_not_found(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.patch("/api-keys/ghost", json={"name": "Y"})
    assert r.status_code == 404


def test_patch_invalid_scope(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    key_id = c.post("/api-keys", json={"name": "X"}).json()["id"]
    r = c.patch(f"/api-keys/{key_id}", json={"scopes": ["badscope"]})
    assert r.status_code == 400


# ── REST: delete ──────────────────────────────────────────────────────────────

def test_delete_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    key_id = c.post("/api-keys", json={"name": "Del"}).json()["id"]
    r = c.delete(f"/api-keys/{key_id}")
    assert r.status_code == 204
    assert c.get(f"/api-keys/{key_id}").status_code == 404


def test_deleted_key_fails_verification(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(ak.router)
    app.dependency_overrides[ak.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    r = c.post("/api-keys", json={"name": "Del"})
    key_id   = r.json()["id"]
    full_key = r.json()["key"]
    assert ak.verify_api_key(full_key) is not None
    c.delete(f"/api-keys/{key_id}")
    assert ak.verify_api_key(full_key) is None


# ── REST: rotate ──────────────────────────────────────────────────────────────

def test_rotate_key_returns_new_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api-keys", json={"name": "Rotate Me"})
    key_id   = r.json()["id"]
    old_key  = r.json()["key"]
    r2 = c.post(f"/api-keys/{key_id}/rotate")
    assert r2.status_code == 201
    new_key = r2.json()["key"]
    assert new_key.startswith("ak_")
    assert new_key != old_key


def test_rotate_key_invalidates_old_key(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(ak.router)
    app.dependency_overrides[ak.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    r = c.post("/api-keys", json={"name": "Rotate"})
    key_id   = r.json()["id"]
    old_key  = r.json()["key"]
    c.post(f"/api-keys/{key_id}/rotate")
    assert ak.verify_api_key(old_key) is None


def test_rotate_new_key_is_valid(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(ak.router)
    app.dependency_overrides[ak.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    key_id = c.post("/api-keys", json={"name": "Rotate"}).json()["id"]
    new_key = c.post(f"/api-keys/{key_id}/rotate").json()["key"]
    assert ak.verify_api_key(new_key) is not None


def test_rotate_resets_use_count(tmp_path, monkeypatch):
    db = _setup(tmp_path, monkeypatch)
    app = FastAPI()
    app.include_router(ak.router)
    app.dependency_overrides[ak.require_local_auth] = lambda: "test"
    c = TestClient(app, raise_server_exceptions=True)
    r = c.post("/api-keys", json={"name": "Rotate"})
    key_id = r.json()["id"]
    old_key = r.json()["key"]
    ak.verify_api_key(old_key)
    ak.verify_api_key(old_key)
    c.post(f"/api-keys/{key_id}/rotate")
    con = sqlite3.connect(db)
    count = con.execute("SELECT use_count FROM api_keys WHERE id=?", (key_id,)).fetchone()[0]
    con.close()
    assert count == 0


def test_rotate_nonexistent_key(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api-keys/no-such-key/rotate")
    assert r.status_code == 404
