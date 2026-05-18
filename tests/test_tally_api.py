from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    from backend.api import tally
    from backend.auth.local_auth import require_local_auth

    monkeypatch.setattr(tally, "TALLY_DB_PATH", str(tmp_path / "tally.db"))
    tally.init_tally_db()
    app = FastAPI()
    app.dependency_overrides[require_local_auth] = lambda: None
    app.include_router(tally.router, prefix="/api/v1")
    return TestClient(app)


def test_tally_connect_status_and_disconnect(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    payload = {
        "mode": "localhost",
        "host": "localhost",
        "port": 9000,
        "company_name": "Acme Books",
        "username": "admin",
        "password": "secret",
        "enable_xml_api": True,
    }
    response = client.post("/api/v1/tally/connect", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "connected"
    assert data["company_name"] == "Acme Books"
    assert data["credentials_encrypted"] is True

    status = client.get("/api/v1/tally/status").json()
    assert status["connection"]["company_name"] == "Acme Books"
    assert status["connection"]["mode"] == "localhost"

    assert client.post("/api/v1/tally/disconnect").json()["status"] == "disconnected"


def test_tally_core_endpoints_return_enterprise_shapes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    assert client.get("/api/v1/tally/discover").status_code == 200
    assert "instances" in client.get("/api/v1/tally/discover").json()
    assert "companies" in client.get("/api/v1/tally/companies").json()
    assert "ledgers" in client.get("/api/v1/tally/ledgers").json()
    assert "vouchers" in client.get("/api/v1/tally/vouchers").json()
    assert "items" in client.get("/api/v1/tally/inventory").json()
    assert "reports" in client.get("/api/v1/tally/gst").json()
    assert "analytics" in client.get("/api/v1/tally/analytics").json()
    assert "logs" in client.get("/api/v1/tally/logs").json()


def test_tally_manual_sync_creates_job_and_events(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post("/api/v1/tally/sync", json={"sync_type": "manual", "company_name": "Acme Books"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "queued"
    assert data["job"]["company_name"] == "Acme Books"
    assert "tally.sync.started" in data["events"]
