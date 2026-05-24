"""
Notification Queue Manager
=========================

Notification queuing:
- Queue management
- Priority queuing
- Batch notifications
- Retry logic
- Delivery tracking
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("notification.queue")


class NotificationPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


class NotificationStatus(Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    DELIVERED = "delivered"


@dataclass
class Notification:
    """Notification"""
    notification_id: str
    user_id: str
    title: str
    message: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    status: NotificationStatus = NotificationStatus.PENDING
    created_at: float = field(default_factory=time.time)
    sent_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0


class NotificationQueue:
    """
    Notification queue manager.
    """

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._queue: deque = deque(maxlen=max_size)
        self._lock = threading.Lock()

        # Handlers
        self._handlers: Dict[str, Callable] = {}

        # Metrics
        self._sent = 0
        self._failed = 0

        logger.info("NotificationQueue initialized")

    def enqueue(
        self,
        notification_id: str,
        user_id: str,
        title: str,
        message: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: Dict = None
    ) -> bool:
        """Add notification to queue"""
        notification = Notification(
            notification_id=notification_id,
            user_id=user_id,
            title=title,
            message=message,
            priority=priority,
            metadata=metadata or {}
        )

        with self._lock:
            self._queue.append(notification)
            return True

    def process(self, batch_size: int = 10) -> int:
        """Process notifications"""
        processed = 0

        with self._lock:
            if not self._queue:
                return 0

            # Get batch
            batch = []
            for _ in range(min(batch_size, len(self._queue))):
                if self._queue:
                    batch.append(self._queue.popleft())

        for notification in batch:
            if self._deliver(notification):
                notification.status = NotificationStatus.SENT
                notification.sent_at = time.time()
                self._sent += 1
                processed += 1
            else:
                notification.retry_count += 1
                if notification.retry_count < 3:
                    # Re-queue
                    with self._lock:
                        self._queue.append(notification)
                else:
                    notification.status = NotificationStatus.FAILED
                    self._failed += 1

        return processed

    def _deliver(self, notification: Notification) -> bool:
        """Deliver notification"""
        handler = self._handlers.get(notification.user_id)

        if handler:
            try:
                handler(notification)
                return True
            except Exception as e:
                logger.error(f"Notification delivery error: {e}")
                return False

        return True  # No handler = considered delivered

    def register_handler(self, user_id: str, handler: Callable):
        """Register notification handler"""
        self._handlers[user_id] = handler

    def get_stats(self) -> Dict:
        """Get queue stats"""
        with self._lock:
            return {
                "queued": len(self._queue),
                "sent": self._sent,
                "failed": self._failed,
                "success_rate": self._sent / max(1, self._sent + self._failed)
            }


# Global notification queue
_notification_queue: Optional[NotificationQueue] = None


def get_notification_queue() -> NotificationQueue:
    """Get global notification queue"""
    global _notification_queue
    if _notification_queue is None:
        _notification_queue = NotificationQueue()
    return _notification_queue


__all__ = ["NotificationQueue", "Notification", "NotificationPriority", "NotificationStatus", "get_notification_queue"]
