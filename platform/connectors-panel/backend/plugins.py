"""
Plugins router — manage platform plugins and their permissions.
Prefix: /plugins
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from .models import (
    APIResponse,
    PermissionGrantRequest,
    PluginInfo,
    PluginPermission,
    PluginPermissionLevel,
)
from ..shared.utils import utc_now_str

router = APIRouter(prefix="/plugins", tags=["plugins"])

# Root of the platform/plugins/ directory
_PLATFORM_PLUGINS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"


# ---------------------------------------------------------------------------
# Plugin discovery helpers
# ---------------------------------------------------------------------------

def _discover_plugins() -> list[PluginInfo]:
    """
    Discover plugins by scanning platform/plugins/ directory for plugin.json files.
    Falls back gracefully if directory does not exist.
    """
    plugins: list[PluginInfo] = []

    if not _PLATFORM_PLUGINS_DIR.exists():
        # Also try the connectors-panel plugins dir
        alt = Path(__file__).resolve().parent.parent / "plugins"
        dirs_to_scan = [alt] if alt.exists() else []
    else:
        # Scan both the platform plugins dir AND connectors-panel plugins
        alt = Path(__file__).resolve().parent.parent / "plugins"
        dirs_to_scan = [_PLATFORM_PLUGINS_DIR]
        if alt.exists():
            dirs_to_scan.append(alt)

    seen: set[str] = set()

    for base_dir in dirs_to_scan:
        for manifest_file in sorted(base_dir.glob("*/plugin.json")):
            try:
                import re as _re
                raw = json.loads(manifest_file.read_text(encoding="utf-8"))
                plugin_id = raw.get("name", manifest_file.parent.name)
                if not _re.fullmatch(r'[A-Za-z0-9_\-]+', plugin_id):
                    continue  # skip plugins with unsafe IDs
                if plugin_id in seen:
                    continue
                seen.add(plugin_id)
                plugins.append(
                    PluginInfo(
                        plugin_id=plugin_id,
                        name=raw.get("name", plugin_id),
                        version=raw.get("version", "0.0.0"),
                        plugin_type=raw.get("type", "plugin"),
                        category=raw.get("category", "internal"),
                        description=raw.get("description", ""),
                        author=raw.get("author", "unknown"),
                        enabled=raw.get("enabled", False),
                        multiTenant=raw.get("multiTenant", True),
                        supports_oauth=raw.get("supports_oauth", False),
                        supports_api_key=raw.get("supports_api_key", False),
                        supports_webhook=raw.get("supports_webhook", False),
                        queue_enabled=raw.get("queue_enabled", False),
                        permissions=raw.get("permissions", []),
                        events=raw.get("events", []),
                        path=str(manifest_file.parent),
                    )
                )
            except Exception:
                continue

    # Try to augment with the runtime registry if available
    try:
        import importlib
        registry_mod = importlib.import_module("platform.runtime.plugin_registry")
        if hasattr(registry_mod, "get_registry"):
            registry = registry_mod.get_registry()
            registered: list[str] = getattr(registry, "list_plugins", lambda: [])()
            existing_ids = {p.plugin_id for p in plugins}
            for pid in registered:
                if pid not in existing_ids:
                    info = getattr(registry, "get_plugin_info", lambda x: None)(pid)
                    if info:
                        plugins.append(
                            PluginInfo(
                                plugin_id=pid,
                                name=getattr(info, "name", pid),
                                version=getattr(info, "version", "0.0.0"),
                                category=getattr(info, "category", "internal"),
                                description=getattr(info, "description", ""),
                                author=getattr(info, "author", "unknown"),
                                enabled=getattr(info, "enabled", False),
                                permissions=[],
                                events=[],
                            )
                        )
    except Exception:
        pass

    return plugins


def _find_plugin(plugin_id: str) -> PluginInfo:
    plugins = _discover_plugins()
    for p in plugins:
        if p.plugin_id == plugin_id:
            return p
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Plugin '{plugin_id}' not found")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[PluginInfo], summary="List all registered plugins")
async def list_plugins(
    category: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
):
    plugins = _discover_plugins()
    if category:
        plugins = [p for p in plugins if p.category == category]
    if enabled is not None:
        plugins = [p for p in plugins if p.enabled == enabled]
    return plugins


@router.get("/health", summary="Get health of all plugins")
async def plugins_health():
    plugins = _discover_plugins()
    health_data: list[dict] = []
    for p in plugins:
        entry: dict[str, Any] = {
            "plugin_id": p.plugin_id,
            "name": p.name,
            "enabled": p.enabled,
            "status": "running" if p.enabled else "stopped",
        }
        # Try to call health_check if module is available
        try:
            import importlib
            import re as _re
            if not _re.fullmatch(r'[A-Za-z0-9_\-]+', p.plugin_id):
                raise ValueError("invalid plugin_id")
            mod = importlib.import_module(f"platform.plugins.{p.plugin_id}.module")
            for attr in dir(mod):
                cls = getattr(mod, attr)
                if isinstance(cls, type) and hasattr(cls, "health_check"):
                    instance = cls()
                    result = instance.health_check("system")
                    entry["health"] = result
                    break
        except Exception:
            entry["health"] = {"status": "unknown", "message": "Module not loaded"}
        health_data.append(entry)
    return {"plugins": health_data, "total": len(health_data)}


@router.get("/{plugin_id}", response_model=PluginInfo, summary="Get plugin details")
async def get_plugin(plugin_id: str):
    return _find_plugin(plugin_id)


@router.post("/{plugin_id}/enable", response_model=APIResponse, summary="Enable a plugin")
async def enable_plugin(plugin_id: str):
    plugin = _find_plugin(plugin_id)
    if plugin.path:
        manifest_path = Path(plugin.path) / "plugin.json"
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                data["enabled"] = True
                manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to update plugin manifest: {exc}",
                )
    return APIResponse(message=f"Plugin '{plugin_id}' enabled")


@router.post("/{plugin_id}/disable", response_model=APIResponse, summary="Disable a plugin")
async def disable_plugin(plugin_id: str):
    plugin = _find_plugin(plugin_id)
    if plugin.path:
        manifest_path = Path(plugin.path) / "plugin.json"
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                data["enabled"] = False
                manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to update plugin manifest: {exc}",
                )
    return APIResponse(message=f"Plugin '{plugin_id}' disabled")


@router.get("/{plugin_id}/permissions", response_model=list[PluginPermission], summary="Get plugin permissions")
async def get_plugin_permissions(plugin_id: str, tenant_id: str = Query(...)):
    _find_plugin(plugin_id)
    db = get_panel_db()
    sql = "SELECT * FROM plugin_permissions WHERE plugin_id = ? AND tenant_id = ?"
    params: list[Any] = [plugin_id, tenant_id]
    rows = db.fetch_all(sql, params)
    return [
        PluginPermission(
            plugin_id=r["plugin_id"],
            tenant_id=r["tenant_id"],
            permission=PluginPermissionLevel(r["permission"]),
            granted_at=datetime.fromisoformat(r["granted_at"]),
            granted_by=r["granted_by"],
        )
        for r in rows
    ]


@router.post("/{plugin_id}/permissions", response_model=PluginPermission, status_code=status.HTTP_201_CREATED, summary="Grant permission")
async def grant_permission(plugin_id: str, body: PermissionGrantRequest, tenant_id: str = Query(...)):
    _find_plugin(plugin_id)
    db = get_panel_db()
    perm_id = str(uuid.uuid4())
    now = utc_now_str()

    db.execute(
        """
        INSERT INTO plugin_permissions (id, plugin_id, tenant_id, permission, granted_at, granted_by)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(plugin_id, tenant_id, permission) DO UPDATE SET
            granted_at = excluded.granted_at,
            granted_by = excluded.granted_by
        """,
        (perm_id, plugin_id, tenant_id, body.permission.value, now, body.granted_by),
    )

    return PluginPermission(
        plugin_id=plugin_id,
        tenant_id=tenant_id,
        permission=body.permission,
        granted_at=datetime.fromisoformat(now),
        granted_by=body.granted_by,
    )


@router.delete(
    "/{plugin_id}/permissions/{permission}",
    response_model=APIResponse,
    summary="Revoke permission",
)
async def revoke_permission(
    plugin_id: str,
    permission: str,
    tenant_id: str = Query(...),
):
    _find_plugin(plugin_id)
    db = get_panel_db()
    db.execute(
        "DELETE FROM plugin_permissions WHERE plugin_id = ? AND tenant_id = ? AND permission = ?",
        (plugin_id, tenant_id, permission),
    )
    return APIResponse(message=f"Permission '{permission}' revoked from plugin '{plugin_id}'")
