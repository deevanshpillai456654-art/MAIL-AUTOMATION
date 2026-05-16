"""
Periodic snapshots of stream state to accelerate replay from a known offset.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("event_snapshot")


@dataclass
class StreamSnapshot:
    snapshot_id: str
    stream_id: str
    up_to_sequence: int
    state: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    compressed: bool = False


class EventSnapshotter:
    def __init__(self, storage_dir: Optional[Path] = None):
        self._dir = storage_dir
        self._latest: Dict[str, StreamSnapshot] = {}
        self._lock = threading.RLock()

    def capture(self, stream_id: str, up_to_sequence: int, state: Dict[str, Any]) -> str:
        snap = StreamSnapshot(
            snapshot_id=f"snap_{uuid.uuid4().hex[:10]}",
            stream_id=stream_id,
            up_to_sequence=up_to_sequence,
            state=dict(state),
        )
        with self._lock:
            self._latest[stream_id] = snap
        if self._dir:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self._dir / f"{stream_id}_{snap.snapshot_id}.json"
            path.write_text(json.dumps(snap.__dict__, default=str), encoding="utf-8")
        logger.info("Snapshot %s stream=%s seq<=%s", snap.snapshot_id, stream_id, up_to_sequence)
        return snap.snapshot_id

    def latest(self, stream_id: str) -> Optional[StreamSnapshot]:
        with self._lock:
            s = self._latest.get(stream_id)
            return s


__all__ = ["StreamSnapshot", "EventSnapshotter"]
