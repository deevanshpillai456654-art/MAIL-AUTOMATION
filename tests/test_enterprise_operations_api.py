from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("AIO_RUNTIME_PROFILE", "low_resource")
    from backend.api.enterprise_operations import router as ops_router
    from backend.api.session import router as session_router

    app = FastAPI()
    app.state.enterprise_operations_paths = {
        "project_root": tmp_path,
        "data_dir": tmp_path / "data",
        "log_dir": tmp_path / "logs",
    }
    app.include_router(session_router, prefix="/api/v1")
    app.include_router(ops_router, prefix="/api/v1")
    client = TestClient(app)
    client.post("/api/v1/session/bootstrap")
    return client


def test_enterprise_operations_overview_and_reports(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    overview = client.get("/api/v1/enterprise-operations/overview")
    reports = client.get("/api/v1/enterprise-operations/reports")

    assert overview.status_code == 200
    assert overview.json()["runtime"]["profile"] == "low_resource"
    assert "service_management" in reports.json()["reports"]
    assert "remaining_technical_debt" in reports.json()["reports"]


def test_enterprise_operations_service_controls_are_persisted(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/v1/enterprise-operations/services/gmail_sync/controls",
        json={"enabled": False, "auto_start": False},
    )
    services = client.get("/api/v1/enterprise-operations/services")

    assert response.status_code == 200
    assert response.json()["service"]["enabled"] is False
    assert services.json()["overrides"]["gmail_sync"]["auto_start"] is False


def test_enterprise_operations_validation_endpoints(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    queue = client.get("/api/v1/enterprise-operations/queues")
    deployment = client.get("/api/v1/enterprise-operations/deployment/validate")
    updates = client.get("/api/v1/enterprise-operations/updates/diagnostics")
    observability = client.get("/api/v1/enterprise-operations/observability")
    database = client.get("/api/v1/enterprise-operations/database")
    security = client.get("/api/v1/enterprise-operations/security")
    electron = client.get("/api/v1/enterprise-operations/electron")
    resources = client.get("/api/v1/enterprise-operations/resources")
    connectors = client.get("/api/v1/enterprise-operations/connectors")
    agents = client.get("/api/v1/enterprise-operations/agents")
    metrics = client.get("/api/v1/enterprise-operations/metrics")
    queue_backend = client.get("/api/v1/enterprise-operations/queues/backend")
    sync_transport = client.get("/api/v1/enterprise-operations/sync/transport")
    production = client.get("/api/v1/enterprise-operations/production/readiness")
    provisioning = client.post("/api/v1/enterprise-operations/production/provisioning-pack/saas")

    assert queue.status_code == 200
    assert deployment.status_code == 200
    assert updates.status_code == 200
    assert updates.json()["safe_update_flow"] is True
    assert observability.status_code == 200
    assert "resource_monitoring" in observability.json()
    assert database.status_code == 200
    assert "integrity_check" in database.json()
    assert security.status_code == 200
    assert "loopback_bound" in security.json()
    assert electron.status_code == 200
    assert "node_integration_disabled" in electron.json()
    assert resources.status_code == 200
    assert "level" in resources.json()
    assert connectors.status_code == 200
    assert "connectors" in connectors.json()
    assert agents.status_code == 200
    assert "idle_resource_policy" in agents.json()
    assert metrics.status_code == 200
    assert "aio_queue_jobs_total" in metrics.text
    assert metrics.headers["content-type"].startswith("text/plain")
    assert queue_backend.status_code == 200
    assert "external_queue_ready" in queue_backend.json()
    assert sync_transport.status_code == 200
    assert sync_transport.json()["async_transport_available"] is True
    assert production.status_code == 200
    assert "gates" in production.json()
    assert provisioning.status_code == 200
    assert provisioning.json()["environment_provisioning_covered"] is True


def test_enterprise_operations_action_endpoints(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    failure = client.post(
        "/api/v1/enterprise-operations/services/slack_connector/failure",
        json={"error": "rate limited"},
    )
    reset = client.post("/api/v1/enterprise-operations/services/slack_connector/failures/reset")
    restart = client.post("/api/v1/enterprise-operations/services/slack_connector/restart")
    profiles = client.get("/api/v1/enterprise-operations/deployment/profiles")
    template = client.post(
        "/api/v1/enterprise-operations/deployment/profiles/windows_11_low_resource/template"
    )
    recovered = client.post("/api/v1/enterprise-operations/queues/recover")
    cleanup = client.post("/api/v1/enterprise-operations/queues/cleanup", json={"max_age_seconds": 0})
    bundle = client.post("/api/v1/enterprise-operations/support/bundle")

    assert failure.status_code == 200
    assert failure.json()["service"]["failure_count"] == 1
    assert reset.status_code == 200
    assert reset.json()["service"]["failure_count"] == 0
    assert restart.status_code == 200
    assert restart.json()["status"] == "scheduled"
    assert "saas" in profiles.json()["profiles"]
    assert template.status_code == 200
    assert template.json()["filename"] == "windows_11_low_resource.env"
    assert recovered.status_code == 200
    assert "recovered_stale_leases" in recovered.json()
    assert cleanup.status_code == 200
    assert "deleted_terminal_jobs" in cleanup.json()
    assert bundle.status_code == 200
    assert bundle.json()["filename"].endswith(".json")


def test_enterprise_updates_validate_uses_hardened_update_diagnostics(tmp_path, monkeypatch):
    import hashlib
    import hmac
    import io
    import json
    import zipfile

    monkeypatch.setenv("AIO_UPDATE_SIGNING_KEY", "release-key")
    monkeypatch.setenv("AIO_REQUIRE_SIGNED_UPDATES", "1")
    from backend.api.enterprise_updates import router as updates_router
    from backend.api.session import router as session_router

    payload = b"release"
    manifest = {
        "version": "10.2.0",
        "files": [{"path": "backend/release.py", "sha256": hashlib.sha256(payload).hexdigest()}],
    }
    manifest["signature"] = {
        "algorithm": "hmac-sha256",
        "value": hmac.new(
            b"release-key",
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest(),
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("backend/release.py", payload)
    archive.seek(0)

    app = FastAPI()
    app.include_router(session_router, prefix="/api/v1")
    app.include_router(updates_router, prefix="/api/v1")
    client = TestClient(app)
    client.post("/api/v1/session/bootstrap")

    response = client.post(
        "/api/v1/updates/validate",
        files={"file": ("patch.zip", archive.getvalue(), "application/zip")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["signature"]["valid"] is True
    assert body["file_integrity"]["verified"] == 1
