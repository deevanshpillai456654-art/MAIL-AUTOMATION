"""
Quota Manager - Resource Quotas
==============================

Resource quota management:
- User quotas
- Provider quotas  
- Storage quotas
- API rate quotas
- Quota tracking
- Quota enforcement
"""

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger("quota.manager")


class QuotaType(Enum):
    STORAGE = "storage"
    API_CALLS = "api_calls"
    EMAILS = "emails"
    ATTACHMENTS = "attachments"
    BANDWIDTH = "bandwidth"


class QuotaLimit:
    """Quota limit"""
    def __init__(self, limit: float, unit: str = "bytes"):
        self.limit = limit
        self.unit = unit


@dataclass
class QuotaUsage:
    """Current quota usage"""
    user_id: str
    quota_type: QuotaType
    used: float = 0
    limit: float = 0
    reset_at: float = 0
    last_update: float = field(default_factory=time.time)


class QuotaManager:
    """
    Resource quota manager.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or "data/quotas.db"
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._init_db()
        self._lock = threading.Lock()

        # Default quotas
        self._default_limits = {
            QuotaType.STORAGE: QuotaLimit(1024 * 1024 * 1024),  # 1GB
            QuotaType.API_CALLS: QuotaLimit(1000, "calls/day"),
            QuotaType.EMAILS: QuotaLimit(10000, "emails/day"),
            QuotaType.ATTACHMENTS: QuotaLimit(100, "attachments/day"),
        }

        logger.info("QuotaManager initialized")

    def _init_db(self):
        """Initialize quota database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS quotas (
                id INTEGER PRIMARY KEY,
                user_id TEXT,
                quota_type TEXT,
                used REAL,
                limit_value REAL,
                reset_at REAL,
                last_update REAL
            )
        """)

        conn.commit()
        conn.close()

    def set_quota(self, user_id: str, quota_type: QuotaType, limit: float, reset_period: float = 86400):
        """Set user quota"""
        reset_at = time.time() + reset_period

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO quotas (user_id, quota_type, used, limit_value, reset_at, last_update)
            VALUES (?, ?, 0, ?, ?, ?)
        """, (user_id, quota_type.value, limit, reset_at, time.time()))

        conn.commit()
        conn.close()

    def check_quota(self, user_id: str, quota_type: QuotaType, amount: float = 1) -> bool:
        """Check if quota allows"""
        with self._lock:
            # Get current usage
            usage = self._get_usage(user_id, quota_type)

            if not usage:
                # No quota set, allow
                return True

            # Check limit
            return usage.used + amount <= usage.limit

    def consume_quota(self, user_id: str, quota_type: QuotaType, amount: float = 1) -> bool:
        """Consume quota"""
        with self._lock:
            if not self.check_quota(user_id, quota_type, amount):
                logger.warning(f"Quota exceeded: {user_id} {quota_type.value}")
                return False

            # Update usage
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE quotas SET used = used + ?, last_update = ?
                WHERE user_id = ? AND quota_type = ?
            """, (amount, time.time(), user_id, quota_type.value))

            conn.commit()
            conn.close()

            return True

    def _get_usage(self, user_id: str, quota_type: QuotaType) -> Optional[QuotaUsage]:
        """Get current usage"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM quotas WHERE user_id = ? AND quota_type = ?
        """, (user_id, quota_type.value))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return QuotaUsage(
            user_id=row[1],
            quota_type=QuotaType(row[2]),
            used=row[3],
            limit=row[4],
            reset_at=row[5]
        )

    def reset_quota(self, user_id: str, quota_type: QuotaType = None):
        """Reset quota"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if quota_type:
            cursor.execute("""
                UPDATE quotas SET used = 0 WHERE user_id = ? AND quota_type = ?
            """, (user_id, quota_type.value))
        else:
            cursor.execute("""
                UPDATE quotas SET used = 0 WHERE user_id = ?
            """, (user_id,))

        conn.commit()
        conn.close()

    def get_remaining(self, user_id: str, quota_type: QuotaType) -> float:
        """Get remaining quota"""
        usage = self._get_usage(user_id, quota_type)

        if not usage:
            return self._default_limits.get(quota_type, QuotaLimit(999999)).limit

        return max(0, usage.limit - usage.used)

    def get_stats(self) -> Dict:
        """Get quota stats"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(DISTINCT user_id) FROM quotas")
        users = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(used) FROM quotas")
        total_used = cursor.fetchone()[0] or 0

        conn.close()

        return {
            "users_with_quotas": users,
            "total_usage": total_used
        }


# Global quota manager
_quota_manager: Optional[QuotaManager] = None


def get_quota_manager() -> QuotaManager:
    """Get global quota manager"""
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = QuotaManager()
    return _quota_manager


__all__ = ["QuotaManager", "QuotaUsage", "QuotaType", "QuotaLimit", "get_quota_manager"]
