"""
PermissionEngine — capability-based permission system for plugins.

Plugins declare required permissions in plugin.json.
The engine checks at runtime whether the plugin holds the permission.

Permission format:  "domain:resource:action"
Examples:
  "crm:contacts:read"
  "erp:invoices:write"
  "shipments:*:*"
  "admin:*:*"
"""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger(__name__)


class PermissionDenied(PermissionError):
    pass


@dataclass
class PluginPermissions:
    plugin_id:   str
    tenant_id:   str
    granted:     Set[str] = field(default_factory=set)
    revoked:     Set[str] = field(default_factory=set)


class PermissionEngine:
    """
    Central permission engine.

    Usage::

        engine = PermissionEngine()
        engine.grant("salesforce", "tenant_1", [
            "crm:contacts:*",
            "crm:leads:read",
        ])
        engine.require("salesforce", "tenant_1", "crm:contacts:write")  # OK
        engine.require("salesforce", "tenant_1", "erp:invoices:write")  # raises PermissionDenied
    """

    def __init__(self) -> None:
        # (plugin_id, tenant_id) → PluginPermissions
        self._perms: Dict[tuple, PluginPermissions] = {}

    def _key(self, plugin_id: str, tenant_id: str) -> tuple:
        return (plugin_id, tenant_id)

    def _get_or_create(self, plugin_id: str, tenant_id: str) -> PluginPermissions:
        key = self._key(plugin_id, tenant_id)
        if key not in self._perms:
            self._perms[key] = PluginPermissions(
                plugin_id=plugin_id, tenant_id=tenant_id
            )
        return self._perms[key]

    # ── Admin ─────────────────────────────────────────────────────────────

    def grant(
        self,
        plugin_id: str,
        tenant_id: str,
        permissions: List[str],
    ) -> None:
        rec = self._get_or_create(plugin_id, tenant_id)
        for perm in permissions:
            rec.granted.add(perm)
            rec.revoked.discard(perm)
        log.debug("PermissionEngine: granted %s → %s for %s", plugin_id, permissions, tenant_id)

    def revoke(
        self,
        plugin_id: str,
        tenant_id: str,
        permissions: List[str],
    ) -> None:
        rec = self._get_or_create(plugin_id, tenant_id)
        for perm in permissions:
            rec.granted.discard(perm)
            rec.revoked.add(perm)

    def revoke_all(self, plugin_id: str, tenant_id: str) -> None:
        key = self._key(plugin_id, tenant_id)
        self._perms.pop(key, None)

    # ── Check ─────────────────────────────────────────────────────────────

    def has(
        self,
        plugin_id: str,
        tenant_id: str,
        permission: str,
    ) -> bool:
        """Return True if plugin has *permission*."""
        rec = self._perms.get(self._key(plugin_id, tenant_id))
        if not rec:
            return False
        if permission in rec.revoked:
            return False
        # Check granted set with glob support
        return any(fnmatch.fnmatch(permission, g) for g in rec.granted)

    def require(
        self,
        plugin_id: str,
        tenant_id: str,
        permission: str,
    ) -> None:
        """Raise PermissionDenied if plugin does not have *permission*."""
        if not self.has(plugin_id, tenant_id, permission):
            raise PermissionDenied(
                f"Plugin '{plugin_id}' (tenant={tenant_id}) lacks permission '{permission}'"
            )

    def list_granted(self, plugin_id: str, tenant_id: str) -> List[str]:
        rec = self._perms.get(self._key(plugin_id, tenant_id))
        return sorted(rec.granted) if rec else []

    def summary(self) -> Dict[str, Any]:
        return {
            f"{pid}@{tid}": sorted(rec.granted)
            for (pid, tid), rec in self._perms.items()
        }
