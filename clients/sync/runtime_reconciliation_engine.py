"""Deterministic reconciliation helpers for client runtime snapshots."""
from __future__ import annotations

from typing import Any, Dict, List

class RuntimeReconciliationEngine:
    def reconcile(self, authoritative: Dict[str, Any], client_snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Return a deterministic server-authoritative reconciliation result."""
        server_emails = {str(item.get("id") or item.get("email_id") or item.get("message_id")): item for item in authoritative.get("emails", [])}
        client_emails = {str(item.get("id") or item.get("email_id") or item.get("message_id")): item for item in client_snapshot.get("emails", [])}
        merged: List[Dict[str, Any]] = []
        for key, item in server_emails.items():
            if key and key != "None":
                merged.append({**client_emails.get(key, {}), **item})
        return {
            "emails": merged,
            "server_count": len(server_emails),
            "client_only_count": max(0, len(client_emails) - len(server_emails)),
            "authority": "server",
        }
