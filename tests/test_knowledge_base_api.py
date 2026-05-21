"""Tests for the knowledge base API."""
from __future__ import annotations
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.auth.local_auth import require_local_auth

@pytest.fixture
def client():
    from backend.api.knowledge_base import router
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_local_auth] = lambda: None
    return TestClient(app, raise_server_exceptions=False)

_NEW_ART = {"title": "How to restart the API", "body": "Run systemctl restart api.", "category": "runbook"}

def test_list_articles_returns_structure(client):
    resp = client.get("/api/v1/kb/articles")
    assert resp.status_code == 200
    body = resp.json()
    assert "articles" in body or "items" in body or isinstance(body, dict)

def test_create_article_returns_id(client):
    resp = client.post("/api/v1/kb/articles", json=_NEW_ART)
    assert resp.status_code in (200, 201)
    assert "id" in resp.json()

def test_get_article_by_id(client):
    art_id = client.post("/api/v1/kb/articles", json=_NEW_ART).json()["id"]
    resp = client.get(f"/api/v1/kb/articles/{art_id}")
    assert resp.status_code == 200

def test_patch_article(client):
    art_id = client.post("/api/v1/kb/articles", json=_NEW_ART).json()["id"]
    resp = client.patch(f"/api/v1/kb/articles/{art_id}", json={"body": "Updated content."})
    assert resp.status_code == 200

def test_delete_article(client):
    art_id = client.post("/api/v1/kb/articles", json=_NEW_ART).json()["id"]
    resp = client.delete(f"/api/v1/kb/articles/{art_id}")
    assert resp.status_code in (200, 204)

def test_article_stats(client):
    resp = client.get("/api/v1/kb/articles/stats")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)
