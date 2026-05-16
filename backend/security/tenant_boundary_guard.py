"""
Enforce tenant_id presence and consistency on structured payloads and log context.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Tuple

logger = logging.getLogger("tenant_boundary")


class TenantBoundaryGuard:
    def __init__(self):
        self._lock = threading.Lock()

    def validate_payload(
        self,
        payload: Dict[str, Any],
        expected_tenant_id: str,
        tenant_key: str = "tenant_id",
    ) -> Tuple[bool, str]:
        with self._lock:
            tid = payload.get(tenant_key)
            if tid is None:
                return False, "missing_tenant"
            if str(tid) != str(expected_tenant_id):
                logger.error("Tenant bleed blocked: expected %s got %s", expected_tenant_id, tid)
                return False, "tenant_mismatch"
            return True, "ok"

    def scrub_cross_tenant_fields(self, payload: Dict[str, Any], allowed_tenant: str) -> Dict[str, Any]:
        with self._lock:
            out = dict(payload)
            if "tenant_id" in out and str(out["tenant_id"]) != str(allowed_tenant):
                out.pop("tenant_id", None)
            return out


__all__ = ["TenantBoundaryGuard"]
