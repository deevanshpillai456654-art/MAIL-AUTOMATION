"""
Durable Event Store - Append-Only Event Journal
================================================

Enterprise-grade durable event storage with:
- Append-only event log
- Persistent event journal
- Consumer group offsets
- Replay-safe processing
- Event idempotency
- Event snapshots
- Event checkpoints
- Dead letter queue
- Event audit trails
"""

import hashlib
import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from backend import config

logger = logging.getLogger("event.store")


class EventStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    POISON = "poison"
    REPLAYED = "replayed"


class EventPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


@dataclass
class DurableEvent:
    """Durable event with full lifecycle tracking"""
    event_id: str
    topic: str
    payload: Dict[str, Any]
    priority: EventPriority = EventPriority.NORMAL
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    source: str = "system"
    timestamp: float = field(default_factory=time.time)
    expires_at: Optional[float] = None

    # Processing metadata
    status: EventStatus = EventStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3
    processed_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None

    # Idempotency
    idempotency_key: Optional[str] = None

    # Snapshots
    snapshot_id: Optional[str] = None


@dataclass
class EventSnapshot:
    """Event checkpoint for replay"""
    snapshot_id: str
    event_id: str
    topic: str
    checkpoint_data: Dict[str, Any]
    created_at: float = field(default_factory=time.time)


@dataclass
class ConsumerOffset:
    """Consumer group offset tracking"""
    group_id: str
    topic: str
    offset: int
    committed_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)


@dataclass
class EventCheckpoint:
    """Workflow checkpoint for recovery"""
    checkpoint_id: str
    workflow_id: str
    step: str
    event_id: str
    state: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    is_complete: bool = False


class DurableEventStore:
    """
    Enterprise-grade durable event store.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.DB_PATH
        self.data_dir = Path(self.db_path).parent / "event_store"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.event_db = str(self.data_dir / "events.db")
        self.journal_db = str(self.data_dir / "journal.db")
        self.snapshot_db = str(self.data_dir / "snapshots.db")
        self.dlq_db = str(self.data_dir / "dlq.db")

        self._lock = threading.RLock()
        self._idempotency_keys: Set[str] = set()
        self._max_idempotency_keys = 10000

        self._init_databases()

        logger.info(f"Event Store initialized at {self.data_dir}")

    def _init_databases(self):
        """Initialize all event databases"""
        # Main event log
        conn = sqlite3.connect(self.event_db)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL,
                priority INTEGER DEFAULT 2,
                correlation_id TEXT,
                causation_id TEXT,
                source TEXT DEFAULT 'system',
                timestamp REAL NOT NULL,
                expires_at REAL,
                status TEXT DEFAULT 'pending',
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                processed_at REAL,
                completed_at REAL,
                error TEXT,
                idempotency_key TEXT,
                snapshot_id TEXT,
                checksum TEXT,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_topic ON events(topic)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_status ON events(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_idempotency ON events(idempotency_key)")

        conn.commit()
        conn.close()

        # Consumer offsets
        conn = sqlite3.connect(self.journal_db)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS consumer_offsets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                offset INTEGER DEFAULT 0,
                committed_at REAL,
                last_heartbeat REAL,
                UNIQUE(group_id, topic)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                workflow_id TEXT NOT NULL,
                step TEXT NOT NULL,
                event_id TEXT NOT NULL,
                state TEXT NOT NULL,
                created_at REAL,
                is_complete INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS event_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                timestamp REAL
            )
        """)

        conn.commit()
        conn.close()

        # Snapshots
        conn = sqlite3.connect(self.snapshot_db)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                snapshot_id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                checkpoint_data TEXT NOT NULL,
                created_at REAL
            )
        """)

        conn.commit()
        conn.close()

        # Dead letter queue
        conn = sqlite3.connect(self.dlq_db)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dlq (
                event_id TEXT PRIMARY KEY,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL,
                error TEXT,
                failure_reason TEXT,
                retry_count INTEGER DEFAULT 0,
                original_timestamp REAL,
                failed_at REAL,
                quarantined_at REAL
            )
        """)

        conn.commit()
        conn.close()

    @contextmanager
    def _get_connection(self, db_path: str):
        conn = sqlite3.connect(db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def append(self, event: DurableEvent) -> bool:
        """Append event to durable log"""
        with self._lock:
            # Check idempotency
            if event.idempotency_key:
                if self._is_idempotent(event.idempotency_key):
                    logger.debug(f"Duplicate event skipped: {event.idempotency_key}")
                    return False
                self._add_idempotency_key(event.idempotency_key)

            # Calculate checksum
            checksum = self._calculate_checksum(event)

            with self._get_connection(self.event_db) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT OR REPLACE INTO events (
                        event_id, topic, payload, priority, correlation_id,
                        causation_id, source, timestamp, expires_at,
                        status, retry_count, max_retries, error,
                        idempotency_key, snapshot_id, checksum
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event.event_id,
                    event.topic,
                    json.dumps(event.payload),
                    event.priority.value,
                    event.correlation_id,
                    event.causation_id,
                    event.source,
                    event.timestamp,
                    event.expires_at,
                    event.status.value,
                    event.retry_count,
                    event.max_retries,
                    event.error,
                    event.idempotency_key,
                    event.snapshot_id,
                    checksum
                ))
                conn.commit()

            # Journal the append
            self._journal(event.event_id, "APPEND", f"Topic: {event.topic}")

            logger.debug(f"Event appended: {event.event_id} to {event.topic}")
            return True

    def _is_idempotent(self, key: str) -> bool:
        """Check if key was already processed"""
        return key in self._idempotency_keys

    def _add_idempotency_key(self, key: str):
        """Add idempotency key to cache"""
        self._idempotency_keys.add(key)
        # Evict old keys if needed
        if len(self._idempotency_keys) > self._max_idempotency_keys:
            # Keep recent ones
            keys = list(self._idempotency_keys)
            self._idempotency_keys = set(keys[-self._max_idempotency_keys//2:])

    def _calculate_checksum(self, event: DurableEvent) -> str:
        """Calculate event checksum"""
        content = f"{event.event_id}{event.topic}{json.dumps(event.payload, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def get(self, event_id: str) -> Optional[DurableEvent]:
        """Get event by ID"""
        with self._get_connection(self.event_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_event(row)
        return None

    def get_by_topic(self, topic: str, limit: int = 100, offset: int = 0) -> List[DurableEvent]:
        """Get events by topic"""
        events = []
        with self._get_connection(self.event_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM events 
                WHERE topic = ? 
                ORDER BY timestamp ASC 
                LIMIT ? OFFSET ?
            """, (topic, limit, offset))
            for row in cursor.fetchall():
                events.append(self._row_to_event(row))
        return events

    def get_pending(self, topic: str, limit: int = 100) -> List[DurableEvent]:
        """Get pending events for a topic"""
        events = []
        with self._get_connection(self.event_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM events 
                WHERE topic = ? AND status = 'pending'
                ORDER BY priority ASC, timestamp ASC
                LIMIT ?
            """, (topic, limit))
            for row in cursor.fetchall():
                events.append(self._row_to_event(row))
        return events

    def update_status(self, event_id: str, status: EventStatus, error: str = None):
        """Update event status"""
        with self._lock:
            with self._get_connection(self.event_db) as conn:
                cursor = conn.cursor()
                if status == EventStatus.COMPLETED:
                    cursor.execute("""
                        UPDATE events 
                        SET status = ?, completed_at = ?, error = ?
                        WHERE event_id = ?
                    """, (status.value, time.time(), error, event_id))
                elif status == EventStatus.PROCESSING:
                    cursor.execute("""
                        UPDATE events 
                        SET status = ?, processed_at = ?
                        WHERE event_id = ?
                    """, (status.value, time.time(), event_id))
                else:
                    cursor.execute("""
                        UPDATE events 
                        SET status = ?, error = ?, retry_count = retry_count + 1
                        WHERE event_id = ?
                    """, (status.value, error, event_id))
                conn.commit()

            self._journal(event_id, "STATUS_UPDATE", f"Status: {status.value}")

    def mark_poison(self, event_id: str, reason: str):
        """Mark event as poison message"""
        with self._lock:
            event = self.get(event_id)
            if not event:
                return

            # Move to DLQ
            with self._get_connection(self.dlq_db) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO dlq (event_id, topic, payload, error, failure_reason, retry_count, original_timestamp, failed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    event_id,
                    event.topic,
                    json.dumps(event.payload),
                    event.error or "Unknown",
                    reason,
                    event.retry_count,
                    event.timestamp,
                    time.time()
                ))
                conn.commit()

            # Mark as poison in main log
            with self._get_connection(self.event_db) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE events SET status = 'poison' WHERE event_id = ?", (event_id,))
                conn.commit()

            self._journal(event_id, "POISON_DETECTED", reason)
            logger.warning(f"Poison message detected: {event_id} - {reason}")

    def _journal(self, event_id: str, action: str, details: str):
        """Log event action to journal"""
        try:
            with self._get_connection(self.journal_db) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO event_journal (event_id, action, details, timestamp)
                    VALUES (?, ?, ?, ?)
                """, (event_id, action, details, time.time()))
                conn.commit()
        except Exception as e:
            logger.error(f"Journal write failed: {e}")

    def save_checkpoint(self, checkpoint: EventCheckpoint):
        """Save workflow checkpoint"""
        with self._get_connection(self.journal_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO checkpoints 
                (checkpoint_id, workflow_id, step, event_id, state, created_at, is_complete)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                checkpoint.checkpoint_id,
                checkpoint.workflow_id,
                checkpoint.step,
                checkpoint.event_id,
                json.dumps(checkpoint.state),
                checkpoint.created_at,
                1 if checkpoint.is_complete else 0
            ))
            conn.commit()

    def get_checkpoint(self, checkpoint_id: str) -> Optional[EventCheckpoint]:
        """Get workflow checkpoint"""
        with self._get_connection(self.journal_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,))
            row = cursor.fetchone()
            if row:
                return EventCheckpoint(
                    checkpoint_id=row["checkpoint_id"],
                    workflow_id=row["workflow_id"],
                    step=row["step"],
                    event_id=row["event_id"],
                    state=json.loads(row["state"]),
                    created_at=row["created_at"],
                    is_complete=bool(row["is_complete"])
                )
        return None

    def get_workflow_checkpoints(self, workflow_id: str) -> List[EventCheckpoint]:
        """Get all checkpoints for a workflow"""
        checkpoints = []
        with self._get_connection(self.journal_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM checkpoints 
                WHERE workflow_id = ? 
                ORDER BY created_at ASC
            """, (workflow_id,))
            for row in cursor.fetchall():
                checkpoints.append(EventCheckpoint(
                    checkpoint_id=row["checkpoint_id"],
                    workflow_id=row["workflow_id"],
                    step=row["step"],
                    event_id=row["event_id"],
                    state=json.loads(row["state"]),
                    created_at=row["created_at"],
                    is_complete=bool(row["is_complete"])
                ))
        return checkpoints

    def commit_offset(self, group_id: str, topic: str, offset: int):
        """Commit consumer offset"""
        with self._get_connection(self.journal_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO consumer_offsets 
                (group_id, topic, offset, committed_at, last_heartbeat)
                VALUES (?, ?, ?, ?, ?)
            """, (group_id, topic, offset, time.time(), time.time()))
            conn.commit()

    def get_offset(self, group_id: str, topic: str) -> int:
        """Get consumer offset"""
        with self._get_connection(self.journal_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT offset FROM consumer_offsets 
                WHERE group_id = ? AND topic = ?
            """, (group_id, topic))
            row = cursor.fetchone()
            return row["offset"] if row else 0

    def save_snapshot(self, snapshot: EventSnapshot):
        """Save event snapshot"""
        with self._get_connection(self.snapshot_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO snapshots 
                (snapshot_id, event_id, topic, checkpoint_data, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                snapshot.snapshot_id,
                snapshot.event_id,
                snapshot.topic,
                json.dumps(snapshot.checkpoint_data),
                snapshot.created_at
            ))
            conn.commit()

    def get_snapshot(self, snapshot_id: str) -> Optional[EventSnapshot]:
        """Get event snapshot"""
        with self._get_connection(self.snapshot_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,))
            row = cursor.fetchone()
            if row:
                return EventSnapshot(
                    snapshot_id=row["snapshot_id"],
                    event_id=row["event_id"],
                    topic=row["topic"],
                    checkpoint_data=json.loads(row["checkpoint_data"]),
                    created_at=row["created_at"]
                )
        return None

    def _row_to_event(self, row) -> DurableEvent:
        """Convert database row to event"""
        return DurableEvent(
            event_id=row["event_id"],
            topic=row["topic"],
            payload=json.loads(row["payload"]),
            priority=EventPriority(row["priority"]),
            correlation_id=row["correlation_id"],
            causation_id=row["causation_id"],
            source=row["source"],
            timestamp=row["timestamp"],
            expires_at=row["expires_at"],
            status=EventStatus(row["status"]),
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            processed_at=row["processed_at"],
            completed_at=row["completed_at"],
            error=row["error"],
            idempotency_key=row["idempotency_key"],
            snapshot_id=row["snapshot_id"]
        )

    def get_stats(self) -> Dict:
        """Get event store statistics"""
        with self._get_connection(self.event_db) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) as total FROM events")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) as count FROM events WHERE status = 'pending'")
            pending = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM events WHERE status = 'completed'")
            completed = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM events WHERE status = 'failed'")
            failed = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) as count FROM events WHERE status = 'poison'")
            poison = cursor.fetchone()["count"]

        with self._get_connection(self.dlq_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM dlq")
            dlq_count = cursor.fetchone()["count"]

        return {
            "total_events": total,
            "pending": pending,
            "completed": completed,
            "failed": failed,
            "poison": poison,
            "dlq_size": dlq_count,
            "idempotency_keys": len(self._idempotency_keys)
        }

    def cleanup_old_events(self, days: int = 30):
        """Clean up old completed events"""
        cutoff = time.time() - (days * 86400)

        with self._get_connection(self.event_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM events 
                WHERE status = 'completed' AND completed_at < ?
            """, (cutoff,))
            deleted = cursor.rowcount
            conn.commit()

        logger.info(f"Cleaned up {deleted} old events")
        return deleted

    def replay_from_offset(self, topic: str, group_id: str, handler: Callable[[DurableEvent], None]):
        """Replay events from offset with handler"""
        offset = self.get_offset(group_id, topic)

        events = self.get_by_topic(topic, limit=1000)

        for i, event in enumerate(events):
            if i < offset:
                continue

            try:
                handler(event)
                self.commit_offset(group_id, topic, i + 1)
            except Exception as e:
                logger.error(f"Replay handler failed for {event.event_id}: {e}")
                raise


# Global event store instance
_event_store: Optional[DurableEventStore] = None


def get_event_store() -> DurableEventStore:
    """Get or create global event store"""
    global _event_store
    if _event_store is None:
        _event_store = DurableEventStore()
    return _event_store
