"""Runtime control plane for low-resource and enterprise profiles.

This module is intentionally lightweight: it resolves process environment into
service, agent, AI and frontend policy without opening databases or importing
heavy subsystems. Startup, routers and dashboard code can all ask this single
policy object whether a module should be enabled.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Mapping, Optional


PROFILE_ALIASES = {
    "low": "low_resource",
    "low-resource": "low_resource",
    "low_resource": "low_resource",
    "lite": "lite",
    "standard": "standard",
    "default": "standard",
    "enterprise": "enterprise",
}

AI_MODES = {"disabled", "lite", "shared", "cloud", "hybrid"}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _falsey(value: object) -> bool:
    return str(value or "").strip().lower() in {"0", "false", "no", "off", "disabled"}


def _key(prefix: str, name: str, suffix: str = "") -> str:
    clean = str(name or "").upper().replace("-", "_").replace(".", "_")
    return f"{prefix}{clean}{suffix}"


@dataclass(frozen=True)
class ServicePolicy:
    service_id: str
    name: str
    category: str
    default_enabled: bool = True
    low_resource_enabled: bool = False
    lite_enabled: bool = True
    enterprise_enabled: bool = True
    auto_start: bool = True
    router_name: Optional[str] = None
    heavy: bool = False


@dataclass(frozen=True)
class AgentPolicy:
    agent_id: str
    name: str
    service_id: str = "agents"
    default_enabled: bool = True
    low_resource_enabled: bool = False
    lite_enabled: bool = True
    enterprise_enabled: bool = True
    auto_start: bool = True
    priority: int = 50
    cpu_limit_percent: int = 20
    memory_limit_mb: int = 128
    queue_limit: int = 500
    api_daily_limit: int = 1000
    retry_limit: int = 3


SERVICE_POLICIES: Dict[str, ServicePolicy] = {
    "enterprise_system": ServicePolicy("enterprise_system", "Enterprise System", "core", True, False, True, True, True, heavy=True),
    "event_bus": ServicePolicy("event_bus", "Event Bus", "core", True, True, True, True, True, "events"),
    "agents": ServicePolicy("agents", "Agent Supervisor", "agents", True, False, True, True, True, "agents", heavy=True),
    "reconciler": ServicePolicy("reconciler", "Operational Reconciler", "operations", True, False, True, True, True, "reconciler", heavy=True),
    "workflow_scheduler": ServicePolicy("workflow_scheduler", "Workflow Scheduler", "workflow", True, False, True, True, True, "workflow_scheduler"),
    "webhooks": ServicePolicy("webhooks", "Webhook Dispatcher", "connectors", True, False, True, True, True, "webhooks"),
    "alert_rules": ServicePolicy("alert_rules", "Alert Rules", "security", True, False, True, True, True, "alert_rules", heavy=True),
    "notifications": ServicePolicy("notifications", "Notification Center", "notifications", True, True, True, True, True, "notifications"),
    "metric_snapshots": ServicePolicy("metric_snapshots", "Metric Snapshots", "observability", True, False, True, True, True, "metric_snapshots", heavy=True),
    "audit_log": ServicePolicy("audit_log", "Audit Log", "security", True, True, True, True, True, "audit_log"),
    "incidents": ServicePolicy("incidents", "Incident Manager", "operations", True, False, True, True, True, "incidents"),
    "scheduled_reports": ServicePolicy("scheduled_reports", "Scheduled Reports", "reports", True, False, True, True, True, "scheduled_reports", heavy=True),
    "playbooks": ServicePolicy("playbooks", "AI Actions", "workflow", True, False, True, True, True, "playbooks", heavy=True),
    "sla": ServicePolicy("sla", "Service Goals", "operations", True, False, True, True, True, "sla"),
    "maintenance": ServicePolicy("maintenance", "System Updates", "operations", True, True, True, True, True, "maintenance"),
    "oncall": ServicePolicy("oncall", "Team Availability", "operations", True, False, True, True, True, "oncall"),
    "system_scheduler": ServicePolicy("system_scheduler", "System Scheduler", "core", True, False, True, True, True, "scheduler", heavy=True),
    "job_runner": ServicePolicy("job_runner", "Async Job Runner", "core", True, True, True, True, True),
    "ai_assistant": ServicePolicy("ai_assistant", "AI Assistant", "ai", True, False, True, True, False, "ai_assistant", heavy=True),
    "ai_enterprise": ServicePolicy("ai_enterprise", "AI Enterprise", "ai", True, False, True, True, False, "ai_enterprise", heavy=True),
    "ocr": ServicePolicy("ocr", "Document Intelligence", "ai", True, False, True, True, False, "ocr", heavy=True),
    "threat_intelligence": ServicePolicy("threat_intelligence", "Security Insights", "security", True, False, True, True, False, "threat_intelligence", heavy=True),
    "telemetry": ServicePolicy("telemetry", "Platform Telemetry", "observability", True, False, True, True, False, "telemetry"),
}

AGENT_POLICIES: Dict[str, AgentPolicy] = {
    # Current built-in operational agents
    "inbox_monitor": AgentPolicy("inbox_monitor", "Inbox Monitor", priority=80),
    "threat_watch": AgentPolicy("threat_watch", "Threat Watch", priority=60),
    "finance_monitor": AgentPolicy("finance_monitor", "Finance Monitor", priority=85),
    "performance_analyst": AgentPolicy("performance_analyst", "Performance Analyst", priority=120),
    "security_posture": AgentPolicy("security_posture", "Security Posture Agent", priority=65),
    # Target enterprise agent taxonomy
    "workflow_orchestrator": AgentPolicy("workflow_orchestrator", "Workflow Orchestrator Agent", priority=10),
    "connector": AgentPolicy("connector", "Connector Agent", priority=20),
    "human_approval": AgentPolicy("human_approval", "Human Approval Agent", priority=30),
    "notification": AgentPolicy("notification", "Notification Agent", low_resource_enabled=True, priority=40),
    "search_memory": AgentPolicy("search_memory", "Search & Memory Agent", priority=50),
    "security_threat": AgentPolicy("security_threat", "Security & Threat Agent", priority=60),
    "document_intelligence": AgentPolicy("document_intelligence", "Document Intelligence Agent", priority=70),
    "inbox_triage": AgentPolicy("inbox_triage", "Inbox Triage Agent", priority=80),
    "ai_reply": AgentPolicy("ai_reply", "AI Reply Agent", priority=90),
    "attachment": AgentPolicy("attachment", "Attachment Agent", priority=100),
    "workflow_automation": AgentPolicy("workflow_automation", "Workflow Automation Agent", priority=110),
}

ALWAYS_ON_ROUTERS = {
    "core", "oauth", "session", "health", "runtime_control", "rules", "integrations",
    "frontend_runtime", "system", "security", "enterprise_accounts", "connection",
    "port", "discovery", "export", "tally", "workflows",
}


class RuntimeControl:
    def __init__(self, environ: Optional[Mapping[str, str]] = None):
        self.environ: Mapping[str, str] = environ if environ is not None else os.environ
        self.profile = self._resolve_profile()
        self.low_resource = self.profile == "low_resource"
        self.offline_mode = self._env_bool("AIO_OFFLINE_MODE", "OFFLINE_MODE", default=False)
        self.enterprise_mode = self.profile == "enterprise" or self._env_bool("AIO_ENTERPRISE_MODE", "ENTERPRISE_MODE", default=False)
        self.ai_mode = self._resolve_ai_mode()
        self.limits = self._resolve_limits()

    def _env(self, *names: str, default: str = "") -> str:
        for name in names:
            value = self.environ.get(name)
            if value not in (None, ""):
                return str(value)
        return default

    def _env_bool(self, *names: str, default: bool) -> bool:
        raw = self._env(*names, default="")
        if raw == "":
            return default
        if _truthy(raw):
            return True
        if _falsey(raw):
            return False
        return default

    def _resolve_profile(self) -> str:
        if self._env_bool("AIO_LOW_RESOURCE_MODE", "LOW_RESOURCE_MODE", default=False):
            return "low_resource"
        raw = self._env("AIO_RUNTIME_PROFILE", "RUNTIME_PROFILE", default="standard")
        return PROFILE_ALIASES.get(raw.strip().lower(), "standard")

    def _resolve_ai_mode(self) -> str:
        raw = self._env("AIO_AI_MODE", "AI_MODE", default="")
        if raw:
            mode = raw.strip().lower().replace("-", "_")
            return mode if mode in AI_MODES else "disabled"
        if self.low_resource or self.offline_mode:
            return "disabled"
        if self.profile == "lite":
            return "lite"
        return "cloud"

    def _resolve_limits(self) -> Dict[str, int]:
        if self.low_resource:
            defaults = {"max_workers": 1, "job_concurrency": 1, "queue_limit": 250, "poll_interval_seconds": 10, "sync_interval_seconds": 900}
        elif self.profile == "lite":
            defaults = {"max_workers": 2, "job_concurrency": 2, "queue_limit": 1000, "poll_interval_seconds": 5, "sync_interval_seconds": 300}
        elif self.profile == "enterprise":
            defaults = {"max_workers": 6, "job_concurrency": 4, "queue_limit": 5000, "poll_interval_seconds": 2, "sync_interval_seconds": 60}
        else:
            defaults = {"max_workers": 4, "job_concurrency": 4, "queue_limit": 2500, "poll_interval_seconds": 3, "sync_interval_seconds": 120}
        return {
            key: self._env_int(_key("AIO_", key), key.upper(), default=value, minimum=1)
            for key, value in defaults.items()
        }

    def _env_int(self, *names: str, default: int, minimum: int = 0) -> int:
        raw = self._env(*names, default="")
        try:
            value = int(raw) if raw != "" else default
        except (TypeError, ValueError):
            value = default
        return max(minimum, value)

    def _profile_default(self, policy) -> bool:
        if self.profile == "low_resource":
            return bool(policy.low_resource_enabled)
        if self.profile == "lite":
            return bool(policy.lite_enabled)
        if self.profile == "enterprise":
            return bool(policy.enterprise_enabled)
        return bool(policy.default_enabled)

    def is_ai_enabled(self) -> bool:
        return self.ai_mode != "disabled"

    def is_service_enabled(self, service_id: str) -> bool:
        service_id = str(service_id or "").strip()
        policy = SERVICE_POLICIES.get(service_id)
        default = self._profile_default(policy) if policy else True
        raw = self._env(_key("AIO_SERVICE_", service_id), _key("SERVICE_", service_id), default="")
        if raw != "":
            return _truthy(raw)
        if policy and policy.category == "ai" and not self.is_ai_enabled():
            return False
        return default

    def should_autostart_service(self, service_id: str) -> bool:
        service_id = str(service_id or "").strip()
        policy = SERVICE_POLICIES.get(service_id)
        if not self.is_service_enabled(service_id):
            return False
        raw = self._env(_key("AIO_SERVICE_", service_id, "_AUTOSTART"), _key("SERVICE_", service_id, "_AUTOSTART"), default="")
        if raw != "":
            return _truthy(raw)
        return bool(policy.auto_start if policy else True)

    def is_agent_enabled(self, agent_id: str) -> bool:
        agent_id = str(agent_id or "").strip()
        policy = AGENT_POLICIES.get(agent_id)
        default = self._profile_default(policy) if policy else self.is_service_enabled("agents")
        raw = self._env(_key("AIO_AGENT_", agent_id), _key("AGENT_", agent_id), default="")
        if raw != "":
            return _truthy(raw)
        return self.is_service_enabled(policy.service_id if policy else "agents") and default

    def should_autostart_agent(self, agent_id: str) -> bool:
        policy = AGENT_POLICIES.get(agent_id)
        if not self.is_agent_enabled(agent_id):
            return False
        raw = self._env(_key("AIO_AGENT_", agent_id, "_AUTOSTART"), _key("AGENT_", agent_id, "_AUTOSTART"), default="")
        if raw != "":
            return _truthy(raw)
        return bool(policy.auto_start if policy else True)

    def agent_limits(self, agent_id: str) -> Dict[str, int]:
        agent_id = str(agent_id or "").strip()
        policy = AGENT_POLICIES.get(agent_id) or AgentPolicy(agent_id, agent_id.replace("_", " ").title())
        limits = {
            "cpu_limit_percent": policy.cpu_limit_percent,
            "memory_limit_mb": policy.memory_limit_mb,
            "queue_limit": policy.queue_limit,
            "api_daily_limit": policy.api_daily_limit,
            "retry_limit": policy.retry_limit,
        }
        if self.low_resource:
            limits.update({
                "cpu_limit_percent": min(limits["cpu_limit_percent"], 15),
                "memory_limit_mb": min(limits["memory_limit_mb"], 96),
                "queue_limit": min(limits["queue_limit"], self.limits["queue_limit"]),
                "api_daily_limit": min(limits["api_daily_limit"], 250),
                "retry_limit": min(limits["retry_limit"], 3),
            })
        return {
            "cpu_limit_percent": self._env_int(_key("AIO_AGENT_", agent_id, "_CPU_LIMIT_PERCENT"), _key("AGENT_", agent_id, "_CPU_LIMIT_PERCENT"), default=limits["cpu_limit_percent"], minimum=1),
            "memory_limit_mb": self._env_int(_key("AIO_AGENT_", agent_id, "_MEMORY_LIMIT_MB"), _key("AGENT_", agent_id, "_MEMORY_LIMIT_MB"), default=limits["memory_limit_mb"], minimum=16),
            "queue_limit": self._env_int(_key("AIO_AGENT_", agent_id, "_QUEUE_LIMIT"), _key("AGENT_", agent_id, "_QUEUE_LIMIT"), default=limits["queue_limit"], minimum=1),
            "api_daily_limit": self._env_int(_key("AIO_AGENT_", agent_id, "_API_DAILY_LIMIT"), _key("AGENT_", agent_id, "_API_DAILY_LIMIT"), default=limits["api_daily_limit"], minimum=0),
            "retry_limit": self._env_int(_key("AIO_AGENT_", agent_id, "_RETRY_LIMIT"), _key("AGENT_", agent_id, "_RETRY_LIMIT"), default=limits["retry_limit"], minimum=0),
        }

    def is_router_enabled(self, router_name: str) -> bool:
        router_name = str(router_name or "").strip()
        if router_name in ALWAYS_ON_ROUTERS:
            return True
        for service_id, policy in SERVICE_POLICIES.items():
            if policy.router_name == router_name:
                return self.is_service_enabled(service_id)
        return True

    def service_status(self) -> Dict[str, Dict[str, object]]:
        return {
            service_id: {
                "id": service_id,
                "name": policy.name,
                "category": policy.category,
                "enabled": self.is_service_enabled(service_id),
                "auto_start": self.should_autostart_service(service_id),
                "heavy": policy.heavy,
            }
            for service_id, policy in SERVICE_POLICIES.items()
        }

    def agent_status(self) -> Dict[str, Dict[str, object]]:
        return {
            agent_id: {
                "id": agent_id,
                "name": policy.name,
                "service_id": policy.service_id,
                "enabled": self.is_agent_enabled(agent_id),
                "auto_start": self.should_autostart_agent(agent_id),
                "priority": policy.priority,
                "limits": self.agent_limits(agent_id),
            }
            for agent_id, policy in AGENT_POLICIES.items()
        }

    def frontend_flags(self) -> Dict[str, object]:
        return {
            "low_resource": self.low_resource,
            "minimal_animations": self.low_resource,
            "deferred_rendering": self.low_resource or self.profile == "lite",
            "virtualize_lists": True,
            "ai_enabled": self.is_ai_enabled(),
            "offline_mode": self.offline_mode,
            "profile": self.profile,
        }

    def snapshot(self) -> Dict[str, object]:
        return {
            "profile": self.profile,
            "low_resource": self.low_resource,
            "offline_mode": self.offline_mode,
            "enterprise_mode": self.enterprise_mode,
            "ai_mode": self.ai_mode,
            "ai_enabled": self.is_ai_enabled(),
            "limits": dict(self.limits),
            "frontend": self.frontend_flags(),
        }


def get_runtime_control() -> RuntimeControl:
    return RuntimeControl()


__all__ = [
    "RuntimeControl",
    "ServicePolicy",
    "AgentPolicy",
    "SERVICE_POLICIES",
    "AGENT_POLICIES",
    "get_runtime_control",
]
