"""
EventTriggers — binds runtime events to workflow executions.

When an event matching a trigger's pattern arrives on the event bus,
the trigger fires the linked workflow with the event payload as inputs.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class WorkflowTrigger:
    """Defines a mapping from an event pattern to a workflow."""
    trigger_id:   str
    workflow_id:  str
    event_pattern: str          # glob, e.g. "crm.contact.*"
    tenant_id:    Optional[str] = None
    enabled:      bool = True
    input_mapping: Dict[str, str] = field(default_factory=dict)


class EventTriggerRegistry:
    """
    Maintains WorkflowTrigger definitions and subscribes them to the
    event bus when activate() is called.
    """

    def __init__(self) -> None:
        self._triggers: Dict[str, WorkflowTrigger] = {}
        self._sub_ids:  Dict[str, str] = {}  # trigger_id → subscription_id

    def add(self, trigger: WorkflowTrigger) -> None:
        self._triggers[trigger.trigger_id] = trigger
        log.debug("EventTriggers: added trigger %s → workflow=%s", trigger.trigger_id, trigger.workflow_id)

    def remove(self, trigger_id: str) -> None:
        self._triggers.pop(trigger_id, None)

    def list_triggers(self) -> List[Dict]:
        return [
            {
                "trigger_id":    t.trigger_id,
                "workflow_id":   t.workflow_id,
                "event_pattern": t.event_pattern,
                "tenant_id":     t.tenant_id,
                "enabled":       t.enabled,
            }
            for t in self._triggers.values()
        ]

    def activate(self, event_bus: Any, workflow_engine: Any) -> None:
        """Subscribe all enabled triggers to the event bus."""
        for t in self._triggers.values():
            if t.enabled:
                sub_id = event_bus.subscribe(
                    [t.event_pattern],
                    self._make_handler(t, workflow_engine),
                    sub_id=f"trigger_{t.trigger_id}",
                    tenant_filter=t.tenant_id,
                )
                self._sub_ids[t.trigger_id] = sub_id

    def deactivate(self, event_bus: Any) -> None:
        """Unsubscribe all active trigger subscriptions."""
        for sub_id in self._sub_ids.values():
            event_bus.unsubscribe(sub_id)
        self._sub_ids.clear()

    def _make_handler(self, trigger: WorkflowTrigger, engine: Any):
        async def _handler(event: Any) -> None:
            payload = getattr(event, "payload", {}) or {}
            inputs = self._map_inputs(payload, trigger.input_mapping)
            try:
                await engine.trigger(
                    trigger.workflow_id,
                    inputs=inputs,
                    tenant_id=getattr(event, "tenant_id", None),
                    correlation_id=getattr(event, "event_id", None),
                )
            except Exception as exc:
                log.error("EventTriggers: failed to trigger %s: %s", trigger.workflow_id, exc)
        return _handler

    def _map_inputs(self, payload: Dict, mapping: Dict[str, str]) -> Dict:
        if not mapping:
            return payload
        return {dest: payload.get(src) for dest, src in mapping.items()}
