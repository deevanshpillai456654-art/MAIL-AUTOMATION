"""
PermissionValidator — validates a plugin's declared permissions before install.

Reads plugin.json (manifest), checks requested permissions against the
platform's allowed permission catalogue, and returns validation results.
"""
from __future__ import annotations

import fnmatch
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Permissions the platform is willing to grant to any plugin
ALLOWED_PERMISSION_CATALOGUE: List[str] = [
    "crm:contacts:read",
    "crm:contacts:write",
    "crm:leads:read",
    "crm:leads:write",
    "erp:invoices:read",
    "erp:invoices:write",
    "erp:orders:read",
    "erp:orders:write",
    "shipments:*:read",
    "shipments:*:write",
    "email:send",
    "email:read",
    "webhooks:register",
    "webhooks:receive",
    "queue:enqueue",
    "queue:fetch",
    "events:publish",
    "events:subscribe",
    "storage:read",
    "storage:write",
]


class PermissionValidationResult:
    def __init__(self) -> None:
        self.valid = True
        self.granted:  List[str] = []
        self.rejected: List[str] = []
        self.warnings: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid":    self.valid,
            "granted":  self.granted,
            "rejected": self.rejected,
            "warnings": self.warnings,
        }


class PermissionValidator:
    """
    Validates a list of requested permissions against the allowed catalogue.

    Usage::

        validator = PermissionValidator()
        result = validator.validate(["crm:contacts:read", "admin:*:*"])
        if not result.valid:
            raise InstallError(result.rejected)
    """

    def __init__(
        self,
        catalogue: Optional[List[str]] = None,
        *,
        strict: bool = False,
    ) -> None:
        self._catalogue = catalogue or ALLOWED_PERMISSION_CATALOGUE
        self._strict    = strict     # True → reject any wildcard permissions

    def validate(self, requested: List[str]) -> PermissionValidationResult:
        result = PermissionValidationResult()

        for perm in requested:
            if self._strict and ("*" in perm):
                result.rejected.append(perm)
                result.warnings.append(
                    f"Wildcard permissions are not allowed in strict mode: {perm}"
                )
                result.valid = False
                continue

            if self._is_allowed(perm):
                result.granted.append(perm)
            else:
                result.rejected.append(perm)
                result.valid = False
                log.warning("PermissionValidator: rejected permission '%s'", perm)

        return result

    def _is_allowed(self, perm: str) -> bool:
        return any(fnmatch.fnmatch(perm, allowed) for allowed in self._catalogue)

    def filter_manifest(self, manifest: Dict[str, Any]) -> PermissionValidationResult:
        """Convenience — pass a plugin manifest dict directly."""
        requested = [
            p if isinstance(p, str) else p.get("name", "")
            for p in manifest.get("permissions", [])
        ]
        return self.validate([r for r in requested if r])
