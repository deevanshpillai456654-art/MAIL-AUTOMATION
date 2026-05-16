"""Event retention policies for replay-safe stores."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Iterable, List


@dataclass
class RetentionPolicy:
    stream: str
    retain_seconds: float
    retain_minimum: int = 0


class EventRetentionManager:
    def __init__(self):
        self._policies: Dict[str, RetentionPolicy] = {}

    def set_policy(self, policy: RetentionPolicy) -> None:
        self._policies[policy.stream] = policy

    def apply(self, stream: str, events: Iterable[Dict]) -> List[Dict]:
        events = list(events)
        policy = self._policies.get(stream)
        if not policy:
            return events
        now = time.time()
        kept = [e for e in events if now - float(e.get("created_at", now)) <= policy.retain_seconds]
        if len(kept) < policy.retain_minimum:
            kept = events[-policy.retain_minimum:]
        return kept


__all__ = ["RetentionPolicy", "EventRetentionManager"]
