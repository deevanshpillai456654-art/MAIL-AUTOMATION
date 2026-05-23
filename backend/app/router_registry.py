"""FastAPI router registry with lazy imports.

Each ``RouterSpec`` can be created in two forms:

* **Eager**: ``RouterSpec("name", APIRouter())`` — used by tests that build
  ad-hoc routers and assert behaviour.

* **Lazy**: ``RouterSpec.lazy("name", "backend.api.module")`` — used by the
  production ``API_ROUTER_SPECS`` tuple. The module is imported only when
  ``register_api_routers`` decides the router is enabled. This honours
  ``RuntimeControl.is_router_enabled`` *before* paying the import cost, which
  is what makes the "Low Resource Mode" service toggle real instead of
  cosmetic.

``API_ROUTER_SPECS`` and ``RouterSpec.name`` semantics are unchanged, so
existing tests that iterate the registry continue to work.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Iterable, Optional

from fastapi import APIRouter, FastAPI

from backend.core.runtime_control import RuntimeControl, get_runtime_control


@dataclass(frozen=True)
class RouterSpec:
    name: str
    router: Optional[APIRouter] = None
    module_path: Optional[str] = None
    attr: str = "router"
    prefix: str = "/api/v1"

    def __post_init__(self):
        if self.router is None and not self.module_path:
            raise ValueError(
                f"RouterSpec('{self.name}') requires either a router instance or a module_path"
            )

    @classmethod
    def lazy(cls, name: str, module_path: str, *, attr: str = "router", prefix: str = "/api/v1") -> "RouterSpec":
        return cls(name=name, router=None, module_path=module_path, attr=attr, prefix=prefix)

    def load(self) -> APIRouter:
        """Return the router instance, importing lazily if needed."""
        if self.router is not None:
            return self.router
        module = importlib.import_module(self.module_path)  # type: ignore[arg-type]
        router = getattr(module, self.attr, None)
        if router is None:
            raise AttributeError(
                f"Module '{self.module_path}' has no attribute '{self.attr}' for RouterSpec('{self.name}')"
            )
        return router


# Production registry. Listed lazily so that a disabled router (per runtime
# profile) never triggers its import. The tuple length and ordering are stable
# so that snapshot-style tests over ``API_ROUTER_SPECS`` keep passing.
API_ROUTER_SPECS: tuple[RouterSpec, ...] = (
    RouterSpec.lazy("core", "backend.api.routes"),
    RouterSpec.lazy("oauth", "backend.auth.routes"),
    RouterSpec.lazy("runtime_control", "backend.api.runtime_control"),
    RouterSpec.lazy("ai_gateway", "backend.api.ai_gateway"),
    RouterSpec.lazy("integrations", "backend.api.integrations"),
    RouterSpec.lazy("enterprise_refinement", "backend.api.enterprise_refinement"),
    RouterSpec.lazy("enterprise_governance", "backend.api.enterprise_governance"),
    RouterSpec.lazy("absolute_enterprise_governance", "backend.api.absolute_enterprise_governance"),
    RouterSpec.lazy("rules", "backend.api.rules"),
    RouterSpec.lazy("export", "backend.api.export"),
    RouterSpec.lazy("ocr", "backend.api.ocr"),
    RouterSpec.lazy("workflows", "backend.api.workflows"),
    RouterSpec.lazy("events", "backend.api.event_bus"),
    RouterSpec.lazy("human_approval", "backend.api.human_approval"),
    RouterSpec.lazy("intelligence", "backend.api.operational_intelligence"),
    RouterSpec.lazy("telemetry", "backend.api.platform_telemetry"),
    RouterSpec.lazy("agents", "backend.api.agents"),
    RouterSpec.lazy("reconciler", "backend.api.reconciler"),
    RouterSpec.lazy("workflow_scheduler", "backend.api.workflow_scheduler"),
    RouterSpec.lazy("health", "backend.api.health"),
    RouterSpec.lazy("session", "backend.api.session"),
    RouterSpec.lazy("scheduler", "backend.api.scheduler"),
    RouterSpec.lazy("port", "backend.api.port"),
    RouterSpec.lazy("connection", "backend.api.connection"),
    RouterSpec.lazy("discovery", "backend.utils.discovery"),
    RouterSpec.lazy("learning", "backend.api.learning"),
    RouterSpec.lazy("system", "backend.api.system"),
    RouterSpec.lazy("tally", "backend.api.tally"),
    RouterSpec.lazy("frontend_runtime", "backend.api.frontend_runtime"),
    RouterSpec.lazy("security", "backend.api.security"),
    RouterSpec.lazy("ai_enterprise", "backend.api.ai_enterprise"),
    RouterSpec.lazy("production95", "backend.api.production95"),
    RouterSpec.lazy("enterprise_accounts", "backend.api.enterprise_accounts"),
    RouterSpec.lazy("enterprise_analysis", "backend.api.enterprise_analysis"),
    RouterSpec.lazy("enterprise_templates", "backend.api.enterprise_templates"),
    RouterSpec.lazy("enterprise_reports", "backend.api.enterprise_reports"),
    RouterSpec.lazy("enterprise_admin", "backend.api.enterprise_admin"),
    RouterSpec.lazy("enterprise_updates", "backend.api.enterprise_updates"),
    RouterSpec.lazy("enterprise_operations", "backend.api.enterprise_operations"),
    RouterSpec.lazy("threat_intelligence", "backend.api.threat_intelligence"),
    RouterSpec.lazy("ws_alerts", "backend.api.ws_alerts"),
    RouterSpec.lazy("ai_assistant", "backend.api.ai_assistant"),
    RouterSpec.lazy("webhooks", "backend.api.webhooks"),
    RouterSpec.lazy("alert_rules", "backend.api.alert_rules"),
    RouterSpec.lazy("notifications", "backend.api.notifications"),
    RouterSpec.lazy("metric_snapshots", "backend.api.metric_snapshots"),
    RouterSpec.lazy("audit_log", "backend.api.audit_log"),
    RouterSpec.lazy("incidents", "backend.api.incidents"),
    RouterSpec.lazy("scheduled_reports", "backend.api.scheduled_reports"),
    RouterSpec.lazy("playbooks", "backend.api.playbooks"),
    RouterSpec.lazy("sla", "backend.api.sla"),
    RouterSpec.lazy("maintenance", "backend.api.maintenance"),
    RouterSpec.lazy("api_keys", "backend.api.api_keys"),
    RouterSpec.lazy("oncall", "backend.api.oncall"),
    RouterSpec.lazy("runbooks", "backend.api.runbooks"),
    RouterSpec.lazy("change_management", "backend.api.change_management"),
    RouterSpec.lazy("problem_management", "backend.api.problem_management"),
    RouterSpec.lazy("service_catalog", "backend.api.service_catalog"),
    RouterSpec.lazy("deployments", "backend.api.deployments"),
    RouterSpec.lazy("asset_management", "backend.api.asset_management"),
    RouterSpec.lazy("knowledge_base", "backend.api.knowledge_base"),
    RouterSpec.lazy("capacity_planning", "backend.api.capacity_planning"),
    RouterSpec.lazy("vendor_management", "backend.api.vendor_management"),
    RouterSpec.lazy("feature_flags", "backend.api.feature_flags"),
    RouterSpec.lazy("budget_tracking", "backend.api.budget_tracking"),
    RouterSpec.lazy("license_management", "backend.api.license_management"),
    RouterSpec.lazy("config_management", "backend.api.config_management"),
    RouterSpec.lazy("certificate_management", "backend.api.certificate_management"),
    RouterSpec.lazy("risk_register", "backend.api.risk_register"),
    RouterSpec.lazy("slo_management", "backend.api.slo_management"),
)


def register_api_routers(
    app: FastAPI,
    specs: Iterable[RouterSpec] = API_ROUTER_SPECS,
    runtime: RuntimeControl | None = None,
) -> None:
    runtime = runtime or get_runtime_control()
    for spec in specs:
        if not runtime.is_router_enabled(spec.name):
            continue
        app.include_router(spec.load(), prefix=spec.prefix)


__all__ = ["API_ROUTER_SPECS", "RouterSpec", "register_api_routers"]
