"""Delta replay engine with scope-local dedupe."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set


class DeltaReplayEngine:
    def build_delta(self, events: Iterable[Dict], cursor: Optional[str] = None, limit: int = 250) -> List[Dict]:
        materialized = list(events)
        if cursor:
            for idx, event in enumerate(materialized):
                if str(event.get("event_id") or event.get("id")) == str(cursor):
                    materialized = materialized[idx + 1:]
                    break
        seen: Set[str] = set()
        delta: List[Dict] = []
        for event in materialized:
            event_id = str(event.get("event_id") or event.get("id") or repr(event))
            if event_id in seen:
                continue
            seen.add(event_id)
            delta.append(dict(event))
            if len(delta) >= limit:
                break
        return delta


__all__ = ["DeltaReplayEngine"]
