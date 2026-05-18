from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from fastapi import APIRouter, FastAPI

from backend.api.absolute_enterprise_governance import router as absolute_enterprise_governance_router
from backend.api.ai_assistant import router as ai_assistant_router
from backend.api.ai_enterprise import router as ai_enterprise_router
from backend.api.connection import router as connection_router
from backend.api.enterprise_accounts import router as enterprise_accounts_router
from backend.api.enterprise_admin import router as enterprise_admin_router
from backend.api.enterprise_analysis import router as enterprise_analysis_router
from backend.api.enterprise_governance import router as enterprise_governance_router
from backend.api.enterprise_refinement import router as enterprise_refinement_router
from backend.api.enterprise_reports import router as enterprise_reports_router
from backend.api.enterprise_templates import router as enterprise_templates_router
from backend.api.enterprise_updates import router as enterprise_updates_router
from backend.api.export import router as export_router
from backend.api.agents import router as agents_router
from backend.api.event_bus import router as event_bus_router
from backend.api.ocr import router as ocr_router
from backend.api.operational_intelligence import router as intelligence_router
from backend.api.platform_telemetry import router as telemetry_router
from backend.api.reconciler import router as reconciler_router
from backend.api.workflow_scheduler import router as workflow_scheduler_router
from backend.api.workflows import router as workflows_router
from backend.api.frontend_runtime import router as frontend_runtime_router
from backend.api.health import router as health_router
from backend.api.integrations import router as integrations_router
from backend.api.learning import router as learning_router
from backend.api.port import router as port_router
from backend.api.production95 import router as production95_router
from backend.api.routes import router as core_router
from backend.api.rules import router as rules_router
from backend.api.scheduler import router as scheduler_router
from backend.api.security import router as security_router
from backend.api.session import router as session_router
from backend.api.system import router as system_router
from backend.api.tally import router as tally_router
from backend.api.threat_intelligence import router as threat_intelligence_router
from backend.api.ws_alerts import router as ws_alerts_router
from backend.api.alert_rules import router as alert_rules_router
from backend.api.audit_log import router as audit_log_router
from backend.api.incidents import router as incidents_router
from backend.api.playbooks import router as playbooks_router
from backend.api.scheduled_reports import router as scheduled_reports_router
from backend.api.metric_snapshots import router as metric_snapshots_router
from backend.api.notifications import router as notifications_router
from backend.api.webhooks import router as webhooks_router
from backend.api.sla import router as sla_router
from backend.api.maintenance import router as maintenance_router
from backend.api.api_keys import router as api_keys_router
from backend.api.oncall import router as oncall_router
from backend.api.runbooks import router as runbooks_router
from backend.auth.routes import router as oauth_router
from backend.utils.discovery import router as discovery_router


@dataclass(frozen=True)
class RouterSpec:
    name: str
    router: APIRouter
    prefix: str = "/api/v1"


API_ROUTER_SPECS: tuple[RouterSpec, ...] = (
    RouterSpec("core", core_router),
    RouterSpec("oauth", oauth_router),
    RouterSpec("integrations", integrations_router),
    RouterSpec("enterprise_refinement", enterprise_refinement_router),
    RouterSpec("enterprise_governance", enterprise_governance_router),
    RouterSpec("absolute_enterprise_governance", absolute_enterprise_governance_router),
    RouterSpec("rules", rules_router),
    RouterSpec("export", export_router),
    RouterSpec("ocr", ocr_router),
    RouterSpec("workflows", workflows_router),
    RouterSpec("events", event_bus_router),
    RouterSpec("intelligence", intelligence_router),
    RouterSpec("telemetry", telemetry_router),
    RouterSpec("agents", agents_router),
    RouterSpec("reconciler", reconciler_router),
    RouterSpec("workflow_scheduler", workflow_scheduler_router),
    RouterSpec("health", health_router),
    RouterSpec("session", session_router),
    RouterSpec("scheduler", scheduler_router),
    RouterSpec("port", port_router),
    RouterSpec("connection", connection_router),
    RouterSpec("discovery", discovery_router),
    RouterSpec("learning", learning_router),
    RouterSpec("system", system_router),
    RouterSpec("tally", tally_router),
    RouterSpec("frontend_runtime", frontend_runtime_router),
    RouterSpec("security", security_router),
    RouterSpec("ai_enterprise", ai_enterprise_router),
    RouterSpec("production95", production95_router),
    RouterSpec("enterprise_accounts", enterprise_accounts_router),
    RouterSpec("enterprise_analysis", enterprise_analysis_router),
    RouterSpec("enterprise_templates", enterprise_templates_router),
    RouterSpec("enterprise_reports", enterprise_reports_router),
    RouterSpec("enterprise_admin", enterprise_admin_router),
    RouterSpec("enterprise_updates", enterprise_updates_router),
    RouterSpec("threat_intelligence", threat_intelligence_router),
    RouterSpec("ws_alerts", ws_alerts_router),
    RouterSpec("ai_assistant", ai_assistant_router),
    RouterSpec("webhooks", webhooks_router),
    RouterSpec("alert_rules", alert_rules_router),
    RouterSpec("notifications", notifications_router),
    RouterSpec("metric_snapshots", metric_snapshots_router),
    RouterSpec("audit_log", audit_log_router),
    RouterSpec("incidents", incidents_router),
    RouterSpec("scheduled_reports", scheduled_reports_router),
    RouterSpec("playbooks", playbooks_router),
    RouterSpec("sla", sla_router),
    RouterSpec("maintenance", maintenance_router),
    RouterSpec("api_keys", api_keys_router),
    RouterSpec("oncall", oncall_router),
    RouterSpec("runbooks", runbooks_router),
)


def register_api_routers(app: FastAPI, specs: Iterable[RouterSpec] = API_ROUTER_SPECS) -> None:
    for spec in specs:
        app.include_router(spec.router, prefix=spec.prefix)


__all__ = ["API_ROUTER_SPECS", "RouterSpec", "register_api_routers"]
