"""
Notification system for AI Email Organizer
"""

import json
import logging
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

_log = logging.getLogger(__name__)


class NotificationType(str, Enum):
    EMAIL_CLASSIFIED = "email_classified"
    HIGH_PRIORITY = "high_priority"
    RULE_TRIGGERED = "rule_triggered"
    SYNC_COMPLETE = "sync_complete"
    ERROR = "error"
    INFO = "info"


class NotificationPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Notification:
    def __init__(
        self,
        title: str,
        message: str,
        notification_type: NotificationType = NotificationType.INFO,
        priority: NotificationPriority = NotificationPriority.MEDIUM,
        data: Optional[Dict] = None
    ):
        self.id = f"notif_{datetime.now().timestamp()}"
        self.title = title
        self.message = message
        self.type = notification_type
        self.priority = priority
        self.data = data or {}
        self.created_at = datetime.now()
        self.read = False

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "type": self.type.value,
            "priority": self.priority.value,
            "data": self.data,
            "created_at": self.created_at.isoformat(),
            "read": self.read
        }


class NotificationManager:
    def __init__(self, storage_path: str = None):
        if storage_path is None:
            base_path = Path(__file__).parent.parent / "data"
            base_path.mkdir(parents=True, exist_ok=True)
            storage_path = str(base_path / "notifications.json")

        self.storage_path = storage_path
        self.notifications: List[Notification] = []
        self.listeners: List[callable] = []
        self._load()

    def _load(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    for n in data.get("notifications", []):
                        notif = Notification(
                            title=n["title"],
                            message=n["message"],
                            notification_type=NotificationType(n.get("type", "info")),
                            priority=NotificationPriority(n.get("priority", "medium"))
                        )
                        notif.id = n["id"]
                        notif.created_at = datetime.fromisoformat(n["created_at"])
                        notif.read = n.get("read", False)
                        self.notifications.append(notif)
            except Exception as exc:
                self.notifications = []
                _log.warning("Failed to load notifications from %s: %s", self.storage_path, exc)

    def _save(self):
        with open(self.storage_path, "w") as f:
            json.dump({
                "notifications": [n.to_dict() for n in self.notifications]
            }, f, indent=2)

    def add(self, notification: Notification):
        self.notifications.insert(0, notification)
        if len(self.notifications) > 100:
            self.notifications = self.notifications[:100]
        self._save()

        for listener in self.listeners:
            try:
                listener(notification)
            except Exception as exc:
                _log.debug("notification listener raised: %s", exc)

    def mark_as_read(self, notification_id: str):
        for notif in self.notifications:
            if notif.id == notification_id:
                notif.read = True
                self._save()
                break

    def mark_all_read(self):
        for notif in self.notifications:
            notif.read = True
        self._save()

    def delete(self, notification_id: str):
        self.notifications = [n for n in self.notifications if n.id != notification_id]
        self._save()

    def clear(self):
        self.notifications = []
        self._save()

    def get_all(self, limit: int = 50) -> List[Dict]:
        return [n.to_dict() for n in self.notifications[:limit]]

    def get_unread(self) -> List[Dict]:
        return [n.to_dict() for n in self.notifications if not n.read]

    def get_unread_count(self) -> int:
        return sum(1 for n in self.notifications if not n.read)

    def add_listener(self, listener: callable):
        self.listeners.append(listener)

    def remove_listener(self, listener: callable):
        if listener in self.listeners:
            self.listeners.remove(listener)


notification_manager = NotificationManager()


def notify_classification(email: Dict, category: str, confidence: float):
    """Send notification when email is classified"""
    if confidence < 0.70:
        return

    priority = NotificationPriority.MEDIUM
    if confidence > 0.95:
        priority = NotificationPriority.HIGH

    notification = Notification(
        title=f"Email Classified: {category}",
        message=f'"{email.get("subject", "No Subject")}" classified as {category}',
        notification_type=NotificationType.EMAIL_CLASSIFIED,
        priority=priority,
        data={"email": email, "category": category, "confidence": confidence}
    )
    notification_manager.add(notification)


def notify_high_priority(email: Dict):
    """Send notification for high priority email"""
    notification = Notification(
        title="High Priority Email",
        message=f'Important email from {email.get("sender", "Unknown")}',
        notification_type=NotificationType.HIGH_PRIORITY,
        priority=NotificationPriority.HIGH,
        data={"email": email}
    )
    notification_manager.add(notification)


def notify_rule_triggered(rule_name: str, email: Dict, action: str):
    """Send notification when rule is triggered"""
    notification = Notification(
        title=f"Rule Triggered: {rule_name}",
        message=f'Action "{action}" applied to "{email.get("subject", "")}"',
        notification_type=NotificationType.RULE_TRIGGERED,
        priority=NotificationPriority.MEDIUM,
        data={"rule": rule_name, "email": email, "action": action}
    )
    notification_manager.add(notification)


def notify_sync_complete(provider: str, count: int):
    """Send notification when sync completes"""
    notification = Notification(
        title=f"{provider.title()} Sync Complete",
        message=f"Processed {count} emails",
        notification_type=NotificationType.SYNC_COMPLETE,
        priority=NotificationPriority.LOW,
        data={"provider": provider, "count": count}
    )
    notification_manager.add(notification)


def notify_error(error: str, context: Dict = None):
    """Send error notification"""
    notification = Notification(
        title="Error",
        message=error,
        notification_type=NotificationType.ERROR,
        priority=NotificationPriority.HIGH,
        data=context or {}
    )
    notification_manager.add(notification)
