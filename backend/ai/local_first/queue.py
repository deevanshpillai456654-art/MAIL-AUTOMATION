"""Durable local AI execution queue with watchdog metadata."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from backend import config
except Exception:  # pragma: no cover
    class _Config:
        DATA_DIR = str(Path.cwd() / "data")
    config = _Config()  # type: ignore

from .runtime import get_runtime


@dataclass
class QueueItem:
    id: str
    task: str
    payload: Dict[str, Any]
    priority: int = 5
    status: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    attempts: int = 0


class AIExecutionQueue:
    def __init__(self, state_path: Optional[str] = None) -> None:
        self.state_path = Path(state_path or Path(config.DATA_DIR) / "ai_execution_queue_v9_1.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._items: Dict[str, QueueItem] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            for raw in data.get("items", []):
                item = QueueItem(**raw)
                if item.status in {"running", "queued"}:
                    item.status = "recovered"
                self._items[item.id] = item
        except Exception:
            self._items.clear()

    def _save(self) -> None:
        payload = {"version": "9.7.0", "items": [asdict(i) for i in self._items.values()]}
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.state_path)

    def submit(self, task: str, payload: Dict[str, Any], priority: int = 5) -> str:
        item = QueueItem(id=str(uuid.uuid4()), task=task, payload=payload, priority=priority)
        with self._lock:
            self._items[item.id] = item
            self._save()
        return item.id

    def run_now(self, item_id: str) -> Dict[str, Any]:
        with self._lock:
            item = self._items[item_id]
            item.status = "running"
            item.started_at = time.time()
            item.attempts += 1
            self._save()
        try:
            result = get_runtime().infer(item.task, item.payload)
            with self._lock:
                item.status = "completed"
                item.finished_at = time.time()
                item.result = asdict(result)
                self._save()
                return item.result
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                item.status = "failed"
                item.finished_at = time.time()
                item.error = str(exc)
                self._save()
            raise

    async def run_now_async(self, item_id: str) -> Dict[str, Any]:
        return await asyncio.to_thread(self.run_now, item_id)

    def cancel(self, item_id: str) -> bool:
        with self._lock:
            item = self._items.get(item_id)
            if not item or item.status in {"completed", "failed"}:
                return False
            item.status = "cancelled"
            item.finished_at = time.time()
            self._save()
            return True

    def status(self) -> Dict[str, Any]:
        with self._lock:
            counts: Dict[str, int] = {}
            for item in self._items.values():
                counts[item.status] = counts.get(item.status, 0) + 1
            oldest_running = min((i.started_at for i in self._items.values() if i.status == "running" and i.started_at), default=None)
            return {
                "version": "9.7.0",
                "status": "ready",
                "depth": sum(1 for i in self._items.values() if i.status in {"queued", "recovered"}),
                "counts": counts,
                "oldest_running_age_seconds": round(time.time() - oldest_running, 3) if oldest_running else 0,
                "watchdog": "healthy",
                "items": [asdict(i) for i in sorted(self._items.values(), key=lambda x: x.created_at, reverse=True)[:50]],
            }


_queue: Optional[AIExecutionQueue] = None
_queue_lock = threading.Lock()


def get_execution_queue() -> AIExecutionQueue:
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = AIExecutionQueue()
        return _queue
