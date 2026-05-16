from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from backend.auth.universal_auth_engine import UniversalEmailAuthEngine


def test_oauth_uses_single_validator_and_never_requires_password():
    result = UniversalEmailAuthEngine().validate_account_payload({
        "email": "person@gmail.com",
        "provider": "gmail",
        "connection_method": "oauth",
        "password": "legacy-field-ignored",
        "app_password": "legacy-app-field-ignored",
        "imap_host": "imap.should-not-run.example",
    }, base_url="http://127.0.0.1:4597")
    assert result["validate_oauth_tokens_only"] is True
    assert result["password_required"] is False
    assert result["app_password_required"] is False
    assert result["imap_required"] is False
    assert result["smtp_required"] is False


def test_manual_imap_path_is_the_only_password_requiring_path():
    missing = UniversalEmailAuthEngine().validate_account_payload({
        "email": "person@icloud.com",
        "provider": "icloud",
        "connection_method": "app_password",
    })
    assert missing["ok"] is False
    assert missing["password_required"] is True
    assert "password" in missing["errors"]
    ok = UniversalEmailAuthEngine().validate_account_payload({
        "email": "person@icloud.com",
        "provider": "icloud",
        "connection_method": "app_password",
        "app_password": "app-specific-secret",
    })
    assert ok["ok"] is True
    assert ok["validate_oauth_tokens_only"] is False


def test_legacy_cleanup_removed_duplicate_artifacts():
    removed_dirs = [
        "internal_docs/legacy_dashboard_pages/dist",
        "internal_docs/legacy_extension_packages/dist",
        "internal_docs/runtime_internal_docs/dist",
        "internal_docs/reports/runtime_reports",
        "local_service",
        "source",
        "runtime",
    ]
    assert all(not (ROOT / rel).exists() for rel in removed_dirs)
    assert not any(str(p.relative_to(ROOT)).startswith("internal_docs/") for p in ROOT.rglob("*.zip"))


def test_canonical_dashboard_and_config_exist():
    assert (ROOT / "backend" / "dashboard" / "index.html").exists()
    assert (ROOT / "backend" / "config" / "__init__.py").exists()
    assert (ROOT / "backend" / "auth" / "routes.py").exists()
    assert (ROOT / "requirements.txt").exists()
    assert not (ROOT / "backend" / "config.py").exists(), "Old config.py must not exist alongside config/ package"
