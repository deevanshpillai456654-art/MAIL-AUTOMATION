"""Chaos engine public wrapper."""
from __future__ import annotations

import threading
from enum import Enum
from typing import Any, Dict, Set


class ScenarioType(str, Enum):
    PROVIDER_OUTAGE = "provider_outage"
    QUEUE_CORRUPTION = "queue_corruption"
    MEMORY_EXHAUSTION = "memory_exhaustion"
    TOKEN_CORRUPTION = "token_corruption"


class ChaosEngine:
    def __init__(self, telemetry: Any = None):
        self.telemetry = telemetry
        self._active: Set[ScenarioType] = set()
        self._lock = threading.RLock()
        self._injections = 0

    def inject_scenario(self, scenario_type: ScenarioType, **kwargs: Any) -> None:
        del kwargs
        with self._lock:
            self._active.add(scenario_type)
            self._injections += 1

    def inject_chaos(self) -> Dict[str, Any]:
        self.inject_scenario(ScenarioType.PROVIDER_OUTAGE)
        return {"status": "chaos_injected", "active_scenarios": len(self._active)}

    def stop_scenario(self, scenario_type: ScenarioType) -> None:
        with self._lock:
            self._active.discard(scenario_type)

    def is_scenario_active(self, scenario_type: ScenarioType) -> bool:
        with self._lock:
            return scenario_type in self._active

    def get_chaos_metrics(self) -> Dict[str, int]:
        with self._lock:
            return {"active_scenarios": len(self._active), "injections": self._injections}


__all__ = ["ChaosEngine", "ScenarioType"]
