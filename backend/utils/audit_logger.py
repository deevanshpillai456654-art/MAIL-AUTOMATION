"""
Audit Logger - Compliance Audit Log
==================================

Compliance audit logging:
- Audit event capture
- Audit log storage
- Audit retention
- Audit search
- Audit export
- Compliance reporting
"""

import hashlib
import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("audit.logger")


class AuditAction(Enum):
    LOGIN = "login"
    LOGOUT = "logout"
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    EXPORT = "export"
    ADMIN = "admin"


class AuditLevel(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class AuditEvent:
    """Audit event"""
    event_id: str
    timestamp: float
    user_id: str
    action: AuditAction
    resource: str
    level: AuditLevel = AuditLevel.MEDIUM
    details: Dict[str, Any] = field(default_factory=dict)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    checksum: Optional[str] = None


class AuditLogger:
    """
    Compliance audit logger.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or "data/audit.db"
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._init_db()
        self._lock = threading.Lock()

        logger.info(f"AuditLogger initialized: {self.db_path}")

    def _init_db(self):
        """Initialize audit database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                timestamp REAL,
                user_id TEXT,
                action TEXT,
                resource TEXT,
                level TEXT,
                details TEXT,
                ip_address TEXT,
                user_agent TEXT,
                checksum TEXT
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_events(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_events(action)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp)")

        conn.commit()
        conn.close()

    def log(
        self,
        user_id: str,
        action: AuditAction,
        resource: str,
        level: AuditLevel = AuditLevel.MEDIUM,
        details: Dict = None,
        ip_address: str = None,
        user_agent: str = None
    ):
        """Log audit event"""
        import secrets

        event_id = f"audit_{secrets.token_hex(16)}"

        data = {
            "event_id": event_id,
            "timestamp": time.time(),
            "user_id": user_id,
            "action": action.value,
            "resource": resource,
            "level": level.value,
            "details": details or {},
            "ip_address": ip_address,
            "user_agent": user_agent
        }

        # Calculate checksum
        checksum = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()

        data["checksum"] = checksum

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO audit_events (
                event_id, timestamp, user_id, action, resource, level,
                details, ip_address, user_agent, checksum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["event_id"],
            data["timestamp"],
            data["user_id"],
            data["action"],
            data["resource"],
            data["level"],
            json.dumps(data["details"]),
            data["ip_address"],
            data["user_agent"],
            data["checksum"]
        ))

        conn.commit()
        conn.close()

        logger.debug(f"Audit: {user_id} {action.value} {resource}")

    def query(
        self,
        user_id: str = None,
        action: AuditAction = None,
        start_time: float = None,
        end_time: float = None,
        limit: int = 100
    ) -> List[AuditEvent]:
        """Query audit events"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM audit_events WHERE 1=1"
        params = []

        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)

        if action:
            query += " AND action = ?"
            params.append(action.value)

        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time)

        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor.execute(query, params)

        events = []
        for row in cursor.fetchall():
            events.append(AuditEvent(
                event_id=row["event_id"],
                timestamp=row["timestamp"],
                user_id=row["user_id"],
                action=AuditAction(row["action"]),
                resource=row["resource"],
                level=AuditLevel(row["level"]),
                details=json.loads(row["details"]),
                ip_address=row["ip_address"],
                user_agent=row["user_agent"],
                checksum=row["checksum"]
            ))

        conn.close()
        return events

    def verify_log(self, event_id: str) -> bool:
        """Verify audit log integrity"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM audit_events WHERE event_id = ?", (event_id,))
        row = cursor.fetchone()

        if not row:
            return False

        # Verify checksum
        stored_checksum = row["checksum"]
        data = {k: row[k] for k in row.keys() if k != "checksum"}
        calculated = hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()

        return stored_checksum == calculated

    def get_stats(self) -> Dict:
        """Get audit stats"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM audit_events")
        total = cursor.fetchone()[0]

        cursor.execute("SELECT action, COUNT(*) FROM audit_events GROUP BY action")
        by_action = {row[0]: row[1] for row in cursor.fetchall()}

        conn.close()

        return {
            "total_events": total,
            "by_action": by_action
        }


# Global audit logger
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get global audit logger"""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


__all__ = ["AuditLogger", "AuditEvent", "AuditAction", "AuditLevel", "get_audit_logger"]
