"""Replay history pruning utilities."""
from __future__ import annotations

import time
from typing import Dict, Iterable, List, Set


def prune_replay_events(events: Iterable[Dict], retention_seconds: float, protected_ids: Iterable[str] = ()) -> List[Dict]:
    now = time.time()
    protected: Set[str] = {str(item) for item in protected_ids}
    kept: List[Dict] = []
    for event in events:
        event_id = str(event.get("event_id") or event.get("id") or "")
        created_at = float(event.get("created_at") or event.get("timestamp") or now)
        if event_id in protected or now - created_at <= retention_seconds:
            kept.append(dict(event))
    return kept


__all__ = ["prune_replay_events"]
