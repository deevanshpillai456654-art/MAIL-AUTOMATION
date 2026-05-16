"""Replay budget manager using scoped token buckets."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass
class ReplayBudget:
    max_tokens: int
    refill_per_second: float
    tokens: float = field(init=False)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.tokens = float(self.max_tokens)


class ReplayBudgetManager:
    def __init__(self, default_max: int = 200, default_refill_per_second: float = 5.0):
        self.default_max = max(1, default_max)
        self.default_refill_per_second = max(0.1, default_refill_per_second)
        self._budgets: Dict[str, ReplayBudget] = {}
        self._lock = threading.RLock()

    def configure(self, scope_key: str, max_tokens: int, refill_per_second: float) -> None:
        with self._lock:
            self._budgets[scope_key] = ReplayBudget(max(1, max_tokens), max(0.1, refill_per_second))

    def allow(self, scope_key: str, cost: int = 1) -> Tuple[bool, str]:
        cost = max(1, cost)
        with self._lock:
            budget = self._budgets.setdefault(
                scope_key,
                ReplayBudget(self.default_max, self.default_refill_per_second),
            )
            now = time.time()
            elapsed = max(0.0, now - budget.updated_at)
            budget.tokens = min(float(budget.max_tokens), budget.tokens + elapsed * budget.refill_per_second)
            budget.updated_at = now
            if budget.tokens < cost:
                return False, "replay_budget_exhausted"
            budget.tokens -= cost
            return True, "allowed"

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        with self._lock:
            return {
                scope: {"max_tokens": b.max_tokens, "tokens": round(b.tokens, 2), "refill_per_second": b.refill_per_second}
                for scope, b in self._budgets.items()
            }


__all__ = ["ReplayBudget", "ReplayBudgetManager"]
