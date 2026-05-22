import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_security_red_team_gate_targets_current_backend_layout():
    from scripts import security_red_team_check

    paths = {check["id"]: check["path"] for check in security_red_team_check.CHECKS}

    assert paths["SEC-001"] == "backend/api/middleware.py"
    assert paths["SEC-002"] == "backend/api/middleware.py"
    assert paths["SEC-003"] == "backend/api/webhook_manager.py"
    assert paths["SEC-004"] == "backend/api/frontend_runtime.py"
    assert paths["SEC-005"] == "backend/api/security.py"
    assert paths["SEC-007"] == "backend/dashboard/realtime/ws_client.js"
    assert paths["SEC-008"] == "backend/app/middleware.py"
    assert all((ROOT / path).exists() for path in paths.values())
    assert security_red_team_check.run_checks()["ok"] is True


def test_security_red_team_gate_cli_passes_json():
    proc = subprocess.run(
        [sys.executable, "-B", "scripts/security_red_team_check.py", "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert json.loads(proc.stdout)["ok"] is True


def test_production_readiness_gate_imports_backend_core_modules():
    script = (ROOT / "scripts" / "production_readiness_check.py").read_text(encoding="utf-8")
    assert '"scripts/dashboard_visual_smoke.py", "--timeout-ms", "60000"' in script

    proc = subprocess.run(
        [
            sys.executable,
            "-B",
            "scripts/production_readiness_check.py",
            "--target",
            "97",
            "--profile",
            "local-first",
            "--json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=180,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result["profile"] == "local-first"
    assert result["status"] == "ready"
    assert result["score"] >= 97
