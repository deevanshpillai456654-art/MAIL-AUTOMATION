from __future__ import annotations
from sdk.models import TenantContext
from sdk.exceptions import PermissionDenied

class PermissionGuard:
    def require(self, context: TenantContext, permission: str) -> None:
        if not context.has_permission(permission):
            raise PermissionDenied(f"Missing permission: {permission}")

    def can_run_plugin(self, context: TenantContext, plugin_permissions: list[str]) -> bool:
        return "admin" in context.roles or all(context.has_permission(p) for p in plugin_permissions)
