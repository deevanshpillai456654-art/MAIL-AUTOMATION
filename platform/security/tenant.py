from sdk.models import TenantContext

class TenantIsolationGuard:
    def assert_same_tenant(self, context: TenantContext, tenant_id: str) -> None:
        if context.tenant_id != tenant_id:
            raise PermissionError("Tenant isolation violation")
