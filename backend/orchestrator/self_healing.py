"""Self-healing orchestration primitives."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List


@dataclass
class HealingResult:
    component: str
    status: str
    actions: List[str] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)


class SelfHealingOrchestrator:
    def __init__(self):
        self._checks: Dict[str, Callable[[], bool]] = {}
        self._recoveries: Dict[str, Callable[[], str]] = {}
        self.history: List[HealingResult] = []

    def register(self, component: str, health_check: Callable[[], bool], recovery: Callable[[], str] | None = None) -> None:
        self._checks[component] = health_check
        if recovery:
            self._recoveries[component] = recovery

    def heal(self) -> Dict:
        results: List[HealingResult] = []
        for component, check in self._checks.items():
            try:
                healthy = bool(check())
            except Exception:
                healthy = False
            actions: List[str] = []
            status = "healthy" if healthy else "degraded"
            if not healthy and component in self._recoveries:
                actions.append(self._recoveries[component]())
                status = "recovery_attempted"
            result = HealingResult(component, status, actions)
            self.history.append(result)
            results.append(result)
        overall = "healthy" if all(r.status == "healthy" for r in results) else "recovery_required"
        return {"status": overall, "components": [r.__dict__ for r in results]}


__all__ = ["SelfHealingOrchestrator", "HealingResult"]
