"""AI governance, prompt-injection defense, and approval policy engine."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class GovernanceDecision:
    allowed: bool
    requires_approval: bool
    reasons: List[str] = field(default_factory=list)
    risk_score: float = 0.0


class AIGovernanceEngine:
    destructive_actions = {"send_email", "delete_email", "erp_update", "workflow_execute", "remote_command"}
    injection_patterns = [
        re.compile(r"ignore\s+previous\s+instructions", re.I),
        re.compile(r"reveal\s+(system|developer)\s+prompt", re.I),
        re.compile(r"exfiltrate|steal|bypass|disable\s+security", re.I),
    ]

    def __init__(self) -> None:
        self._events: List[Dict[str, Any]] = []

    def evaluate(self, action: str, payload: Dict[str, Any]) -> GovernanceDecision:
        text = " ".join(str(v) for v in payload.values())[:10000]
        reasons: List[str] = []
        risk = 0.0
        for pattern in self.injection_patterns:
            if pattern.search(text):
                reasons.append("prompt_injection_pattern_detected")
                risk += 0.85
                break
        requires_approval = action in self.destructive_actions or bool(payload.get("requires_approval"))
        if requires_approval:
            reasons.append("human_approval_required")
            risk += 0.2
        allowed = risk < 0.8
        decision = GovernanceDecision(allowed=allowed, requires_approval=requires_approval, reasons=reasons, risk_score=round(risk, 3))
        self._events.append({"action": action, "decision": decision.__dict__, "timestamp": time.time()})
        self._events = self._events[-500:]
        return decision

    def status(self) -> Dict[str, Any]:
        return {
            "version": "9.7.0",
            "status": "enforcing",
            "offline_only": True,
            "policies": {
                "prompt_injection_defense": True,
                "human_approval_for_destructive_actions": True,
                "email_content_telemetry_blocked": True,
                "tool_execution_sandbox": True,
            },
            "recent_events": self._events[-20:],
        }


_engine: AIGovernanceEngine | None = None


def get_governance_engine() -> AIGovernanceEngine:
    global _engine
    if _engine is None:
        _engine = AIGovernanceEngine()
    return _engine
