"""
Transactional outbox: enqueue domain events before side effects are fully committed.

Consumers mark deliveries to achieve at-least-once dispatch without losing events
if the process crashes after DB commit and before publish.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("outbox")


class OutboxStatus(Enum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass
class OutboxRecord:
    record_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: Dict[str, Any]
    tenant_id: Optional[str] = None
    status: OutboxStatus = OutboxStatus.PENDING
    created_at: float = field(default_factory=time.time)
    published_at: Optional[float] = None
    attempts: int = 0


class OutboxManager:
    def __init__(self, persistence_path: Optional[Path] = None):
        self._records: Dict[str, OutboxRecord] = {}
        self._pending_order: List[str] = []
        self._path = persistence_path
        self._lock = threading.RLock()
        if self._path and self._path.exists():
            self._load()

    def _load(self) -> None:
        assert self._path is not None
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                rec = OutboxRecord(
                    record_id=data["record_id"],
                    aggregate_type=data["aggregate_type"],
                    aggregate_id=data["aggregate_id"],
                    event_type=data["event_type"],
                    payload=data["payload"],
                    tenant_id=data.get("tenant_id"),
                    status=OutboxStatus(data["status"]),
                    created_at=data["created_at"],
                    published_at=data.get("published_at"),
                    attempts=int(data.get("attempts", 0)),
                )
                self._records[rec.record_id] = rec
                if rec.status == OutboxStatus.PENDING:
                    self._pending_order.append(rec.record_id)

    def _persist_snapshot(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        with self._lock:
            lines = [json.dumps(self._record_to_dict(r), default=str) for r in self._records.values()]
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(self._path)

    def _record_to_dict(self, r: OutboxRecord) -> Dict[str, Any]:
        return {
            "record_id": r.record_id,
            "aggregate_type": r.aggregate_type,
            "aggregate_id": r.aggregate_id,
            "event_type": r.event_type,
            "payload": r.payload,
            "tenant_id": r.tenant_id,
            "status": r.status.value,
            "created_at": r.created_at,
            "published_at": r.published_at,
            "attempts": r.attempts,
        }

    def enqueue(
        self,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> str:
        record_id = f"ob_{uuid.uuid4().hex}"
        rec = OutboxRecord(
            record_id=record_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            payload=payload,
            tenant_id=tenant_id,
        )
        with self._lock:
            self._records[record_id] = rec
            self._pending_order.append(record_id)
        self._persist_snapshot()
        logger.debug("Outbox enqueue %s %s", event_type, record_id)
        return record_id

    def pending(self, limit: int = 100) -> List[OutboxRecord]:
        with self._lock:
            ids = [i for i in self._pending_order if i in self._records][:limit]
            return [self._records[i] for i in ids if self._records[i].status == OutboxStatus.PENDING]

    def mark_published(self, record_id: str) -> None:
        with self._lock:
            rec = self._records.get(record_id)
            if not rec:
                return
            rec.status = OutboxStatus.PUBLISHED
            rec.published_at = time.time()
            if record_id in self._pending_order:
                self._pending_order.remove(record_id)
        self._persist_snapshot()

    def mark_failed(self, record_id: str) -> None:
        with self._lock:
            rec = self._records.get(record_id)
            if not rec:
                return
            rec.attempts += 1
            if rec.attempts >= 10:
                rec.status = OutboxStatus.FAILED
                if record_id in self._pending_order:
                    self._pending_order.remove(record_id)
        self._persist_snapshot()


__all__ = ["OutboxStatus", "OutboxRecord", "OutboxManager"]
