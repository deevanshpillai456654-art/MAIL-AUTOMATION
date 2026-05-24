"""Provider secret isolation policy."""
from __future__ import annotations

from typing import Dict

from backend.db.database import Database


class ProviderSecretGovernor:
    def __init__(self, db: Database):
        self.db = db

    def validate_account_secrets(self, account_id: int) -> Dict:
        account = self.db.get_account_by_id(account_id)
        if not account:
            return {"ok": False, "status": "missing"}
        plaintext_markers = ["password", "secret", "token"]
        findings = []
        for field in ("access_token", "refresh_token"):
            value = account.get(field) or ""
            lowered = value.lower()
            if any(marker in lowered for marker in plaintext_markers) and not value.startswith("gAAAA"):
                findings.append(field)
        ok = not findings
        return {"ok": ok, "status": "ok" if ok else "plaintext_secret_risk", "fields": findings, "account_id": account_id}
