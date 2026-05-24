"""
Advanced IMAP Engine - Enterprise Grade Hardening
===================================================

Comprehensive IMAP hardening with:
- UID Management (rollover, validity, mapping, history)
- Folder Drift Detection (state hash, alerts, auto-reconciliation)
- Message Reconciliation (deduplication, conflict resolution)
- Gmail Label Normalization
- Sync Checkpoint System
- Resumable Sync
- Connection Health (heartbeat, polling, IDLE)
"""

import hashlib
import json
import logging
import random
import sqlite3
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("imap.advanced")


class DriftSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MergeStrategy(Enum):
    SERVER_WINS = "server_wins"
    CLIENT_WINS = "client_wins"
    NEWEST_WINS = "newest_wins"
    MANUAL = "manual"


class PollInterval(Enum):
    FAST = 60
    NORMAL = 300
    SLOW = 900
    IDLE = 3600


@dataclass
class UIDRecord:
    uid: int
    message_id: str
    checksum: str
    folder: str
    seen: bool = False
    flagged: bool = False
    deleted: bool = False
    last_seen: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)


@dataclass
class FolderState:
    folder: str
    message_count: int
    uid_validity: int
    uid_next: int
    state_hash: str = ""
    last_check: float = field(default_factory=time.time)
    flags: Dict[str, bool] = field(default_factory=dict)


@dataclass
class DriftAlert:
    account_id: int
    folder: str
    drift_type: str
    severity: DriftSeverity
    old_value: Any
    new_value: Any
    timestamp: float = field(default_factory=time.time)
    auto_reconciled: bool = False


@dataclass
class MessageConflict:
    message_id: str
    uid: int
    folder: str
    server_checksum: str
    client_checksum: str
    server_modified: float
    client_modified: float
    merge_strategy: MergeStrategy = MergeStrategy.NEWEST_WINS


@dataclass
class GmailLabel:
    message_uid: str
    labels: List[str]
    folder_path: str
    has_children: bool = False
    has_no_children: bool = True


@dataclass
class SyncCheckpoint:
    checkpoint_id: str
    account_id: int
    folder: str
    uidnext: int
    uidvalidity: int
    last_sync: float
    checksum: str
    messages_synced: int
    batch_number: int
    completed: bool = False


@dataclass
class BatchProgress:
    batch_id: str
    account_id: int
    folder: str
    start_uid: int
    end_uid: int
    processed: int
    total: int
    success: bool = False
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None


@dataclass
class ConnectionHealth:
    connected: bool = False
    last_noop: float = 0
    last_poll: float = 0
    poll_interval: int = 300
    idle_enabled: bool = False
    reconnect_count: int = 0
    last_error: Optional[str] = None


class AdvancedIMAPEngine:
    """
    Advanced IMAP Engine with comprehensive hardening.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or self._get_default_db_path()
        self._init_database()

        self.uid_rollover_threshold = 1000
        self._deleted_uids: Dict[int, Set[int]] = {}
        self._folder_states: Dict[int, Dict[str, FolderState]] = {}
        self._connection_health: Dict[int, ConnectionHealth] = {}
        self._poll_history: deque = deque(maxlen=100)
        self._backoff_jitter = 0.5

        self.on_drift_detected: Optional[Callable[[DriftAlert], None]] = None
        self.on_uid_rollover: Optional[Callable[[int, str, int, int], None]] = None
        self.on_conflict: Optional[Callable[[MessageConflict], None]] = None
        self.on_health_change: Optional[Callable[[ConnectionHealth], None]] = None

        logger.info("Advanced IMAP Engine initialized")

    def _get_default_db_path(self) -> str:
        from backend import config
        return str(Path(config.DATA_DIR) / "imap_advanced.db")

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_database(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()

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
                    deleted INTEGER DEFAULT 0,
                    last_seen REAL,
                    created_at REAL,
                    UNIQUE(account_id, folder, uid)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS uid_mapping (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    message_id TEXT NOT NULL,
                    source_folder TEXT,
                    target_folder TEXT,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS uid_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    folder TEXT NOT NULL,
                    uid INTEGER NOT NULL,
                    message_id TEXT,
                    action TEXT,
                    timestamp REAL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS folder_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    folder TEXT NOT NULL,
                    message_count INTEGER,
                    uid_validity INTEGER,
                    uid_next INTEGER,
                    state_hash TEXT,
                    last_check REAL,
                    flags TEXT,
                    UNIQUE(account_id, folder)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS drift_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    folder TEXT NOT NULL,
                    drift_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    timestamp REAL,
                    auto_reconciled INTEGER DEFAULT 0
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS message_conflicts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    message_id TEXT NOT NULL,
                    uid INTEGER,
                    folder TEXT,
                    server_checksum TEXT,
                    client_checksum TEXT,
                    server_modified REAL,
                    client_modified REAL,
                    merge_strategy TEXT,
                    resolved INTEGER DEFAULT 0,
                    resolved_at REAL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gmail_labels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    message_uid TEXT NOT NULL,
                    labels TEXT,
                    folder_path TEXT,
                    has_children INTEGER DEFAULT 0,
                    has_no_children INTEGER DEFAULT 1,
                    last_updated REAL,
                    UNIQUE(account_id, message_uid)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    folder TEXT NOT NULL,
                    uidnext INTEGER,
                    uidvalidity INTEGER,
                    last_sync REAL,
                    checksum TEXT,
                    messages_synced INTEGER,
                    batch_number INTEGER,
                    completed INTEGER DEFAULT 0,
                    UNIQUE(account_id, folder, batch_number)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS batch_progress (
                    batch_id TEXT PRIMARY KEY,
                    account_id INTEGER NOT NULL,
                    folder TEXT NOT NULL,
                    start_uid INTEGER,
                    end_uid INTEGER,
                    processed INTEGER,
                    total INTEGER,
                    success INTEGER DEFAULT 0,
                    started_at REAL,
                    completed_at REAL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS connection_health (
                    account_id INTEGER PRIMARY KEY,
                    connected INTEGER DEFAULT 0,
                    last_noop REAL,
                    last_poll REAL,
                    poll_interval INTEGER DEFAULT 300,
                    idle_enabled INTEGER DEFAULT 0,
                    reconnect_count INTEGER DEFAULT 0,
                    last_error TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deleted_uid_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    folder TEXT NOT NULL,
                    uid INTEGER NOT NULL,
                    deleted_at REAL,
                    UNIQUE(account_id, folder, uid)
                )
            """)

            conn.commit()

    def _compute_state_hash(self, message_count: int, uid_validity: int, uid_next: int, flags: Dict) -> str:
        data = f"{message_count}:{uid_validity}:{uid_next}:{json.dumps(flags, sort_keys=True)}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    def _compute_message_checksum(self, message_id: str, subject: str, body: str = "") -> str:
        data = f"{message_id}:{subject}:{body}"
        return hashlib.sha256(data.encode()).hexdigest()

    def _add_jitter(self, base_delay: float) -> float:
        jitter = base_delay * self._backoff_jitter * random.uniform(-1, 1)
        return max(0, base_delay + jitter)

    def track_uid(self, account_id: int, folder: str, uid: int, message_id: str,
                  checksum: str, seen: bool = False, flagged: bool = False):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO uid_tracking
                (account_id, folder, uid, message_id, checksum, seen, flagged, deleted, last_seen, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """, (account_id, folder, uid, message_id, checksum, seen, flagged, time.time(), time.time()))
            conn.commit()

    def get_known_uids(self, account_id: int, folder: str) -> Dict[int, UIDRecord]:
        uids = {}
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM uid_tracking WHERE account_id = ? AND folder = ? AND deleted = 0
            """, (account_id, folder))
            for row in cursor.fetchall():
                uids[row["uid"]] = UIDRecord(
                    uid=row["uid"],
                    message_id=row["message_id"],
                    checksum=row["checksum"],
                    folder=row["folder"],
                    seen=bool(row["seen"]),
                    flagged=bool(row["flagged"]),
                    deleted=bool(row["deleted"]),
                    last_seen=row["last_seen"],
                    created_at=row["created_at"]
                )
        return uids

    def mark_uid_deleted(self, account_id: int, folder: str, uid: int):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE uid_tracking SET deleted = 1, last_seen = ? WHERE account_id = ? AND folder = ? AND uid = ?
            """, (time.time(), account_id, folder, uid))
            cursor.execute("""
                INSERT OR REPLACE INTO deleted_uid_history (account_id, folder, uid, deleted_at)
                VALUES (?, ?, ?, ?)
            """, (account_id, folder, uid, time.time()))
            conn.commit()

    def get_deleted_uids(self, account_id: int, folder: str) -> Set[int]:
        deleted = set()
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT uid FROM deleted_uid_history WHERE account_id = ? AND folder = ?
            """, (account_id, folder))
            for row in cursor.fetchall():
                deleted.add(row["uid"])
        return deleted

    def check_uid_rollover(self, account_id: int, folder: str,
                          old_uid_validity: int, new_uid_validity: int,
                          old_uid_next: int, new_uid_next: int) -> bool:
        if old_uid_validity != new_uid_validity:
            logger.warning(f"UID rollover detected for {folder}: {old_uid_validity} -> {new_uid_validity}")

            self._log_drift(account_id, folder, "uid_rollover", DriftSeverity.CRITICAL,
                           old_uid_validity, new_uid_validity)

            self._record_uid_history(account_id, folder, 0, "", "rollover")

            if self.on_uid_rollover:
                self.on_uid_rollover(account_id, folder, old_uid_validity, new_uid_validity)

            return True

        if old_uid_next > new_uid_next and new_uid_next < self.uid_rollover_threshold:
            logger.warning(f"UIDNEXT rolled back for {folder}: {old_uid_next} -> {new_uid_next}")
            self._log_drift(account_id, folder, "uidnext_rollback", DriftSeverity.HIGH,
                           old_uid_next, new_uid_next)

        return False

    def validate_uidvalidity_on_reconnect(self, account_id: int, folder: str,
                                         stored_validity: int, server_validity: int) -> bool:
        if stored_validity != 0 and stored_validity != server_validity:
            logger.error(f"UIDVALIDITY mismatch on reconnect for {folder}: stored={stored_validity}, server={server_validity}")
            self._log_drift(account_id, folder, "uidvalidity_mismatch", DriftSeverity.CRITICAL,
                           stored_validity, server_validity)
            return False
        return True

    def record_uid_mapping(self, account_id: int, message_id: str, source_folder: str, target_folder: str):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO uid_mapping (account_id, message_id, source_folder, target_folder)
                VALUES (?, ?, ?, ?)
            """, (account_id, message_id, source_folder, target_folder))
            conn.commit()

    def get_uid_mapping(self, account_id: int, message_id: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM uid_mapping WHERE account_id = ? AND message_id = ?
            """, (account_id, message_id))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def _record_uid_history(self, account_id: int, folder: str, uid: int, message_id: str, action: str):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO uid_history (account_id, folder, uid, message_id, action, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (account_id, folder, uid, message_id, action, time.time()))
            conn.commit()

    def get_uid_history(self, account_id: int, folder: str, limit: int = 100) -> List[Dict]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM uid_history WHERE account_id = ? AND folder = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (account_id, folder, limit))
            return [dict(row) for row in cursor.fetchall()]

    def update_folder_state(self, account_id: int, folder: str, message_count: int,
                           uid_validity: int, uid_next: int, flags: Optional[Dict] = None):
        flags = flags or {}
        state_hash = self._compute_state_hash(message_count, uid_validity, uid_next, flags)

        old_state = self.get_folder_state(account_id, folder)

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO folder_states
                (account_id, folder, message_count, uid_validity, uid_next, state_hash, last_check, flags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (account_id, folder, message_count, uid_validity, uid_next, state_hash, time.time(), json.dumps(flags)))
            conn.commit()

        if old_state:
            if old_state.message_count != message_count:
                drift = abs(message_count - old_state.message_count)
                severity = DriftSeverity.CRITICAL if drift > 50 else DriftSeverity.HIGH if drift > 20 else DriftSeverity.MEDIUM
                self._log_drift(account_id, folder, "message_count", severity,
                               old_state.message_count, message_count)

            if old_state.state_hash != state_hash:
                self._log_drift(account_id, folder, "state_hash", DriftSeverity.LOW,
                               old_state.state_hash, state_hash)

    def get_folder_state(self, account_id: int, folder: str) -> Optional[FolderState]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM folder_states WHERE account_id = ? AND folder = ?
            """, (account_id, folder))
            row = cursor.fetchone()
            if row:
                return FolderState(
                    folder=row["folder"],
                    message_count=row["message_count"],
                    uid_validity=row["uid_validity"],
                    uid_next=row["uid_next"],
                    state_hash=row["state_hash"],
                    last_check=row["last_check"],
                    flags=json.loads(row["flags"] or "{}")
                )
        return None

    def detect_folder_drift(self, account_id: int, folder: str,
                           server_count: int, server_uid_validity: int, server_uid_next: int) -> List[DriftAlert]:
        alerts = []
        local_state = self.get_folder_state(account_id, folder)

        if not local_state:
            return alerts

        if local_state.message_count != server_count:
            drift = abs(server_count - local_state.message_count)
            severity = DriftSeverity.CRITICAL if drift > 50 else DriftSeverity.HIGH if drift > 20 else DriftSeverity.MEDIUM
            alerts.append(DriftAlert(
                account_id=account_id,
                folder=folder,
                drift_type="message_count",
                severity=severity,
                old_value=local_state.message_count,
                new_value=server_count
            ))

        if local_state.uid_validity != server_uid_validity:
            alerts.append(DriftAlert(
                account_id=account_id,
                folder=folder,
                drift_type="uid_validity",
                severity=DriftSeverity.CRITICAL,
                old_value=local_state.uid_validity,
                new_value=server_uid_validity
            ))

        return alerts

    def reconcile_folders(self, account_id: int, server_folders: List[str]) -> List[DriftAlert]:
        alerts = []
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT folder FROM folder_states WHERE account_id = ?", (account_id,))
            local_folders = {row["folder"] for row in cursor.fetchall()}

        server_set = set(server_folders)
        local_set = local_folders

        for folder in server_set - local_set:
            alerts.append(DriftAlert(
                account_id=account_id,
                folder=folder,
                drift_type="folder_new",
                severity=DriftSeverity.MEDIUM,
                old_value=None,
                new_value=folder
            ))

        for folder in local_set - server_set:
            alerts.append(DriftAlert(
                account_id=account_id,
                folder=folder,
                drift_type="folder_missing",
                severity=DriftSeverity.HIGH,
                old_value=folder,
                new_value=None
            ))

        return alerts

    def _log_drift(self, account_id: int, folder: str, drift_type: str,
                  severity: DriftSeverity, old_value: Any, new_value: Any):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO drift_alerts (account_id, folder, drift_type, severity, old_value, new_value, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (account_id, folder, drift_type, severity.value, str(old_value), str(new_value), time.time()))
            conn.commit()

        alert = DriftAlert(account_id=account_id, folder=folder, drift_type=drift_type,
                         severity=severity, old_value=old_value, new_value=new_value)

        if self.on_drift_detected:
            self.on_drift_detected(alert)

    def get_pending_drifts(self, account_id: int) -> List[DriftAlert]:
        alerts = []
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM drift_alerts WHERE account_id = ? ORDER BY timestamp DESC LIMIT 50
            """, (account_id,))
            for row in cursor.fetchall():
                alerts.append(DriftAlert(
                    account_id=row["account_id"],
                    folder=row["folder"],
                    drift_type=row["drift_type"],
                    severity=DriftSeverity(row["severity"]),
                    old_value=row["old_value"],
                    new_value=row["new_value"],
                    timestamp=row["timestamp"],
                    auto_reconciled=bool(row["auto_reconciled"])
                ))
        return alerts

    def detect_duplicates_by_message_id(self, account_id: int, message_id: str,
                                       folder: str) -> List[UIDRecord]:
        duplicates = []
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM uid_tracking WHERE account_id = ? AND message_id = ? AND deleted = 0
            """, (account_id, message_id))
            for row in cursor.fetchall():
                duplicates.append(UIDRecord(
                    uid=row["uid"],
                    message_id=row["message_id"],
                    checksum=row["checksum"],
                    folder=row["folder"],
                    seen=bool(row["seen"]),
                    flagged=bool(row["flagged"]),
                    deleted=bool(row["deleted"]),
                    last_seen=row["last_seen"],
                    created_at=row["created_at"]
                ))
        return duplicates

    def detect_reappearing_deleted(self, account_id: int, folder: str,
                                  server_uids: Set[int]) -> List[int]:
        deleted_uids = self.get_deleted_uids(account_id, folder)
        reappearing = list(deleted_uids & server_uids)
        if reappearing:
            logger.warning(f"Reappearing deleted emails detected in {folder}: {len(reappearing)} emails")
        return reappearing

    def reconcile_messages(self, account_id: int, folder: str,
                          fetched_messages: List[Dict]) -> Tuple[List[UIDRecord], List[MessageConflict]]:
        known_uids = self.get_known_uids(account_id, folder)
        new_records = []
        conflicts = []

        for msg in fetched_messages:
            uid = msg.get("uid")
            message_id = msg.get("message_id", "")
            subject = msg.get("subject", "")
            body = msg.get("body", "")
            server_checksum = self._compute_message_checksum(message_id, subject, body)

            if uid is None:
                continue

            if uid not in known_uids:
                self.track_uid(account_id, folder, uid, message_id, server_checksum)
                new_records.append(UIDRecord(uid=uid, message_id=message_id, checksum=server_checksum, folder=folder))
            else:
                existing = known_uids[uid]
                if existing.checksum != server_checksum:
                    conflict = MessageConflict(
                        message_id=message_id,
                        uid=uid,
                        folder=folder,
                        server_checksum=server_checksum,
                        client_checksum=existing.checksum,
                        server_modified=time.time(),
                        client_modified=existing.last_seen,
                        merge_strategy=MergeStrategy.NEWEST_WINS
                    )
                    conflicts.append(conflict)
                    self._log_conflict(account_id, conflict)

                    self.track_uid(account_id, folder, uid, message_id, server_checksum,
                                  seen=existing.seen, flagged=existing.flagged)

        return new_records, conflicts

    def _log_conflict(self, account_id: int, conflict: MessageConflict):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO message_conflicts
                (account_id, message_id, uid, folder, server_checksum, client_checksum,
                 server_modified, client_modified, merge_strategy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (account_id, conflict.message_id, conflict.uid, conflict.folder,
                  conflict.server_checksum, conflict.client_checksum,
                  conflict.server_modified, conflict.client_modified, conflict.merge_strategy.value))
            conn.commit()

        if self.on_conflict:
            self.on_conflict(conflict)

    def resolve_conflict(self, account_id: int, message_id: str, strategy: MergeStrategy) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE message_conflicts SET resolved = 1, resolved_at = ?, merge_strategy = ?
                WHERE account_id = ? AND message_id = ? AND resolved = 0
            """, (time.time(), strategy.value, account_id, message_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_unresolved_conflicts(self, account_id: int) -> List[MessageConflict]:
        conflicts = []
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM message_conflicts WHERE account_id = ? AND resolved = 0
            """, (account_id,))
            for row in cursor.fetchall():
                conflicts.append(MessageConflict(
                    message_id=row["message_id"],
                    uid=row["uid"],
                    folder=row["folder"],
                    server_checksum=row["server_checksum"],
                    client_checksum=row["client_checksum"],
                    server_modified=row["server_modified"],
                    client_modified=row["client_modified"],
                    merge_strategy=MergeStrategy(row["merge_strategy"])
                ))
        return conflicts

    def save_gmail_label(self, account_id: int, message_uid: str, labels: List[str],
                        folder_path: str, has_children: bool = False, has_no_children: bool = True):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO gmail_labels
                (account_id, message_uid, labels, folder_path, has_children, has_no_children, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (account_id, message_uid, json.dumps(labels), folder_path,
                  int(has_children), int(has_no_children), time.time()))
            conn.commit()

    def get_gmail_labels(self, account_id: int, message_uid: str) -> Optional[GmailLabel]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM gmail_labels WHERE account_id = ? AND message_uid = ?
            """, (account_id, message_uid))
            row = cursor.fetchone()
            if row:
                return GmailLabel(
                    message_uid=row["message_uid"],
                    labels=json.loads(row["labels"]),
                    folder_path=row["folder_path"],
                    has_children=bool(row["has_children"]),
                    has_no_children=bool(row["has_no_children"])
                )
        return None

    def detect_orphan_labels(self, account_id: int) -> List[str]:
        orphans = []
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT folder_path FROM gmail_labels WHERE account_id = ? AND has_no_children = 1
            """, (account_id,))
            labels = {row["folder_path"] for row in cursor.fetchall()}

            cursor.execute("SELECT DISTINCT folder FROM folder_states WHERE account_id = ?", (account_id,))
            folders = {row["folder"] for row in cursor.fetchall()}

            orphans = list(labels - folders)
        return orphans

    def map_gmail_label_to_folder(self, label: str) -> str:
        label_map = {
            "INBOX": "INBOX",
            "[Gmail]/All Mail": "All Mail",
            "[Gmail]/Sent Mail": "Sent",
            "[Gmail]/Drafts": "Drafts",
            "[Gmail]/Spam": "Spam",
            "[Gmail]/Trash": "Trash",
            "Starred": "Starred",
            "Important": "Important",
        }
        return label_map.get(label, label.replace(" ", "_"))

    def create_checkpoint(self, account_id: int, folder: str, uidnext: int, uidvalidity: int,
                         messages_synced: int, batch_number: int, checksum: str = "") -> str:
        import secrets
        checkpoint_id = f"chk_{secrets.token_hex(8)}"

        checkpoint = SyncCheckpoint(
            checkpoint_id=checkpoint_id,
            account_id=account_id,
            folder=folder,
            uidnext=uidnext,
            uidvalidity=uidvalidity,
            last_sync=time.time(),
            checksum=checksum,
            messages_synced=messages_synced,
            batch_number=batch_number,
            completed=False
        )

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sync_checkpoints
                (checkpoint_id, account_id, folder, uidnext, uidvalidity, last_sync, checksum, messages_synced, batch_number, completed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (checkpoint.checkpoint_id, checkpoint.account_id, checkpoint.folder,
                  checkpoint.uidnext, checkpoint.uidvalidity, checkpoint.last_sync,
                  checkpoint.checksum, checkpoint.messages_synced, checkpoint.batch_number,
                  int(checkpoint.completed)))
            conn.commit()

        logger.debug(f"Checkpoint created: {checkpoint_id} for {folder} batch {batch_number}")
        return checkpoint_id

    def get_valid_checkpoint(self, account_id: int, folder: str) -> Optional[SyncCheckpoint]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM sync_checkpoints
                WHERE account_id = ? AND folder = ? AND completed = 0
                ORDER BY batch_number DESC LIMIT 1
            """, (account_id, folder))
            row = cursor.fetchone()
            if row:
                return SyncCheckpoint(
                    checkpoint_id=row["checkpoint_id"],
                    account_id=row["account_id"],
                    folder=row["folder"],
                    uidnext=row["uidnext"],
                    uidvalidity=row["uidvalidity"],
                    last_sync=row["last_sync"],
                    checksum=row["checksum"],
                    messages_synced=row["messages_synced"],
                    batch_number=row["batch_number"],
                    completed=bool(row["completed"])
                )
        return None

    def validate_checkpoint(self, account_id: int, folder: str, server_uidvalidity: int) -> bool:
        checkpoint = self.get_valid_checkpoint(account_id, folder)
        if not checkpoint:
            return True
        return checkpoint.uidvalidity == server_uidvalidity

    def mark_checkpoint_completed(self, checkpoint_id: str):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sync_checkpoints SET completed = 1 WHERE checkpoint_id = ?
            """, (checkpoint_id,))
            conn.commit()

    def save_batch_progress(self, batch: BatchProgress):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO batch_progress
                (batch_id, account_id, folder, start_uid, end_uid, processed, total, success, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (batch.batch_id, batch.account_id, batch.folder, batch.start_uid, batch.end_uid,
                  batch.processed, batch.total, int(batch.success), batch.started_at, batch.completed_at))
            conn.commit()

    def get_last_successful_batch(self, account_id: int, folder: str) -> Optional[BatchProgress]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM batch_progress
                WHERE account_id = ? AND folder = ? AND success = 1
                ORDER BY completed_at DESC LIMIT 1
            """, (account_id, folder))
            row = cursor.fetchone()
            if row:
                return BatchProgress(
                    batch_id=row["batch_id"],
                    account_id=row["account_id"],
                    folder=row["folder"],
                    start_uid=row["start_uid"],
                    end_uid=row["end_uid"],
                    processed=row["processed"],
                    total=row["total"],
                    success=bool(row["success"]),
                    started_at=row["started_at"],
                    completed_at=row["completed_at"]
                )
        return None

    def get_resume_point(self, account_id: int, folder: str) -> Optional[Dict]:
        batch = self.get_last_successful_batch(account_id, folder)
        if batch:
            return {
                "start_uid": batch.end_uid + 1,
                "batch_number": batch.processed + 1
            }
        checkpoint = self.get_valid_checkpoint(account_id, folder)
        if checkpoint:
            return {
                "start_uid": checkpoint.uidnext,
                "batch_number": checkpoint.batch_number + 1
            }
        return None

    def run_chunked_sync(self, account_id: int, folder: str,
                         fetch_func: Callable, process_func: Callable,
                         chunk_size: int = 100, max_batches: int = 100) -> int:
        import secrets

        resume_point = self.get_resume_point(account_id, folder)
        batch_number = resume_point["batch_number"] if resume_point else 1
        start_uid = resume_point["start_uid"] if resume_point else 1

        total_synced = 0

        while batch_number <= max_batches:
            batch_id = f"batch_{secrets.token_hex(8)}"
            batch = BatchProgress(
                batch_id=batch_id,
                account_id=account_id,
                folder=folder,
                start_uid=start_uid,
                end_uid=start_uid + chunk_size - 1,
                processed=0,
                total=chunk_size
            )

            try:
                messages = fetch_func(start_uid=batch.start_uid, end_uid=batch.end_uid)
                processed = process_func(messages)

                batch.processed = processed
                batch.total = len(messages)
                batch.success = True
                batch.completed_at = time.time()

                total_synced += processed
                start_uid = batch.end_uid + 1
                batch_number += 1

            except Exception as e:
                logger.error(f"Batch {batch_id} failed: {e}")
                batch.success = False
                batch.completed_at = time.time()
                break
            finally:
                self.save_batch_progress(batch)

        return total_synced

    def update_connection_health(self, account_id: int, health: ConnectionHealth):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO connection_health
                (account_id, connected, last_noop, last_poll, poll_interval, idle_enabled, reconnect_count, last_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (account_id, int(health.connected), health.last_noop, health.last_poll,
                  health.poll_interval, int(health.idle_enabled), health.reconnect_count, health.last_error))
            conn.commit()

        if self.on_health_change:
            self.on_health_change(health)

    def get_connection_health(self, account_id: int) -> Optional[ConnectionHealth]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM connection_health WHERE account_id = ?", (account_id,))
            row = cursor.fetchone()
            if row:
                return ConnectionHealth(
                    connected=bool(row["connected"]),
                    last_noop=row["last_noop"],
                    last_poll=row["last_poll"],
                    poll_interval=row["poll_interval"],
                    idle_enabled=bool(row["idle_enabled"]),
                    reconnect_count=row["reconnect_count"],
                    last_error=row["last_error"]
                )
        return None

    def perform_noop_heartbeat(self, imap_connection, account_id: int) -> bool:
        try:
            imap_connection.noop()
            health = self.get_connection_health(account_id) or ConnectionHealth()
            health.connected = True
            health.last_noop = time.time()
            self.update_connection_health(account_id, health)
            return True
        except Exception as e:
            logger.warning(f"NOOP heartbeat failed: {e}")
            health = self.get_connection_health(account_id) or ConnectionHealth()
            health.connected = False
            health.last_error = str(e)
            self.update_connection_health(account_id, health)
            return False

    def get_adaptive_poll_interval(self, account_id: int) -> PollInterval:
        health = self.get_connection_health(account_id)
        if not health or not health.last_poll:
            return PollInterval.NORMAL

        time_since_poll = time.time() - health.last_poll

        if time_since_poll < 60:
            return PollInterval.FAST
        elif time_since_poll < 300:
            return PollInterval.NORMAL
        elif time_since_poll < 900:
            return PollInterval.SLOW
        else:
            return PollInterval.IDLE

    def record_poll_result(self, account_id: int, new_messages: int):
        self._poll_history.append({
            "account_id": account_id,
            "timestamp": time.time(),
            "new_messages": new_messages
        })

        health = self.get_connection_health(account_id) or ConnectionHealth()
        health.last_poll = time.time()

        if new_messages > 10:
            health.poll_interval = 60
        elif new_messages > 2:
            health.poll_interval = 300
        elif new_messages > 0:
            health.poll_interval = 900
        else:
            health.poll_interval = 3600

        self.update_connection_health(account_id, health)

    def reconnect_with_backoff(self, connect_func: Callable, max_attempts: int = 5) -> bool:
        base_delay = 1.0
        max_delay = 60.0

        for attempt in range(max_attempts):
            try:
                if connect_func():
                    logger.info(f"Reconnected after {attempt + 1} attempts")
                    return True
            except Exception as e:
                logger.warning(f"Reconnect attempt {attempt + 1} failed: {e}")

            delay = min(base_delay * (2 ** attempt), max_delay)
            delay = self._add_jitter(delay)
            time.sleep(delay)

        return False

    def get_sync_health_summary(self, account_id: int) -> Dict:
        drifts = self.get_pending_drifts(account_id)
        conflicts = self.get_unresolved_conflicts(account_id)
        health = self.get_connection_health(account_id)

        return {
            "pending_drifts": len(drifts),
            "drift_types": list(set(d.drift_type for d in drifts)),
            "critical_drifts": len([d for d in drifts if d.severity == DriftSeverity.CRITICAL]),
            "unresolved_conflicts": len(conflicts),
            "connection_health": {
                "connected": health.connected if health else False,
                "poll_interval": health.poll_interval if health else 300,
                "reconnect_count": health.reconnect_count if health else 0
            },
            "adaptive_poll": self.get_adaptive_poll_interval(account_id).value
        }


_global_engine: Optional[AdvancedIMAPEngine] = None


def get_advanced_imap_engine(db_path: Optional[str] = None) -> AdvancedIMAPEngine:
    global _global_engine
    if _global_engine is None:
        _global_engine = AdvancedIMAPEngine(db_path)
    return _global_engine
