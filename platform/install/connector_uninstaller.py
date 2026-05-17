"""
ConnectorUninstaller — reverses the install flow for a plugin.

Uninstall sequence:
  1. Stop plugin lifecycle (if running)
  2. Call on_uninstall() on the plugin instance
  3. Deregister webhooks
  4. Revoke all permissions
  5. Deregister from ServiceRegistry
  6. Publish uninstalled event
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


class ConnectorUninstaller:
    def __init__(
        self,
        *,
        permission_engine:  Any,
        service_registry:   Any,
        lifecycle_manager:  Optional[Any] = None,
        webhook_adapter:    Optional[Any] = None,
        event_bus:          Optional[Any] = None,
    ) -> None:
        self._perms     = permission_engine
        self._registry  = service_registry
        self._lifecycle = lifecycle_manager
        self._webhooks  = webhook_adapter
        self._bus       = event_bus

    async def uninstall(
        self,
        plugin_id: str,
        instance:  Any,
        *,
        tenant_id: str,
    ) -> Dict[str, Any]:
        log.info("Uninstalling plugin=%s for tenant=%s", plugin_id, tenant_id)

        # 1. Stop lifecycle
        if self._lifecycle:
            try:
                await self._lifecycle.stop(plugin_id)
            except Exception as exc:
                log.warning("uninstall: lifecycle.stop raised — %s", exc)

        # 2. Call on_uninstall()
        if hasattr(instance, "on_uninstall"):
            try:
                await instance.on_uninstall()
            except Exception as exc:
                log.error("uninstall: on_uninstall() raised — %s", exc)

        # 3. Deregister webhooks
        if self._webhooks and hasattr(self._webhooks, "deregister_plugin"):
            try:
                self._webhooks.deregister_plugin(plugin_id)
            except Exception as exc:
                log.warning("uninstall: webhook deregister failed — %s", exc)

        # 4. Revoke permissions
        try:
            self._perms.revoke_all(plugin_id, tenant_id)
        except Exception as exc:
            log.warning("uninstall: permission revoke failed — %s", exc)

        # 5. Deregister from registry
        try:
            self._registry.deregister(plugin_id)
        except Exception as exc:
            log.warning("uninstall: registry deregister failed — %s", exc)

        # 6. Publish event
        await self._emit("connector.uninstalled", {
            "plugin_id":    plugin_id,
            "tenant_id":    tenant_id,
            "uninstalled_at": datetime.now(timezone.utc).isoformat(),
        }, tenant_id)

        log.info("Plugin=%s uninstalled for tenant=%s", plugin_id, tenant_id)
        return {"plugin_id": plugin_id, "tenant_id": tenant_id, "status": "uninstalled"}

    async def _emit(self, event_type: str, payload: dict, tenant_id: str) -> None:
        if self._bus:
            try:
                await self._bus.publish(event_type, "__uninstaller__", tenant_id, payload)
            except Exception as exc:
                log.warning("uninstall: event publish failed — %s", exc)
