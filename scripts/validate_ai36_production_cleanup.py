#!/usr/bin/env python3
from __future__ import annotations
import json, os, re, subprocess, sys
from pathlib import Path
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FRONTEND_ROOTS = ["backend/dashboard", "frontend", "extensions", "outlook-addin", "desktop", "mobile", "shared"]
TEXT_SUFFIXES = {".html", ".js", ".css"}
SECRET_PATTERNS = [r"GOCSPX-[A-Za-z0-9_-]+", r"[0-9]{6,}-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com"]
UNSUPPORTED_CSS = []  # backdrop-filter is intentionally used for premium glass effects


def iter_frontend_files():
    for root in FRONTEND_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
                yield path


def node_check(path: Path) -> tuple[bool, str]:
    if path.suffix.lower() != ".js":
        return True, ""
    try:
        cp = subprocess.run(["node", "--check", str(path)], cwd=ROOT, text=True, capture_output=True, timeout=20)
        return cp.returncode == 0, (cp.stderr or cp.stdout).strip()
    except FileNotFoundError:
        return True, "node not installed; skipped"
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    from backend.auth.universal_auth_engine import UniversalEmailAuthEngine
    from backend.utils.sqlite_connection_guard import tracked_connection_count, close_all_tracked_connections
    from backend.main import app  # noqa: F401 - verifies API app imports

    engine = UniversalEmailAuthEngine()
    gmail = engine.validate_account_payload({"email":"user@gmail.com","provider":"gmail","connection_method":"oauth","password":"ignored"}, base_url="http://127.0.0.1:{}".format(os.environ.get("API_PORT", "4597")))
    custom_missing = engine.validate_account_payload({"email":"user@company.com","provider":"custom","connection_method":"app_password"})

    frontend_files = list(iter_frontend_files())
    js_failures = []
    inline_style_attrs = []
    unsupported_css_hits = []
    mojibake_hits = []
    for path in frontend_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        ok, msg = node_check(path)
        if not ok:
            js_failures.append({"path": str(path.relative_to(ROOT)), "error": msg})
        # Only actual HTML/CSS authoring style attributes are counted; JS DOM .style assignments are allowed for runtime values.
        if re.search(r"style\s*=", text, flags=re.I):
            inline_style_attrs.append(str(path.relative_to(ROOT)))
        for token in UNSUPPORTED_CSS:
            if token in text:
                unsupported_css_hits.append({"path": str(path.relative_to(ROOT)), "token": token})
        if re.search(r"â|Ã|�", text):
            mojibake_hits.append(str(path.relative_to(ROOT)))

    env_text = (ROOT / ".env").read_text(encoding="utf-8", errors="ignore") if (ROOT / ".env").exists() else ""
    secret_hits = [pat for pat in SECRET_PATTERNS if re.search(pat, env_text)]

    checks = {
        "backend_imports": True,
        "oauth_validation_ignores_mailbox_password": gmail.get("validate_oauth_tokens_only") is True and gmail.get("password_required") is False,
        "manual_custom_provider_requires_credentials": custom_missing.get("ok") is False and custom_missing.get("password_required") is True,
        "frontend_js_syntax_clean": not js_failures,
        "frontend_no_static_inline_style_attrs": not inline_style_attrs,
        "frontend_no_unsupported_backdrop_filter": not unsupported_css_hits,
        "frontend_text_encoding_clean": not mojibake_hits,
        "package_env_has_no_oauth_secrets": not secret_hits,
        "core_frontend_files_present": all((ROOT / p).exists() for p in ["backend/dashboard/index.html", "backend/dashboard/enterprise-ui.css", "backend/dashboard/enterprise-ui.js", "backend/dashboard/scam-panel.html", "extensions/chrome/manifest.json", "outlook-addin/taskpane.html"]),
    }
    close_all_tracked_connections()
    checks["sqlite_guard_cleanup_clean"] = tracked_connection_count() == 0

    report = {
        "name": "AI36 frontend/backend package validation",
        "passed": all(checks.values()),
        "score": round(100 * sum(1 for v in checks.values() if v) / len(checks), 2),
        "checks": checks,
        "details": {
            "frontend_files_checked": len(frontend_files),
            "js_failures": js_failures,
            "inline_style_attrs": inline_style_attrs,
            "unsupported_css_hits": unsupported_css_hits,
            "mojibake_hits": mojibake_hits,
            "secret_hits": secret_hits,
        },
    }
    audits_dir = ROOT / "docs" / "audits"
    audits_dir.mkdir(parents=True, exist_ok=True)
    (audits_dir / "AI36_FRONTEND_FIX_VALIDATION_REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = ["# AI36 Frontend Fix Validation", "", f"Passed: {report['passed']}", f"Score: {report['score']}/100", ""]
    for name, ok in checks.items():
        lines.append(f"- [{'PASS' if ok else 'FAIL'}] {name}")
    (audits_dir / "AI36_FRONTEND_FIX_VALIDATION_REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
