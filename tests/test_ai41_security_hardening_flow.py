from pathlib import Path


def test_security_local_runtime_hardening_status_detects_loopback(monkeypatch):
    from backend.api import security

    monkeypatch.setattr(security.config, "API_HOST", "127.0.0.1", raising=False)
    monkeypatch.setattr(security.config, "API_PORT", 4597, raising=False)
    monkeypatch.delenv("ALLOW_EXTERNAL_BIND", raising=False)

    status = security.local_runtime_hardening_status()

    assert status["local_only"]["passed"] is True
    assert status["local_only"]["bind_host"] == "127.0.0.1"
    assert status["firewall"]["port"] == 4597
    assert "INTEMO Local Dashboard" in status["firewall"]["setup_command"]


def test_security_local_runtime_hardening_status_flags_external_bind(monkeypatch):
    from backend.api import security

    monkeypatch.setattr(security.config, "API_HOST", "0.0.0.0", raising=False)
    monkeypatch.setenv("ALLOW_EXTERNAL_BIND", "1")

    status = security.local_runtime_hardening_status()

    assert status["status"] == "review_required"
    assert status["local_only"]["passed"] is False
    assert "Bind the desktop runtime to 127.0.0.1" in status["local_only"]["remediation"]


def test_security_local_runtime_endpoint_and_setup_page_expose_check_flow(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.auth.local_auth import get_local_token
    from backend.api import security
    from backend.main import app

    monkeypatch.setattr(security.config, "API_HOST", "127.0.0.1", raising=False)
    client = TestClient(app)
    client.post("/api/v1/session/bootstrap", headers={"X-Local-Token": get_local_token()})
    response = client.get("/api/v1/security/local-runtime")
    html = (Path(__file__).resolve().parents[1] / "backend" / "dashboard" / "setup.html").read_text(encoding="utf-8")

    assert response.status_code == 200
    assert response.json()["local_only"]["passed"] is True
    assert "securityHardeningTag" in html
    assert "loadHardeningStatus" in html
    assert "/security/local-runtime" in html
    assert "Windows Firewall" in html
