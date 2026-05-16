"""Local AI workflow engine with approval-safe execution."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .governance import get_governance_engine


@dataclass
class WorkflowStep:
    action: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkflowRun:
    id: str
    name: str
    status: str
    steps: List[Dict[str, Any]]
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


class WorkflowEngine:
    def __init__(self) -> None:
        self._runs: List[WorkflowRun] = []

    def execute(self, name: str, steps: List[WorkflowStep]) -> Dict[str, Any]:
        run = WorkflowRun(id=str(uuid.uuid4()), name=name, status="running", steps=[])
        for step in steps:
            decision = get_governance_engine().evaluate(step.action, step.payload)
            state = {"action": step.action, "allowed": decision.allowed, "approval_required": decision.requires_approval, "reasons": decision.reasons}
            run.steps.append(state)
            if not decision.allowed:
                run.status = "blocked"
                break
            if decision.requires_approval:
                run.status = "waiting_for_approval"
                break
        else:
            run.status = "completed"
        run.finished_at = time.time() if run.status in {"blocked", "completed"} else None
        self._runs.append(run)
        self._runs = self._runs[-200:]
        return asdict(run)

    def status(self) -> Dict[str, Any]:
        return {
            "version": "9.7.0",
            "status": "ready",
            "runs": [asdict(run) for run in self._runs[-50:]],
            "templates": ["email_triage", "logistics_followup", "compliance_review", "approval_then_send"],
        }


_engine: WorkflowEngine | None = None


def get_workflow_engine() -> WorkflowEngine:
    global _engine
    if _engine is None:
        _engine = WorkflowEngine()
    return _engine
