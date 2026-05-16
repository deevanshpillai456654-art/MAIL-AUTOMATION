#!/usr/bin/env python3
"""Local red-team security regression gate for INTEMO.

This script does not replace a live third-party pentest, but it prevents the
highest-risk regressions found during the local bug-bounty pass from coming
back into the repository.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]

CHECKS = [
    {
        "id": "SEC-001",
        "name": "request signing middleware present",
        "path": "local-service/api/middleware.py",
        "must_contain": ["class RequestSigningMiddleware", "RequestSigner", "request_signature_rejected"],
    },
    {
        "id": "SEC-002",
        "name": "request body limit middleware present",
        "path": "local-service/api/middleware.py",
        "must_contain": ["class RequestSizeLimitMiddleware", "Payload too large"],
    },
    {
        "id": "SEC-003",
        "name": "webhook SSRF protection present",
        "path": "local-service/api/webhooks.py",
        "must_contain": ["validate_outbound_url", "webhook_delivery_blocked"],
    },
    {
        "id": "SEC-004",
        "name": "frontend telemetry redaction present",
        "path": "local-service/api/frontend_runtime.py",
        "must_contain": ["from security.redaction import redact", "item = redact"],
    },
    {
        "id": "SEC-005",
        "name": "security status API exposed",
        "path": "local-service/api/security.py",
        "must_contain": ["/status", "request_signing", "ssrf_protection"],
    },
    {
        "id": "SEC-006",
        "name": "Electron main-window navigation is allowlisted",
        "path": "desktop/electron/main.js",
        "must_contain": ["isAllowedAppUrl", "ALLOWED_APP_ORIGINS", "will-navigate"],
        "must_not_contain": ["return ALLOWED_ORIGINS.has(url.origin) || url.protocol === 'https:'"],
    },
    {
        "id": "SEC-007",
        "name": "websocket continuation tokens are not persisted",
        "path": "local-service/dashboard/realtime/ws_client.js",
        "must_contain": ["Keep websocket continuation tokens in memory only"],
        "must_not_contain": ["sessionStorage.setItem('ws_session_token'"],
    },
    {
        "id": "SEC-008",
        "name": "production CORS does not wildcard extension origins",
        "path": "local-service/main.py",
        "must_contain": ["allow_origin_regex=None if getattr(config, \"IS_PRODUCTION\", False) else local_cors_regex"],
    },
]


def run_checks() -> Dict[str, object]:
    results: List[Dict[str, object]] = []
    for check in CHECKS:
        path = ROOT / check["path"]
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        missing = [needle for needle in check.get("must_contain", []) if needle not in text]
        forbidden = [needle for needle in check.get("must_not_contain", []) if needle in text]
        ok = path.exists() and not missing and not forbidden
        results.append({
            "id": check["id"],
            "name": check["name"],
            "path": check["path"],
            "ok": ok,
            "missing": missing,
            "forbidden_present": forbidden,
        })
    return {"ok": all(item["ok"] for item in results), "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    args = parser.parse_args()
    result = run_checks()
    if args.write_report:
        out = ROOT / "reports" / "SECURITY_REGRESSION_GATE.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("SECURITY RED TEAM GATE:", "PASS" if result["ok"] else "FAIL")
        for item in result["results"]:
            print(f"{item['id']} {'PASS' if item['ok'] else 'FAIL'} - {item['name']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
