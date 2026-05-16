"""
Delta Replay Engine
===================

Features:
- Event buffering (store last N events per subscription)
- Delta computation (send only changes)
- Client-side delta replay capability
- Full snapshot option for initial sync
- Event versioning (v1, v2, v3 events)
- Snapshot versioning
- Missed event recovery
- Gap detection and fill
- Event expiration policy
- Batch replay for efficiency

"""

import asyncio
import json
import time
import logging
import threading
import sqlite3
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Set, Tuple
from enum import Enum
from collections import deque, defaultdict
from contextlib import contextmanager
from backend import config

logger = logging.getLogger("realtime.delta_replay")


class EventVersion(Enum):
    V1 = "v1"
    V2 = "v2"
    V3 = "v3"


class SyncMode(Enum):
    FULL = "full"
    DELTA = "delta"
    SNAPSHOT = "snapshot"


class EventType(Enum):
    UPDATE = "update"
    DELETE = "delete"
    INSERT = "insert"
    BATCH = "batch"


@dataclass
class BufferEvent:
    """Buffered event with metadata"""
    event_id: str
    topic: str
    event_type: EventType
    payload: Any
    sequence: int
    timestamp: float
    version: EventVersion
    base_sequence: Optional[int] = None
    delta: Optional[Dict] = None


@dataclass
class Snapshot:
    """Versioned snapshot"""
    snapshot_id: str
    topic: str
    data: Dict
    version: int
    created_at: float
    expires_at: float
    sequence: int


@dataclass
class EventGap:
    """Gap in event sequence"""
    topic: str
    start_sequence: int
    end_sequence: int
    detected_at: float


@dataclass
class ReplayRequest:
    """Event replay request"""
    request_id: str
    client_id: str
    topic: str
    from_sequence: int
    to_sequence: int
    mode: SyncMode
    priority: int
    requested_at: float


class EventBuffer:
    """Circular buffer for events per subscription"""
    
    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._buffer: deque = deque(maxlen=max_size)
        self._lock = threading.RLock()
    
    def add(self, event: BufferEvent):
        """Add event to buffer"""
        with self._lock:
            self._buffer.append(event)
    
    def get_range(self, from_seq: int, to_seq: int) -> List[BufferEvent]:
        """Get events in range"""
        with self._lock:
            return [
                e for e in self._buffer
                if from_seq <= e.sequence <= to_seq
            ]
    
    def get_since(self, sequence: int, limit: int = 100) -> List[BufferEvent]:
        """Get events since sequence"""
        with self._lock:
            events = [e for e in self._buffer if e.sequence > sequence]
            return events[:limit]
    
    def get_latest(self, count: int = 10) -> List[BufferEvent]:
        """Get latest events"""
        with self._lock:
            return list(self._buffer)[-count:]
    
    def get_sequence_range(self) -> Tuple[int, int]:
        """Get min and max sequence"""
        with self._lock:
            if not self._buffer:
                return (0, 0)
            return (self._buffer[0].sequence, self._buffer[-1].sequence)
    
    def clear(self):
        """Clear buffer"""
        with self._lock:
            self._buffer.clear()


class DeltaComputer:
    """Compute deltas between states"""
    
    def __init__(self):
        self._last_states: Dict[str, Any] = {}
    
    def compute_delta(self, topic: str, new_data: Dict) -> Tuple[Dict, bool]:
        """Compute delta from last state"""
        old_data = self._last_states.get(topic, {})
        
        if not old_data:
            return new_data, True
        
        delta = {}
        has_changes = False
        
        for key, value in new_data.items():
            if key not in old_data or old_data[key] != value:
                delta[key] = value
                has_changes = True
        
        for key in old_data:
            if key not in new_data:
                delta[key] = None
                has_changes = True
        
        if has_changes:
            self._last_states[topic] = new_data.copy()
        
        return delta, has_changes
    
    def apply_delta(self, topic: str, delta: Dict) -> Dict:
        """Apply delta to current state"""
        current = self._last_states.get(topic, {}).copy()
        
        for key, value in delta.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        
        self._last_states[topic] = current
        return current
    
    def set_full_state(self, topic: str, data: Dict):
        """Set full state"""
        self._last_states[topic] = data.copy()
    
    def get_state(self, topic: str) -> Optional[Dict]:
        """Get current state"""
        return self._last_states.get(topic)


class SnapshotStore:
    """Store versioned snapshots"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or (Path(config.DATA_DIR) / "snapshots.db")
        self._snapshots: Dict[str, Snapshot] = {}
        self._lock = threading.RLock()
        self._init_db()
    
    def _init_db(self):
        """Initialize snapshot database"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                data TEXT NOT NULL,
                version INTEGER NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                sequence INTEGER NOT NULL
            )
        """)
        
        cursor.execute("""
            CREATE INDEX idx_snapshots_topic ON snapshots(topic, version DESC)
        """)
        
        conn.commit()
        conn.close()
    
    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def save_snapshot(self, snapshot: Snapshot):
        """Save snapshot"""
        with self._lock:
            self._snapshots[snapshot.snapshot_id] = snapshot
            
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO snapshots
                    (snapshot_id, topic, data, version, created_at, expires_at, sequence)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    snapshot.snapshot_id,
                    snapshot.topic,
                    json.dumps(snapshot.data),
                    snapshot.version,
                    snapshot.created_at,
                    snapshot.expires_at,
                    snapshot.sequence
                ))
                conn.commit()
    
    def get_snapshot(self, topic: str, version: int = None) -> Optional[Snapshot]:
        """Get snapshot for topic"""
        with self._lock:
            if version:
                for sid, snap in self._snapshots.items():
                    if snap.topic == topic and snap.version == version:
                        return snap
            
            candidates = [s for s in self._snapshots.values() if s.topic == topic]
            if candidates:
                return max(candidates, key=lambda s: s.version)
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if version:
                cursor.execute("""
                    SELECT * FROM snapshots WHERE topic = ? AND version = ?
                """, (topic, version))
            else:
                cursor.execute("""
                    SELECT * FROM snapshots WHERE topic = ? ORDER BY version DESC LIMIT 1
                """, (topic,))
            
            row = cursor.fetchone()
            if row:
                return Snapshot(
                    snapshot_id=row["snapshot_id"],
                    topic=row["topic"],
                    data=json.loads(row["data"]),
                    version=row["version"],
                    created_at=row["created_at"],
                    expires_at=row["expires_at"],
                    sequence=row["sequence"]
                )
        
        return None
    
    def cleanup_expired(self) -> int:
        """Clean up expired snapshots"""
        now = time.time()
        expired_ids = []
        
        with self._lock:
            for sid, snap in list(self._snapshots.items()):
                if snap.expires_at < now:
                    expired_ids.append(sid)
                    del self._snapshots[sid]
        
        if expired_ids:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    DELETE FROM snapshots WHERE snapshot_id IN ({})
                """.format(",".join("?" * len(expired_ids))), expired_ids)
                conn.commit()
        
        return len(expired_ids)


class MissedEventDetector:
    """Detect and handle missed events"""
    
    def __init__(self):
        self._gaps: List[EventGap] = []
        self._lock = threading.Lock()
    
    def detect_gaps(self, topic: str, sequences: List[int]) -> List[EventGap]:
        """Detect gaps in sequence numbers"""
        if not sequences:
            return []
        
        sequences = sorted(sequences)
        gaps = []
        
        for i in range(len(sequences) - 1):
            if sequences[i + 1] - sequences[i] > 1:
                gap = EventGap(
                    topic=topic,
                    start_sequence=sequences[i],
                    end_sequence=sequences[i + 1],
                    detected_at=time.time()
                )
                gaps.append(gap)
        
        with self._lock:
            self._gaps.extend(gaps)
        
        return gaps
    
    def get_pending_gaps(self, topic: str = None) -> List[EventGap]:
        """Get pending gaps"""
        with self._lock:
            if topic:
                return [g for g in self._gaps if g.topic == topic]
            return list(self._gaps)
    
    def clear_gap(self, topic: str, start: int, end: int):
        """Clear a gap after replay"""
        with self._lock:
            self._gaps = [
                g for g in self._gaps
                if not (g.topic == topic and g.start_sequence == start and g.end_sequence == end)
            ]


class ReplayScheduler:
    """Schedule and batch replay requests"""
    
    def __init__(self, batch_size: int = 50, batch_delay: float = 0.1):
        self.batch_size = batch_size
        self.batch_delay = batch_delay
        self._pending: deque = deque(maxlen=1000)
        self._priority_queue: List[ReplayRequest] = []
        self._lock = threading.Lock()
        self._running = False
    
    def add_request(self, request: ReplayRequest):
        """Add replay request"""
        with self._lock:
            if request.priority > 5:
                self._priority_queue.append(request)
                self._priority_queue.sort(key=lambda r: r.priority, reverse=True)
            else:
                self._pending.append(request)
    
    def get_batch(self) -> List[ReplayRequest]:
        """Get next batch of requests"""
        batch = []
        
        with self._lock:
            while self._priority_queue and len(batch) < self.batch_size:
                batch.append(self._priority_queue.pop(0))
            
            while len(batch) < self.batch_size and self._pending:
                batch.append(self._pending.popleft())
        
        return batch
    
    def has_pending(self) -> bool:
        """Check if there are pending requests"""
        with self._lock:
            return bool(self._priority_queue or self._pending)


class DeltaReplayEngine:
    """
    Delta replay engine with buffering, recovery, and versioning.
    """
    
    def __init__(self, buffer_size: int = 1000, retention_hours: int = 24):
        self.buffer_size = buffer_size
        self.retention_hours = retention_hours
        
        self._buffers: Dict[str, EventBuffer] = {}
        self._delta_computer = DeltaComputer()
        self._snapshot_store = SnapshotStore()
        self._gap_detector = MissedEventDetector()
        self._replay_scheduler = ReplayScheduler()
        
        self._event_sequences: Dict[str, int] = defaultdict(int)
        self._client_states: Dict[str, Dict] = {}
        
        self._lock = threading.RLock()
        
        self.on_gap_detected: Optional[Callable] = None
        self.on_batch_replay: Optional[Callable] = None
        
        logger.info(f"DeltaReplayEngine initialized (buffer={buffer_size}, retention={retention_hours}h)")
    
    def _get_buffer(self, topic: str) -> EventBuffer:
        """Get or create buffer for topic"""
        with self._lock:
            if topic not in self._buffers:
                self._buffers[topic] = EventBuffer(self.buffer_size)
            return self._buffers[topic]
    
    def publish_event(self, topic: str, payload: Any, event_type: EventType = EventType.UPDATE,
                     version: EventVersion = EventVersion.V3) -> BufferEvent:
        """Publish event with versioning"""
        with self._lock:
            sequence = self._event_sequences[topic] + 1
            self._event_sequences[topic] = sequence
        
        is_delta = version == EventVersion.V3
        delta = None
        base_sequence = None
        
        if is_delta:
            delta, _ = self._delta_computer.compute_delta(topic, payload)
            base_sequence = sequence - 1
        
        event = BufferEvent(
            event_id=f"evt_{secrets.token_hex(8)}",
            topic=topic,
            event_type=event_type,
            payload=payload,
            sequence=sequence,
            timestamp=time.time(),
            version=version,
            base_sequence=base_sequence,
            delta=delta
        )
        
        buffer = self._get_buffer(topic)
        buffer.add(event)
        
        if not is_delta:
            self._delta_computer.set_full_state(topic, payload)
        
        logger.debug(f"Published event: {event.event_id} seq={sequence} topic={topic}")
        
        return event
    
    def get_events_since(self, topic: str, sequence: int, limit: int = 100) -> List[BufferEvent]:
        """Get events since sequence"""
        buffer = self._get_buffer(topic)
        return buffer.get_since(sequence, limit)
    
    def get_delta(self, topic: str, client_sequence: int) -> Dict:
        """Get delta for client"""
        events = self.get_events_since(topic, client_sequence)
        
        if not events:
            return {"type": "no_changes", "sequence": self._event_sequences[topic]}
        
        full_snapshot = self._delta_computer.get_state(topic)
        
        deltas = []
        for event in events:
            if event.delta:
                deltas.append({
                    "event_id": event.event_id,
                    "sequence": event.sequence,
                    "delta": event.delta,
                    "version": event.version.value,
                    "type": event.event_type.value
                })
            else:
                deltas.append({
                    "event_id": event.event_id,
                    "sequence": event.sequence,
                    "full": event.payload,
                    "version": event.version.value,
                    "type": event.event_type.value
                })
        
        return {
            "type": "delta_sync",
            "sequence": self._event_sequences[topic],
            "deltas": deltas,
            "snapshot": full_snapshot
        }
    
    def get_full_snapshot(self, topic: str, version: int = None) -> Optional[Dict]:
        """Get full snapshot"""
        if version:
            snapshot = self._snapshot_store.get_snapshot(topic, version)
            if snapshot:
                return snapshot.data
        
        state = self._delta_computer.get_state(topic)
        
        if state:
            snapshot = Snapshot(
                snapshot_id=f"snap_{secrets.token_hex(8)}",
                topic=topic,
                data=state,
                version=self._event_sequences[topic],
                created_at=time.time(),
                expires_at=time.time() + (self.retention_hours * 3600),
                sequence=self._event_sequences[topic]
            )
            self._snapshot_store.save_snapshot(snapshot)
        
        return state
    
    def create_recovery_request(self, client_id: str, topic: str, 
                                last_sequence: int) -> ReplayRequest:
        """Create missed event recovery request"""
        request = ReplayRequest(
            request_id=f"req_{secrets.token_hex(8)}",
            client_id=client_id,
            topic=topic,
            from_sequence=last_sequence + 1,
            to_sequence=self._event_sequences[topic],
            mode=SyncMode.DELTA,
            priority=7,
            requested_at=time.time()
        )
        
        self._replay_scheduler.add_request(request)
        
        gaps = self._gap_detector.detect_gaps(
            topic,
            list(range(last_sequence + 1, self._event_sequences[topic] + 1))
        )
        
        if gaps and self.on_gap_detected:
            self.on_gap_detected(topic, gaps)
        
        return request
    
    def get_recovery_events(self, topic: str, from_seq: int, to_seq: int) -> List[BufferEvent]:
        """Get events for recovery"""
        buffer = self._get_buffer(topic)
        return buffer.get_range(from_seq, to_seq)
    
    def replay_batch(self) -> List[Dict]:
        """Process replay batch"""
        batch = self._replay_scheduler.get_batch()
        
        results = []
        
        for request in batch:
            events = self.get_recovery_events(
                request.topic,
                request.from_sequence,
                min(request.to_sequence, request.from_sequence + self._replay_scheduler.batch_size)
            )
            
            results.append({
                "request_id": request.request_id,
                "topic": request.topic,
                "events": [
                    {
                        "event_id": e.event_id,
                        "sequence": e.sequence,
                        "payload": e.payload,
                        "version": e.version.value,
                        "delta": e.delta
                    }
                    for e in events
                ],
                "total": len(events)
            })
            
            if events and events[-1].sequence >= request.to_sequence:
                self._gap_detector.clear_gap(
                    request.topic, 
                    request.from_sequence,
                    request.to_sequence
                )
        
        if results and self.on_batch_replay:
            self.on_batch_replay(results)
        
        return results
    
    def store_client_state(self, client_id: str, topic: str, sequence: int):
        """Store client state for resumption"""
        key = f"{client_id}:{topic}"
        self._client_states[key] = {
            "sequence": sequence,
            "timestamp": time.time()
        }
    
    def get_client_state(self, client_id: str, topic: str) -> Optional[int]:
        """Get client state for resumption"""
        key = f"{client_id}:{topic}"
        state = self._client_states.get(key)
        if state:
            return state["sequence"]
        return None
    
    def get_sequence_info(self, topic: str) -> Dict:
        """Get sequence information"""
        buffer = self._get_buffer(topic)
        min_seq, max_seq = buffer.get_sequence_range()
        
        return {
            "topic": topic,
            "current_sequence": self._event_sequences[topic],
            "buffer_min": min_seq,
            "buffer_max": max_seq,
            "has_snapshot": self._delta_computer.get_state(topic) is not None
        }
    
    def get_stats(self) -> Dict:
        """Get engine statistics"""
        with self._lock:
            return {
                "topics": list(self._event_sequences.keys()),
                "total_sequences": dict(self._event_sequences),
                "pending_replays": len(self._replay_scheduler._pending),
                "priority_replays": len(self._replay_scheduler._priority_queue),
                "gaps_detected": len(self._gap_detector._gaps)
            }
    
    def cleanup(self) -> int:
        """Clean up old events"""
        cleaned = 0
        
        with self._lock:
            for topic, buffer in self._buffers.items():
                old_size = len(buffer._buffer)
                buffer.clear()
                cleaned += old_size
        
        self._snapshot_store.cleanup_expired()
        
        cutoff = time.time() - (self.retention_hours * 3600)
        with self._lock:
            expired_clients = [
                key for key, state in self._client_states.items()
                if state["timestamp"] < cutoff
            ]
            for key in expired_clients:
                del self._client_states[key]
            cleaned += len(expired_clients)
        
        logger.info(f"Cleaned up {cleaned} items")
        return cleaned


_global_engine: Optional[DeltaReplayEngine] = None


def get_delta_replay_engine() -> DeltaReplayEngine:
    """Get global delta replay engine"""
    global _global_engine
    if _global_engine is None:
        _global_engine = DeltaReplayEngine()
    return _global_engine


import secrets
from contextlib import contextmanager
