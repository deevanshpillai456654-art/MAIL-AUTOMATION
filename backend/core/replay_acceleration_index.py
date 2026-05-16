"""In-memory replay acceleration index."""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class ReplayIndexEntry:
    offset: int
    event_id: str


class ReplayAccelerationIndex:
    def __init__(self):
        self._index: Dict[str, List[ReplayIndexEntry]] = {}

    def add(self, stream: str, offset: int, event_id: str) -> None:
        entries = self._index.setdefault(stream, [])
        entries.append(ReplayIndexEntry(offset, event_id))
        entries.sort(key=lambda e: e.offset)

    def after(self, stream: str, offset: int, limit: int = 250) -> List[ReplayIndexEntry]:
        entries = self._index.get(stream, [])
        offsets = [e.offset for e in entries]
        start = bisect_right(offsets, offset)
        return entries[start:start + max(1, limit)]


__all__ = ["ReplayIndexEntry", "ReplayAccelerationIndex"]
