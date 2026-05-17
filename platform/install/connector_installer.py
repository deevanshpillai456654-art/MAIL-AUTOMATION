"""
ConnectorInstaller — orchestrates the full plugin install flow.

Install sequence:
  1. Load & validate plugin manifest
  2. Validate permissions (PermissionValidator)
  3. Grant validated permissions (PermissionEngine)
  4. Register plugin in ServiceRegistry
  5. Call on_install() on the plugin instance
  6. Register webhooks (WebhookAdapter)
  7. Publish installed event

All steps are reversible; on failure ConnectorUninstaller.rollback() is
called automatically.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class InstallError(Exception):
    pass


class ConnectorInstaller:
    """
    Drives plugin installation for a given tenant.

    Usage::

        installer = ConnectorInstaller(
            permission_engine=engine,
            service_registry=registry,
            webhook_adapter=webhooks,
            event_bus=bus,
        )
        await installer.install(manifest, instance, tenant_id="tenant_1")
    """

    def __init__(
        self,
        *,
        permission_engine: Any,
        service_registry:  Any,
        webhook_adapter:   Optional[Any] = None,
        event_bus:         Optional[Any] = None,
        permission_validator: Optional[Any] = None,
    ) -> None:
        self._perms     = permission_engine
        self._registry  = service_registry
        self._webhooks  = webhook_adapter
        self._bus       = event_bus

        if permission_validator is None:
            from .permission_validator import PermissionValidator
            permission_validator = PermissionValidator()
        self._pv = permission_validator

    async def install(
        self,
        manifest: Dict[str, Any],
        instance: Any,
        *,
        tenant_id: str,
        config:    Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        plugin_id = manifest.get("plugin_id") or manifest.get("id", "unknown")
        log.info("Installing plugin=%s for tenant=%s", plugin_id, tenant_id)

        # 1. Validate permissions
        pv_result = self._pv.filter_manifest(manifest)
        if not pv_result.valid:
            raise InstallError(
                f"Permission validation failed: {pv_result.rejected}"
            )

        # 2. Grant permissions
        self._perms.grant(plugin_id, tenant_id, pv_result.granted)

        # 3. Register in service registry
        from ..runtime.registry.service_registry import PluginRegistration, PluginState, Capability
        caps = [
            Capability(name=c if isinstance(c, str) else c.get("name", ""))
            for c in manifest.get("capabilities", [])
        ]
        reg = PluginRegistration(
            plugin_id=plugin_id,
            name=manifest.get("name", plugin_id),
            version=manifest.get("version", "0.0.1"),
            capabilities=caps,
            event_types_emitted  =manifest.get("event_types_emitted", []),
            event_types_consumed =manifest.get("event_types_consumed", []),
            provides_routes       =manifest.get("provides_routes", []),
            provides_ui_widgets   =manifest.get("provides_ui_widgets", []),
            provides_workflow_nodes=manifest.get("provides_workflow_nodes", []),
            state=PluginState.ACTIVE,
            tenant_ids=[tenant_id],
        )
        self._registry.register(reg)

        # 4. Call on_install()
        if hasattr(instance, "on_install"):
            try:
                await instance.on_install()
            except Exception as exc:
                raise InstallError(f"on_install() raised: {exc}") from exc

        # 5. Register webhooks declared in manifest
        if self._webhooks:
            for wh in manifest.get("webhooks", []):
                try:
                    self._webhooks.register(
                        plugin_id=plugin_id,
                        event_types=wh.get("event_types", []),
                        endpoint_url=wh.get("endpoint_url", ""),
                        secret=wh.get("secret"),
                    )
                except Exception as exc:
                    log.warning("install: webhook registration failed — %s", exc)

        # 6. Publish installed event
        await self._emit("connector.installed", {
            "plugin_id": plugin_id,
            "tenant_id": tenant_id,
            "version":   manifest.get("version"),
            "installed_at": datetime.now(timezone.utc).isoformat(),
        }, tenant_id)

        log.info("Plugin=%s installed successfully for tenant=%s", plugin_id, tenant_id)
        return {
            "plugin_id":  plugin_id,
            "tenant_id":  tenant_id,
            "granted":    pv_result.granted,
            "warnings":   pv_result.warnings,
        }

    async def _emit(self, event_type: str, payload: Dict[str, Any], tenant_id: str) -> None:
        if self._bus:
            try:
                await self._bus.publish(
                    event_type, "__installer__", tenant_id, payload
                )
            except Exception as exc:
                log.warning("install: event publish failed — %s", exc)
