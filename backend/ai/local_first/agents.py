"""Lightweight smart-action router for email, search, workflow, and monitoring tasks."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .governance import get_governance_engine
from .runtime import get_runtime


@dataclass
class ActionLaneRecord:
    name: str
    role: str
    status: str = "idle"
    tasks_completed: int = 0
    last_activity_at: float = field(default_factory=time.time)


class AgentOrchestrator:
    """Compatibility wrapper around a small local smart-action router.

    The public class name is preserved for existing API/test compatibility, but
    the implementation is deliberately lightweight: no autonomous loops, no
    background planning, and no heavyweight model orchestration.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, ActionLaneRecord] = {
            "email": ActionLaneRecord("email", "Email Triage Lane"),
            "workflow": ActionLaneRecord("workflow", "Workflow Suggestion Lane"),
            "search": ActionLaneRecord("search", "Semantic Search Lane"),
            "monitoring": ActionLaneRecord("monitoring", "Diagnostics Lane"),
        }
        self._activity: List[Dict[str, Any]] = []

    def run(self, agent: str, task: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if agent not in self._agents:
            raise ValueError("unknown_action_lane")
        decision = get_governance_engine().evaluate(task, payload)
        if not decision.allowed:
            return {"allowed": False, "decision": decision.__dict__}
        record = self._agents[agent]
        record.status = "running"
        record.last_activity_at = time.time()
        result = get_runtime().infer(task, payload)
        record.status = "idle"
        record.tasks_completed += 1
        record.last_activity_at = time.time()
        event = {"lane": agent, "task": task, "result": result.output, "timestamp": time.time(), "approval_required": decision.requires_approval}
        self._activity.append(event)
        self._activity = self._activity[-200:]
        return {"allowed": True, "approval_required": decision.requires_approval, "agent": asdict(record), "result": result.output}

    def status(self) -> Dict[str, Any]:
        return {
            "version": "9.7.0",
            "status": "ready",
            "profile": "lightweight-smart-actions",
            "agents": [asdict(agent) for agent in self._agents.values()],
            "recent_activity": self._activity[-20:],
        }


_orchestrator: AgentOrchestrator | None = None


def get_agent_orchestrator() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator
