"""
ServiceRegistry — central registry where plugins advertise their capabilities.

A plugin registers itself once at startup.  Other plugins query the registry
to discover what capabilities are available without depending on a specific
implementation.

Example::

    registry = ServiceRegistry.instance()

    # Salesforce plugin registers at startup
    registry.register(PluginRegistration(
        plugin_id   = "salesforce",
        name        = "Salesforce CRM",
        version     = "2.1.0",
        capabilities= [
            Capability("crm.contacts.sync",  "Sync CRM contacts"),
            Capability("crm.leads.sync",     "Sync CRM leads"),
            Capability("crm.opportunities",  "Manage opportunities"),
        ],
        event_types_emitted  = ["crm.contact.created", "crm.lead.updated"],
        event_types_consumed = ["invoice.paid", "shipment.delivered"],
        provides_routes      = ["/crm/salesforce/..."],
        provides_ui_widgets  = ["crm-dashboard-widget"],
    ))

    # Another plugin asks "who can sync CRM contacts?"
    providers = registry.resolve_capability("crm.contacts.sync")
"""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class PluginState(str, Enum):
    REGISTERED  = "registered"
    STARTING    = "starting"
    RUNNING     = "running"
    DEGRADED    = "degraded"
    STOPPING    = "stopping"
    STOPPED     = "stopped"
    FAILED      = "failed"


@dataclass
class Capability:
    name:        str
    description: str = ""
    version:     str = "1.0.0"
    schema:      Dict[str, Any] = field(default_factory=dict)  # JSON-schema for inputs/outputs
    tags:        List[str]      = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name":        self.name,
            "description": self.description,
            "version":     self.version,
            "tags":        self.tags,
        }


@dataclass
class PluginRegistration:
    plugin_id:            str
    name:                 str
    version:              str
    capabilities:         List[Capability]     = field(default_factory=list)
    event_types_emitted:  List[str]            = field(default_factory=list)
    event_types_consumed: List[str]            = field(default_factory=list)
    provides_routes:      List[str]            = field(default_factory=list)
    provides_ui_widgets:  List[str]            = field(default_factory=list)
    provides_workflow_nodes: List[str]         = field(default_factory=list)
    state:                PluginState          = PluginState.REGISTERED
    tenant_ids:           Optional[List[str]]  = None   # None = global (all tenants)
    metadata:             Dict[str, Any]       = field(default_factory=dict)
    registered_at:        str                  = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    last_heartbeat:       Optional[str]        = None
    error_message:        Optional[str]        = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plugin_id":               self.plugin_id,
            "name":                    self.name,
            "version":                 self.version,
            "capabilities":            [c.to_dict() for c in self.capabilities],
            "event_types_emitted":     self.event_types_emitted,
            "event_types_consumed":    self.event_types_consumed,
            "provides_routes":         self.provides_routes,
            "provides_ui_widgets":     self.provides_ui_widgets,
            "provides_workflow_nodes": self.provides_workflow_nodes,
            "state":                   self.state.value,
            "tenant_ids":              self.tenant_ids,
            "registered_at":           self.registered_at,
            "last_heartbeat":          self.last_heartbeat,
            "error_message":           self.error_message,
            "metadata":                self.metadata,
        }


# ---------------------------------------------------------------------------
# ServiceRegistry
# ---------------------------------------------------------------------------

class ServiceRegistry:
    """
    Thread-safe singleton service + capability registry.

    Plugins register themselves here; consumers query here.
    No direct plugin-to-plugin imports needed.
    """

    _instance: Optional["ServiceRegistry"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._plugins:     Dict[str, PluginRegistration] = {}
        self._cap_index:   Dict[str, List[str]]          = {}  # cap_name → [plugin_ids]
        self._event_index: Dict[str, List[str]]          = {}  # event_type → [plugin_ids]
        self._rw_lock = threading.RLock()

    @classmethod
    def instance(cls) -> "ServiceRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Registration ──────────────────────────────────────────────────────

    def register(self, reg: PluginRegistration) -> None:
        with self._rw_lock:
            self._plugins[reg.plugin_id] = reg
            # Index capabilities
            for cap in reg.capabilities:
                self._cap_index.setdefault(cap.name, [])
                if reg.plugin_id not in self._cap_index[cap.name]:
                    self._cap_index[cap.name].append(reg.plugin_id)
            # Index consumed event types
            for et in reg.event_types_consumed:
                self._event_index.setdefault(et, [])
                if reg.plugin_id not in self._event_index[et]:
                    self._event_index[et].append(reg.plugin_id)
        log.info(
            "ServiceRegistry: registered plugin=%s v=%s caps=%d events_in=%d",
            reg.plugin_id, reg.version,
            len(reg.capabilities), len(reg.event_types_consumed),
        )

    def unregister(self, plugin_id: str) -> None:
        with self._rw_lock:
            reg = self._plugins.pop(plugin_id, None)
            if reg is None:
                return
            # Clean capability index
            for cap in reg.capabilities:
                lst = self._cap_index.get(cap.name, [])
                if plugin_id in lst:
                    lst.remove(plugin_id)
            # Clean event index
            for et in reg.event_types_consumed:
                lst = self._event_index.get(et, [])
                if plugin_id in lst:
                    lst.remove(plugin_id)
        log.info("ServiceRegistry: unregistered plugin=%s", plugin_id)

    def update_state(
        self,
        plugin_id: str,
        state: PluginState,
        error: Optional[str] = None,
    ) -> None:
        with self._rw_lock:
            reg = self._plugins.get(plugin_id)
            if reg:
                reg.state = state
                reg.last_heartbeat = datetime.now(timezone.utc).isoformat()
                if error:
                    reg.error_message = error
                elif state == PluginState.RUNNING:
                    reg.error_message = None

    # ── Discovery ─────────────────────────────────────────────────────────

    def get(self, plugin_id: str) -> Optional[PluginRegistration]:
        return self._plugins.get(plugin_id)

    def list_all(
        self,
        state_filter: Optional[PluginState] = None,
        tenant_id: Optional[str] = None,
    ) -> List[PluginRegistration]:
        with self._rw_lock:
            results = list(self._plugins.values())
        if state_filter:
            results = [p for p in results if p.state == state_filter]
        if tenant_id:
            results = [
                p for p in results
                if p.tenant_ids is None or tenant_id in p.tenant_ids
            ]
        return results

    def list_running(self, tenant_id: Optional[str] = None) -> List[PluginRegistration]:
        return self.list_all(state_filter=PluginState.RUNNING, tenant_id=tenant_id)

    def resolve_capability(
        self,
        capability_name: str,
        tenant_id: Optional[str] = None,
    ) -> List[PluginRegistration]:
        """Return plugins that provide *capability_name*."""
        with self._rw_lock:
            plugin_ids = list(self._cap_index.get(capability_name, []))
        providers = []
        for pid in plugin_ids:
            reg = self._plugins.get(pid)
            if reg and reg.state in (PluginState.RUNNING, PluginState.REGISTERED):
                if tenant_id is None or reg.tenant_ids is None or tenant_id in reg.tenant_ids:
                    providers.append(reg)
        return providers

    def find_event_consumers(self, event_type: str) -> List[PluginRegistration]:
        """Return plugins that consume *event_type*."""
        import fnmatch
        consumers = []
        with self._rw_lock:
            for pid, reg in self._plugins.items():
                if any(fnmatch.fnmatch(event_type, pattern) for pattern in reg.event_types_consumed):
                    consumers.append(reg)
        return consumers

    def list_capabilities(self) -> Dict[str, List[str]]:
        """Return a map of capability_name → [plugin_ids]."""
        with self._rw_lock:
            return {k: list(v) for k, v in self._cap_index.items() if v}

    def list_ui_widgets(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all UI widget contributions from running plugins."""
        widgets = []
        for reg in self.list_running(tenant_id=tenant_id):
            for widget in reg.provides_ui_widgets:
                widgets.append({
                    "plugin_id": reg.plugin_id,
                    "widget_id": widget,
                    "plugin_name": reg.name,
                })
        return widgets

    def list_workflow_nodes(self) -> List[Dict[str, Any]]:
        """Return all workflow node contributions from running plugins."""
        nodes = []
        for reg in self.list_running():
            for node in reg.provides_workflow_nodes:
                nodes.append({
                    "plugin_id": reg.plugin_id,
                    "node_type": node,
                    "plugin_name": reg.name,
                })
        return nodes

    def health_summary(self) -> Dict[str, Any]:
        with self._rw_lock:
            plugins = list(self._plugins.values())
        counts: Dict[str, int] = {}
        for p in plugins:
            counts[p.state.value] = counts.get(p.state.value, 0) + 1
        return {
            "total":  len(plugins),
            "by_state": counts,
            "capabilities": len(self._cap_index),
        }


# ---------------------------------------------------------------------------
# Module-level accessor
# ---------------------------------------------------------------------------

def get_service_registry() -> ServiceRegistry:
    return ServiceRegistry.instance()
