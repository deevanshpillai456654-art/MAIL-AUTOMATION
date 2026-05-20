"""
Queue low-confidence or policy-flagged items for human review.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("human_review")


@dataclass
class ReviewItem:
    item_id: str
    tenant_id: str
    reason: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    status: str = "pending"


class HumanReviewQueue:
    def __init__(self, max_items: int = 10_000):
        self._items: Dict[str, ReviewItem] = {}
        self._order: List[str] = []
        self._max = max_items
        self._lock = threading.RLock()

    def enqueue(self, tenant_id: str, reason: str, payload: Dict[str, Any]) -> str:
        item_id = f"hr_{uuid.uuid4().hex[:12]}"
        item = ReviewItem(item_id=item_id, tenant_id=tenant_id, reason=reason, payload=payload)
        with self._lock:
            if len(self._order) >= self._max:
                oldest = self._order.pop(0)
                self._items.pop(oldest, None)
            self._items[item_id] = item
            self._order.append(item_id)
        logger.info("Human review enqueued %s tenant=%s reason=%s", item_id, tenant_id, reason)
        return item_id

    def pending_for_tenant(self, tenant_id: str) -> List[ReviewItem]:
        with self._lock:
            return [
                self._items[i]
                for i in self._order
                if self._items[i].tenant_id == tenant_id and self._items[i].status == "pending"
            ]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            pending = [item for item in self._items.values() if item.status == "pending"]
            return {
                "pending": len(pending),
                "tenants_with_pending": len({item.tenant_id for item in pending}),
            }

    def resolve(self, item_id: str, resolution: str) -> None:
        with self._lock:
            if item_id in self._items:
                self._items[item_id].status = resolution


__all__ = ["ReviewItem", "HumanReviewQueue"]
