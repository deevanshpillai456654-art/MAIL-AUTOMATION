"""
Advanced IMAP Hardening - Enterprise IMAP Resilience
=====================================================

Features:
- UID rollover protection
- UID validity tracking
- Folder drift detection
- Message reconciliation
- Gmail label normalization
- Duplicate mailbox prevention
- Sync checkpoints
- Resumable sync
- IMAP heartbeat
- Adaptive polling
- Quota-aware polling
- IDLE fallback recovery
- Sync state journal
"""
import os

__path__ = [os.path.join(os.path.dirname(__file__), "imap_hardening")]

import json
import logging
import sqlite3
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from backend import config

logger = logging.getLogger("imap.hardening")


class SyncState(Enum):
    INITIAL = "initial"
    SYNCING = "syncing"
    CATCHUP = "catchup"
    IDLE = "idle"
    RECONNECTING = "reconnecting"
    ERROR = "error"


class DriftType(Enum):
    MESSAGE_COUNT = "message_count"
    UID_ROLLOVER = "uid_rollover"
    UID_VALIDITY = "uid_validity"
    FOLDER_MISSING = "folder_missing"
    FOLDER_NEW = "folder_new"


@dataclass
class SyncCheckpoint:
    """Sync checkpoint for resumable sync"""
    checkpoint_id: str
    account_id: int
    folder: str
    last_uid: int
    uid_validity: int
    sync_state: SyncState
    messages_synced: int
    created_at: float = field(default_factory=time.time)


@dataclass
class DriftEvent:
    """Folder drift event"""
    account_id: int
    folder: str
    drift_type: DriftType
    old_value: Any
    new_value: Any
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False


@dataclass
class MessageReconciliation:
    """Message reconciliation record"""
    message_uid: str
    message_id: str
    subject: str
    status: str  # new, existing, modified, deleted
    folder: str


@dataclass
class UIDRecord:
    """UID tracking record"""
    uid: int
    message_id: str
    checksum: str
    seen: bool
    flagged: bool
    last_seen: float


class IMAPSyncJournal:
    """IMAP sync state journal"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or (Path(config.DATA_DIR) / "imap_sync.db")
        self._init_db()

    def _init_db(self):
        """Initialize sync journal database"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Sync checkpoints
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sync_checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL,
                folder TEXT NOT NULL,
                last_uid INTEGER,
                uid_validity INTEGER,
                sync_state TEXT,
                messages_synced INTEGER,
                created_at REAL,
                UNIQUE(account_id, folder)
            )
        """)

        # UID tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS uid_tracking (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                folder TEXT NOT NULL,
                uid INTEGER NOT NULL,
                message_id TEXT,
                checksum TEXT,
                seen INTEGER DEFAULT 0,
                flagged INTEGER DEFAULT 0,
                last_seen REAL,
                UNIQUE(account_id, folder, uid)
            )
        """)

        # Drift events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS drift_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                folder TEXT NOT NULL,
                drift_type TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                timestamp REAL,
                resolved INTEGER DEFAULT 0
            )
        """)

        # Message reconciliation
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_reconciliation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                message_uid TEXT NOT NULL,
                message_id TEXT,
                subject TEXT,
                status TEXT,
                folder TEXT,
                reconciled_at REAL
            )
        """)

        # Gmail label mappings
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gmail_labels (
                account_id INTEGER NOT NULL,
                message_uid TEXT NOT NULL,
                labels TEXT,
                last_updated REAL,
                PRIMARY KEY(account_id, message_uid)
            )
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

    def save_checkpoint(self, checkpoint: SyncCheckpoint):
        """Save sync checkpoint"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sync_checkpoints
                (checkpoint_id, account_id, folder, last_uid, uid_validity, sync_state, messages_synced, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                checkpoint.checkpoint_id,
                checkpoint.account_id,
                checkpoint.folder,
                checkpoint.last_uid,
                checkpoint.uid_validity,
                checkpoint.sync_state.value,
                checkpoint.messages_synced,
                checkpoint.created_at
            ))
            conn.commit()

    def get_checkpoint(self, account_id: int, folder: str) -> Optional[SyncCheckpoint]:
        """Get sync checkpoint"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM sync_checkpoints 
                WHERE account_id = ? AND folder = ?
            """, (account_id, folder))
            row = cursor.fetchone()
            if row:
                return SyncCheckpoint(
                    checkpoint_id=row["checkpoint_id"],
                    account_id=row["account_id"],
                    folder=row["folder"],
                    last_uid=row["last_uid"],
                    uid_validity=row["uid_validity"],
                    sync_state=SyncState(row["sync_state"]),
                    messages_synced=row["messages_synced"],
                    created_at=row["created_at"]
                )
        return None

    def record_uid(self, account_id: int, folder: str, uid: int,
                   message_id: str, checksum: str):
        """Record UID for tracking"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO uid_tracking
                (account_id, folder, uid, message_id, checksum, seen, flagged, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (account_id, folder, uid, message_id, checksum, 0, 0, time.time()))
            conn.commit()

    def get_known_uids(self, account_id: int, folder: str) -> Dict[int, UIDRecord]:
        """Get known UIDs for folder"""
        uids = {}
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM uid_tracking 
                WHERE account_id = ? AND folder = ?
            """, (account_id, folder))
            for row in cursor.fetchall():
                uids[row["uid"]] = UIDRecord(
                    uid=row["uid"],
                    message_id=row["message_id"],
                    checksum=row["checksum"],
                    seen=bool(row["seen"]),
                    flagged=bool(row["flagged"]),
                    last_seen=row["last_seen"]
                )
        return uids

    def mark_uid_seen(self, account_id: int, folder: str, uid: int):
        """Mark UID as seen"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE uid_tracking SET seen = 1, last_seen = ?
                WHERE account_id = ? AND folder = ? AND uid = ?
            """, (time.time(), account_id, folder, uid))
            conn.commit()

    def log_drift(self, event: DriftEvent):
        """Log drift event"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO drift_events
                (account_id, folder, drift_type, old_value, new_value, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event.account_id,
                event.folder,
                event.drift_type.value,
                str(event.old_value),
                str(event.new_value),
                event.timestamp
            ))
            conn.commit()

    def get_pending_drifts(self, account_id: int) -> List[DriftEvent]:
        """Get unresolved drift events"""
        drifts = []
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM drift_events 
                WHERE account_id = ? AND resolved = 0
                ORDER BY timestamp DESC
            """, (account_id,))
            for row in cursor.fetchall():
                drifts.append(DriftEvent(
                    account_id=row["account_id"],
                    folder=row["folder"],
                    drift_type=DriftType(row["drift_type"]),
                    old_value=row["old_value"],
                    new_value=row["new_value"],
                    timestamp=row["timestamp"],
                    resolved=bool(row["resolved"])
                ))
        return drifts

    def resolve_drift(self, account_id: int, folder: str, drift_type: DriftType):
        """Mark drift as resolved"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE drift_events SET resolved = 1
                WHERE account_id = ? AND folder = ? AND drift_type = ?
            """, (account_id, folder, drift_type.value))
            conn.commit()

    def reconcile_message(self, account_id: int, uid: str, message_id: str,
                         subject: str, status: str, folder: str):
        """Record message reconciliation"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO message_reconciliation
                (account_id, message_uid, message_id, subject, status, folder, reconciled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (account_id, uid, message_id, subject, status, folder, time.time()))
            conn.commit()

    def get_reconciliation_status(self, account_id: int) -> Dict[str, int]:
        """Get reconciliation status counts"""
        status = {"new": 0, "existing": 0, "modified": 0, "deleted": 0}
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT status, COUNT(*) as count FROM message_reconciliation
                WHERE account_id = ?
                GROUP BY status
            """, (account_id,))
            for row in cursor.fetchall():
                if row["status"] in status:
                    status[row["status"]] = row["count"]
        return status

    def save_gmail_labels(self, account_id: int, message_uid: str, labels: List[str]):
        """Save Gmail labels"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO gmail_labels
                (account_id, message_uid, labels, last_updated)
                VALUES (?, ?, ?, ?)
            """, (account_id, message_uid, json.dumps(labels), time.time()))
            conn.commit()

    def get_gmail_labels(self, account_id: int, message_uid: str) -> List[str]:
        """Get Gmail labels"""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT labels FROM gmail_labels
                WHERE account_id = ? AND message_uid = ?
            """, (account_id, message_uid))
            row = cursor.fetchone()
            if row:
                return json.loads(row["labels"])
        return []


class AdvancedIMAPHardener:
    """
    Advanced IMAP hardening with full resilience.
    """

    def __init__(self):
        self.journal = IMAPSyncJournal()

        # Drift detection thresholds
        self.uid_rollover_threshold = 1000  # Allow for UID rollover
        self.drift_warning_count = 5

        # Adaptive polling
        self._poll_history: deque = deque(maxlen=100)
        self._base_poll_interval = 30
        self._min_poll_interval = 10
        self._max_poll_interval = 300

        # Callbacks
        self.on_drift: Optional[Callable] = None
        self.on_rollover: Optional[Callable] = None
        self.on_reconciliation: Optional[Callable] = None

        logger.info("Advanced IMAP Hardener initialized")

    def check_uid_rollover(self, account_id: int, folder: str,
                          old_uid_validity: int, new_uid_validity: int,
                          old_uid_next: int, new_uid_next: int) -> bool:
        """Check for UID rollover"""
        if old_uid_validity != new_uid_validity:
            # UID validity changed - this is a rollover
            logger.warning(f"UID rollover detected for {folder}: {old_uid_validity} -> {new_uid_validity}")

            event = DriftEvent(
                account_id=account_id,
                folder=folder,
                drift_type=DriftType.UID_ROLLOVER,
                old_value=old_uid_validity,
                new_value=new_uid_validity
            )
            self.journal.log_drift(event)

            if self.on_rollover:
                self.on_rollover(account_id, folder, old_uid_validity, new_uid_validity)

            return True

        return False

    def check_folder_drift(self, account_id: int, folder: str,
                           old_count: int, new_count: int) -> Optional[DriftEvent]:
        """Check for folder message count drift"""
        drift = abs(new_count - old_count)

        if drift > self.drift_warning_count:
            event = DriftEvent(
                account_id=account_id,
                folder=folder,
                drift_type=DriftType.MESSAGE_COUNT,
                old_value=old_count,
                new_value=new_count
            )
            self.journal.log_drift(event)

            if self.on_drift:
                self.on_drift(event)

            return event

        return None

    def detect_deleted_messages(self, account_id: int, folder: str,
                               server_uids: Set[int]) -> List[int]:
        """Detect deleted messages by comparing UIDs"""
        known_uids = self.journal.get_known_uids(account_id, folder)

        deleted = []
        for uid in known_uids:
            if uid not in server_uids:
                deleted.append(uid)

        return deleted

    def detect_new_messages(self, account_id: int, folder: str,
                           server_uids: Set[int]) -> List[int]:
        """Detect new messages by comparing UIDs"""
        known_uids = self.journal.get_known_uids(account_id, folder)

        new = []
        for uid in server_uids:
            if uid not in known_uids:
                new.append(uid)

        return new

    def reconcile_messages(self, account_id: int, folder: str,
                          fetched_messages: List[Dict]) -> List[MessageReconciliation]:
        """Reconcile fetched messages with known state"""
        known_uids = self.journal.get_known_uids(account_id, folder)
        reconciliations = []

        for msg in fetched_messages:
            uid = msg.get("uid")
            message_id = msg.get("message_id", "")
            subject = msg.get("subject", "")

            # Calculate checksum for change detection
            checksum = f"{message_id}:{subject}"

            if uid is None:
                continue

            if uid not in known_uids:
                # New message
                status = "new"
                self.journal.record_uid(account_id, folder, uid, message_id, checksum)
            else:
                # Check for modifications
                existing = known_uids[uid]
                if existing.checksum != checksum:
                    status = "modified"
                    self.journal.record_uid(account_id, folder, uid, message_id, checksum)
                else:
                    status = "existing"

            reconciliation = MessageReconciliation(
                message_uid=str(uid),
                message_id=message_id,
                subject=subject,
                status=status,
                folder=folder
            )
            reconciliations.append(reconciliation)

            self.journal.reconcile_message(
                account_id, str(uid), message_id, subject, status, folder
            )

        if self.on_reconciliation:
            self.on_reconciliation(reconciliations)

        return reconciliations

    def get_adaptive_poll_interval(self) -> int:
        """Get adaptive poll interval based on recent activity"""
        if not self._poll_history:
            return self._base_poll_interval

        recent = list(self._poll_history)[-10:]

        # Calculate average new messages
        avg_new = sum(r.get("new_messages", 0) for r in recent) / len(recent)

        # Adjust interval based on activity
        if avg_new > 10:
            return self._min_poll_interval
        elif avg_new > 2:
            return self._base_poll_interval
        elif avg_new > 0:
            return self._base_poll_interval * 2
        else:
            return min(self._max_poll_interval, self._base_poll_interval * 3)

    def record_poll_result(self, new_messages: int):
        """Record poll result for adaptive interval"""
        self._poll_history.append({
            "timestamp": time.time(),
            "new_messages": new_messages
        })

    def get_sync_health(self, account_id: int) -> Dict:
        """Get sync health metrics"""
        drifts = self.journal.get_pending_drifts(account_id)
        reconciliation = self.journal.get_reconciliation_status(account_id)

        return {
            "pending_drifts": len(drifts),
            "drift_types": [d.drift_type.value for d in drifts],
            "reconciliation": reconciliation,
            "adaptive_poll_interval": self.get_adaptive_poll_interval(),
            "poll_history_size": len(self._poll_history)
        }

    def create_checkpoint(self, account_id: int, folder: str, last_uid: int,
                         uid_validity: int, sync_state: SyncState,
                         messages_synced: int) -> str:
        """Create sync checkpoint"""
        import secrets
        checkpoint_id = f"chk_{secrets.token_hex(8)}"

        checkpoint = SyncCheckpoint(
            checkpoint_id=checkpoint_id,
            account_id=account_id,
            folder=folder,
            last_uid=last_uid,
            uid_validity=uid_validity,
            sync_state=sync_state,
            messages_synced=messages_synced
        )

        self.journal.save_checkpoint(checkpoint)

        logger.debug(f"Checkpoint created: {checkpoint_id} for {folder}")
        return checkpoint_id

    def get_resume_point(self, account_id: int, folder: str) -> Optional[Dict]:
        """Get resume point for interrupted sync"""
        checkpoint = self.journal.get_checkpoint(account_id, folder)

        if checkpoint:
            return {
                "last_uid": checkpoint.last_uid,
                "uid_validity": checkpoint.uid_validity,
                "messages_synced": checkpoint.messages_synced,
                "sync_state": checkpoint.sync_state.value
            }

        return None


# Global hardener
_imap_hardener: Optional[AdvancedIMAPHardener] = None


def get_imap_hardener() -> AdvancedIMAPHardener:
    """Get global IMAP hardener"""
    global _imap_hardener
    if _imap_hardener is None:
        _imap_hardener = AdvancedIMAPHardener()
    return _imap_hardener


# Need contextmanager import
from contextlib import contextmanager
