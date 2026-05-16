"""
Stream compaction: drop acknowledged / tombstoned events before a cursor.

Operates on in-memory event lists or adapter-provided stores.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("event_compaction")


@dataclass
class CompactionCursor:
    stream_id: str
    up_to_sequence: int
    updated_at: float


class EventCompactor:
    def __init__(self):
        self._cursors: Dict[str, CompactionCursor] = {}
        self._lock = threading.RLock()

    def set_cursor(self, stream_id: str, up_to_sequence: int) -> None:
        with self._lock:
            self._cursors[stream_id] = CompactionCursor(
                stream_id=stream_id,
                up_to_sequence=up_to_sequence,
                updated_at=time.time(),
            )

    def compact_in_memory(
        self,
        events: List[Dict[str, Any]],
        sequence_key: str = "sequence",
        tombstone_key: str = "tombstone",
    ) -> List[Dict[str, Any]]:
        return [e for e in events if not e.get(tombstone_key)]

    def prune_by_cursor(
        self,
        stream_id: str,
        events: List[Dict[str, Any]],
        sequence_key: str = "sequence",
    ) -> List[Dict[str, Any]]:
        with self._lock:
            cur = self._cursors.get(stream_id)
        if not cur:
            return list(events)
        return [e for e in events if int(e.get(sequence_key, 0)) > cur.up_to_sequence]


__all__ = ["CompactionCursor", "EventCompactor"]
