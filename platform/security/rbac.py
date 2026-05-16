from sdk.models import TenantContext
from sdk.exceptions import PermissionDenied

class RBAC:
    def require(self, context: TenantContext, permission: str) -> None:
        if not context.has_permission(permission):
            raise PermissionDenied(permission)
