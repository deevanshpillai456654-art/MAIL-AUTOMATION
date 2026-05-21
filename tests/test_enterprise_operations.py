from __future__ import annotations

import logging
from pathlib import Path


REQUIRED_REPORTS = {
    "enterprise_scalability",
    "deployment_architecture",
    "service_management",
    "queue_optimization",
    "connector_hardening",
    "agent_runtime_optimization",
    "memory_optimization",
    "cpu_optimization",
    "observability_implementation",
    "logging_system",
    "error_recovery",
    "low_resource_optimization",
    "electron_enterprise_hardening",
    "database_hardening",
    "security_hardening",
    "production_operations",
    "long_term_maintainability",
    "remaining_technical_debt",
}


def test_service_state_store_persists_toggles_and_restart_protection(tmp_path):
    from backend.core.enterprise_operations import ServiceStateStore

    store = ServiceStateStore(tmp_path / "services.json")
    store.set_controls("gmail_sync", enabled=False, auto_start=False)
    store.record_failure("gmail_sync", "oauth_refresh_failed")
    store.record_failure("gmail_sync", "rate_limited")
    store.record_failure("gmail_sync", "rate_limited")

    reloaded = ServiceStateStore(tmp_path / "services.json")
    state = reloaded.get("gmail_sync")

    assert state["enabled"] is False
    assert state["auto_start"] is False
    assert state["failure_count"] == 3
    assert reloaded.restart_allowed("gmail_sync", max_failures=3) is False
    assert "restart protection" in reloaded.restart_block_reason("gmail_sync", max_failures=3)


def test_persistent_queue_exposes_dead_letters_cleanup_and_per_queue_counts(tmp_path):
    from backend.core.persistent_job_queue import PersistentJobQueue
    from backend.core.enterprise_operations import QueueInspector

    queue = PersistentJobQueue(tmp_path / "jobs.db")
    queue.enqueue("gmail.sync", {"account_id": 1}, max_attempts=1)
    queue.enqueue("outlook.sync", {"account_id": 2}, max_attempts=3)

    job = queue.lease_next("gmail.sync")
    assert job is not None
    queue.fail(job["job_id"], "provider_timeout")

    snapshot = QueueInspector(queue).snapshot()

    assert snapshot["totals"]["dead_letter"] == 1
    assert snapshot["queues"]["gmail.sync"]["dead_letter"] == 1
    assert snapshot["queues"]["outlook.sync"]["pending"] == 1
    assert snapshot["risk"] == "degraded"
    assert queue.cleanup_terminal_jobs(max_age_seconds=0) == 1


def test_persistent_queue_prevents_duplicates_limits_overflow_and_replays_dead_letters(tmp_path):
    import pytest

    from backend.core.persistent_job_queue import PersistentJobQueue, QueueOverflowError

    queue = PersistentJobQueue(tmp_path / "jobs.db")
    first = queue.enqueue_unique("gmail.sync", {"account_id": 1}, idempotency_key="acct-1", max_attempts=1, max_depth=2)
    duplicate = queue.enqueue_unique("gmail.sync", {"account_id": 1}, idempotency_key="acct-1", max_attempts=1, max_depth=2)
    second = queue.enqueue_unique("gmail.sync", {"account_id": 2}, idempotency_key="acct-2", max_attempts=1, max_depth=2)

    assert first == duplicate
    assert first != second
    assert queue.counts_by_queue()["gmail.sync"]["pending"] == 2
    with pytest.raises(QueueOverflowError):
        queue.enqueue_unique("gmail.sync", {"account_id": 3}, idempotency_key="acct-3", max_depth=2)

    job = queue.lease_next("gmail.sync")
    assert job is not None
    queue.fail(job["job_id"], "provider timeout")
    replayed = queue.requeue_dead_letter(job["job_id"])

    assert replayed is True
    assert queue.counts_by_queue()["gmail.sync"]["pending"] == 2


def test_deployment_validator_reports_environment_blockers(tmp_path, monkeypatch):
    from backend.core.enterprise_operations import DeploymentValidator

    (tmp_path / "backend").mkdir()
    (tmp_path / "desktop").mkdir()
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("OUTLOOK_CLIENT_ID", raising=False)

    report = DeploymentValidator(project_root=tmp_path, data_dir=tmp_path / "data", log_dir=tmp_path / "logs").validate()

    assert report["status"] == "blocked"
    assert "GMAIL_CLIENT_ID" in report["blockers"]
    assert "OUTLOOK_CLIENT_ID" in report["blockers"]
    assert report["targets"]["windows_11"]["status"] == "ready"
    assert report["targets"]["offline"]["status"] in {"ready", "warning"}


def test_operations_center_builds_all_required_reports(tmp_path):
    from backend.core.enterprise_operations import EnterpriseOperationsCenter

    center = EnterpriseOperationsCenter(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        environ={"AIO_RUNTIME_PROFILE": "low_resource"},
    )

    reports = center.build_reports()

    assert REQUIRED_REPORTS.issubset(reports)
    assert reports["service_management"]["controls"]["supports_enable_disable"] is True
    assert reports["queue_optimization"]["protections"]["dead_letter_queues"] is True
    assert reports["low_resource_optimization"]["profile"] == "low_resource"
    assert reports["production_operations"]["diagnostics"]["support_bundle_ready"] is True


def test_operations_center_service_restart_and_failure_controls(tmp_path):
    from backend.core.enterprise_operations import EnterpriseOperationsCenter

    center = EnterpriseOperationsCenter(project_root=tmp_path, data_dir=tmp_path / "data", log_dir=tmp_path / "logs")

    failure = center.record_service_failure("sap_connector", "credential verification failed")
    restart = center.restart_service("sap_connector")
    center.set_service_controls("sap_connector", enabled=False)
    blocked = center.restart_service("sap_connector")

    assert failure["service"]["failure_count"] == 1
    assert restart["status"] == "scheduled"
    assert restart["service"]["restart_count"] == 1
    assert blocked["status"] == "blocked"
    assert "disabled" in blocked["reason"]

    reset = center.reset_service_failures("sap_connector")
    assert reset["service"]["failure_count"] == 0


def test_operations_center_queue_recovery_cleanup_and_support_bundle(tmp_path):
    import json
    import time

    from backend.core.enterprise_operations import EnterpriseOperationsCenter

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "service.log").write_text(
        "normal line\nAuthorization: Bearer secret-token-value\npassword=unsafe\n",
        encoding="utf-8",
    )
    center = EnterpriseOperationsCenter(project_root=tmp_path, data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    center.job_queue.enqueue("gmail.sync", {"account_id": 1}, max_attempts=1)
    leased = center.job_queue.lease_next("gmail.sync", lease_seconds=1)
    assert leased is not None
    time.sleep(1.05)

    recovery = center.recover_queues()
    job = center.job_queue.lease_next("gmail.sync")
    assert job is not None
    center.job_queue.fail(job["job_id"], "provider timeout")
    cleanup = center.cleanup_queues(max_age_seconds=0)
    bundle = center.create_support_bundle()

    assert recovery["recovered_stale_leases"] == 1
    assert cleanup["deleted_terminal_jobs"] == 1
    bundle_path = tmp_path / "data" / "support_bundles" / bundle["filename"]
    assert bundle_path.exists()
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert "overview" in payload
    assert "reports" in payload
    assert "recent_logs" in payload
    assert "secret-token-value" not in json.dumps(payload).lower()
    assert "unsafe" not in json.dumps(payload).lower()


def test_deployment_profiles_cover_all_target_modes(tmp_path):
    from backend.core.enterprise_operations import EnterpriseOperationsCenter

    center = EnterpriseOperationsCenter(project_root=tmp_path, data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    profiles = center.deployment_profiles()

    for key in ("windows_11_low_resource", "smb_office", "self_hosted", "shared_office", "offline", "saas"):
        assert key in profiles
        assert "env" in profiles[key]
        assert "validation" in profiles[key]


def test_deployment_template_writer_and_update_package_diagnostics(tmp_path):
    import hashlib
    import hmac
    import json
    import zipfile

    from backend.core.enterprise_operations import EnterpriseOperationsCenter

    center = EnterpriseOperationsCenter(project_root=tmp_path, data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    template = center.write_deployment_template("windows_11_low_resource", output_dir=tmp_path / "deploy")

    assert template["status"] == "written"
    env_path = tmp_path / "deploy" / "windows_11_low_resource.env"
    assert env_path.exists()
    assert "AIO_RUNTIME_PROFILE=low_resource" in env_path.read_text(encoding="utf-8")

    patch_path = tmp_path / "patch.zip"
    with zipfile.ZipFile(patch_path, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"version": "10.0.0", "files": []}))
        zf.writestr("../escape.txt", "bad")

    diagnostics = center.validate_update_package(patch_path)

    assert diagnostics["ok"] is False
    assert diagnostics["zip_slip_protected"] is True
    assert "path traversal" in diagnostics["blockers"][0]

    key = "release-signing-key"
    payload = b"updated content"
    file_sha = hashlib.sha256(payload).hexdigest()
    manifest = {"version": "10.1.0", "files": [{"path": "backend/example.py", "sha256": file_sha}]}
    manifest["signature"] = {
        "algorithm": "hmac-sha256",
        "value": hmac.new(
            key.encode("utf-8"),
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest(),
    }
    signed_patch = tmp_path / "signed_patch.zip"
    with zipfile.ZipFile(signed_patch, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("backend/example.py", payload)

    signed_center = EnterpriseOperationsCenter(
        project_root=tmp_path,
        data_dir=tmp_path / "data-signed",
        log_dir=tmp_path / "logs-signed",
        environ={"AIO_UPDATE_SIGNING_KEY": key, "AIO_REQUIRE_SIGNED_UPDATES": "1"},
    )
    signed_diagnostics = signed_center.validate_update_package(signed_patch)

    assert signed_diagnostics["ok"] is True
    assert signed_diagnostics["signature"]["valid"] is True
    assert signed_diagnostics["file_integrity"]["verified"] == 1

    tampered_patch = tmp_path / "tampered_patch.zip"
    with zipfile.ZipFile(tampered_patch, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("backend/example.py", b"tampered")

    tampered = signed_center.validate_update_package(tampered_patch)

    assert tampered["ok"] is False
    assert tampered["file_integrity"]["mismatches"][0]["path"] == "backend/example.py"


def test_database_security_electron_and_resource_diagnostics(tmp_path):
    import sqlite3

    from backend.core.enterprise_operations import EnterpriseOperationsCenter

    db_path = tmp_path / "emails.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE emails (id INTEGER PRIMARY KEY, subject TEXT)")
        conn.execute("CREATE INDEX idx_emails_subject ON emails(subject)")

    (tmp_path / ".env").write_text("GMAIL_CLIENT_SECRET=unsafe-secret\nAPP_ENV=local\n", encoding="utf-8")
    electron_dir = tmp_path / "desktop" / "electron"
    electron_dir.mkdir(parents=True)
    (electron_dir / "main.js").write_text(
        "new BrowserWindow({webPreferences:{contextIsolation:true,sandbox:true,nodeIntegration:false}});",
        encoding="utf-8",
    )

    center = EnterpriseOperationsCenter(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        environ={"DB_PATH": str(db_path), "API_HOST": "127.0.0.1"},
    )

    database = center.database_diagnostics()
    security = center.security_posture()
    electron = center.electron_diagnostics()
    pressure = center.resource_pressure(cpu_percent=92.0, memory_available_mb=384.0, queue_pending=1200)

    assert database["integrity_check"] == "ok"
    assert database["index_count"] >= 1
    assert security["loopback_bound"] is True
    assert security["secret_key_count"] == 1
    assert security["secret_values_exposed"] is False
    assert electron["context_isolation"] is True
    assert electron["sandbox"] is True
    assert electron["node_integration_disabled"] is True
    assert pressure["level"] == "critical"
    assert "pause noncritical connectors" in " ".join(pressure["actions"]).lower()


def test_connector_inventory_and_agent_runtime_diagnostics(tmp_path):
    from backend.core.enterprise_operations import EnterpriseOperationsCenter

    connector_root = tmp_path / "platform" / "connectors-panel" / "connectors"
    for name in ("gmail", "outlook", "sap", "whatsapp"):
        path = connector_root / name
        path.mkdir(parents=True)
        (path / "connector.py").write_text("# connector\n", encoding="utf-8")
    plugin = tmp_path / "platform" / "plugins" / "tally"
    plugin.mkdir(parents=True)
    (plugin / "plugin.json").write_text('{"id":"tally","permissions":["queue","credentials"]}', encoding="utf-8")
    communication_plugin = tmp_path / "platform" / "plugins" / "communication"
    communication_plugin.mkdir(parents=True)
    (communication_plugin / "plugin.json").write_text(
        '{"id":"Email + WhatsApp Unified Communication","permissions":["queue"]}',
        encoding="utf-8",
    )

    center = EnterpriseOperationsCenter(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        environ={"AIO_RUNTIME_PROFILE": "low_resource"},
    )

    connectors = center.connector_inventory()
    agents = center.agent_runtime_diagnostics()

    assert connectors["count"] == 6
    assert connectors["connectors"]["gmail"]["isolated"] is True
    assert connectors["connectors"]["tally"]["manifest_present"] is True
    assert "email_whatsapp_unified_communication" in connectors["connectors"]
    assert connectors["required_connectors"]["outlook"]["present"] is True
    assert connectors["required_connectors"]["zoho"]["present"] is False
    assert connectors["connectors"]["sap"]["retry_protected"] is True
    assert agents["profile"] == "low_resource"
    assert agents["disabled_count"] > 0
    assert agents["idle_resource_policy"] == "disabled_agents_do_not_autostart"


def test_operations_metrics_export_is_scrapeable_and_redacted(tmp_path):
    from backend.core.enterprise_operations import EnterpriseOperationsCenter

    center = EnterpriseOperationsCenter(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        environ={"PROMETHEUS_ENABLED": "1", "SENTRY_DSN": "https://secret@example.test/1"},
    )
    center.job_queue.enqueue("gmail.sync", {"account_id": 1})

    diagnostics = center.observability()
    metrics = center.operations_metrics_text()

    assert diagnostics["metrics_export"]["prometheus_text"] is True
    assert diagnostics["metrics_export"]["external_apm_configured"] is True
    assert "aio_queue_jobs_total{status=\"pending\"}" in metrics
    assert "aio_connectors_total" in metrics
    assert "secret@example" not in metrics


def test_final_phase_readiness_gates_close_platform_debt(tmp_path):
    from backend.core.enterprise_operations import EnterpriseOperationsCenter

    backup_path = tmp_path / "backups"
    backup_path.mkdir()
    center = EnterpriseOperationsCenter(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        log_dir=tmp_path / "logs",
        environ={
            "APP_ENV": "production",
            "QUEUE_BACKEND": "postgres",
            "DATABASE_URL": "postgresql://user:pass@db.local/app",
            "AIO_UPDATE_SIGNING_KEY": "release-signing-key",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otel.example.test/v1/traces",
            "BACKUP_PATH": str(backup_path),
        },
    )

    queue_backend = center.queue_backend_diagnostics()
    sync_transport = center.sync_transport_diagnostics()
    readiness = center.production_readiness_gates()
    reports = center.build_reports()

    assert queue_backend["external_queue_ready"] is True
    assert queue_backend["capabilities"]["postgres_skip_locked"] is True
    assert sync_transport["async_transport_available"] is True
    assert sync_transport["high_volume_providers"]["gmail"]["async_client_ready"] is True
    assert sync_transport["high_volume_providers"]["outlook"]["async_client_ready"] is True
    assert readiness["status"] == "ready"
    assert reports["remaining_technical_debt"]["platform_items"] == []


def test_provisioning_pack_generates_non_secret_saas_artifacts(tmp_path):
    import json

    from backend.core.enterprise_operations import EnterpriseOperationsCenter

    center = EnterpriseOperationsCenter(project_root=tmp_path, data_dir=tmp_path / "data", log_dir=tmp_path / "logs")
    pack = center.write_provisioning_pack("saas", output_dir=tmp_path / "deploy")

    assert pack["status"] == "written"
    assert pack["environment_provisioning_covered"] is True
    assert "AIO_UPDATE_SIGNING_KEY" in pack["required_secrets"]
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" in pack["required_endpoints"]
    env_path = tmp_path / "deploy" / "saas.provisioning.env.example"
    manifest_path = tmp_path / "deploy" / "saas.provisioning.json"
    assert env_path.exists()
    assert manifest_path.exists()
    env_text = env_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "QUEUE_BACKEND=postgres" in env_text
    assert "AIO_UPDATE_SIGNING_KEY=<set-in-secret-manager>" in env_text
    assert "release-signing-key" not in env_text
    assert manifest["profile"] == "saas"
    assert manifest["secret_values_included"] is False
    assert "saas_queue_backend" in manifest["readiness_gates"]

    reports = center.build_reports()
    assert reports["production_operations"]["deployment_provisioning_pack"]["environment_provisioning_covered"] is True
    assert reports["remaining_technical_debt"]["status"] == "platform_complete"
    assert reports["remaining_technical_debt"]["platform_items"] == []


def test_async_provider_transport_supports_pooled_json_requests(monkeypatch):
    import asyncio

    from backend.sync.async_provider_transport import AsyncProviderTransport

    class FakeResponse:
        ok = True
        content = b'{"ok": true}'
        status_code = 200
        text = ""
        reason_phrase = "OK"

        def json(self):
            return {"ok": True}

    class FakeClient:
        async def request(self, method, url, headers=None, timeout=None, **kwargs):
            return FakeResponse()

    async def fake_get_http_client():
        return FakeClient()

    monkeypatch.setattr("backend.sync.async_provider_transport.get_http_client", fake_get_http_client)
    transport = AsyncProviderTransport(
        provider="gmail",
        api_base="https://provider.example.test",
        headers={"Authorization": "Bearer token"},
    )

    result = asyncio.run(transport.request_json("GET", "/messages"))

    assert result == {"ok": True}
    assert transport.capabilities()["pooled_async_http"] is True


def test_logging_configuration_uses_rotation(tmp_path):
    from logging.handlers import RotatingFileHandler
    from backend.app.logging_config import configure_logging

    logger = logging.getLogger("enterprise-ops-test")
    logger.handlers.clear()

    log_file = configure_logging(tmp_path, "INFO", root_logger=logger)

    assert log_file == tmp_path / "service.log"
    assert any(isinstance(handler, RotatingFileHandler) for handler in logger.handlers)
