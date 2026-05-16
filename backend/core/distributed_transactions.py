"""
Saga-style orchestration with explicit compensation steps and a durable journal.

Exactly-once end-to-end is not guaranteed without an external idempotency store;
callers should combine sagas with inbox_dedupe and idempotency_manager.
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
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("distributed_txn")


class SagaStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPENSATED = "compensated"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SagaStep:
    name: str
    action: Callable[[Dict[str, Any]], Any]
    compensate: Optional[Callable[[Dict[str, Any]], Any]] = None


@dataclass
class SagaInstance:
    saga_id: str
    status: SagaStatus = SagaStatus.PENDING
    context: Dict[str, Any] = field(default_factory=dict)
    completed_steps: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class SagaJournal:
    def __init__(self, path: Optional[Path] = None):
        self._path = path
        self._lock = threading.RLock()

    def append(self, record: Dict[str, Any]) -> None:
        if not self._path:
            return
        line = json.dumps(record, default=str) + "\n"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line)


class SagaOrchestrator:
    def __init__(self, journal_path: Optional[Path] = None):
        self._journal = SagaJournal(journal_path)
        self._instances: Dict[str, SagaInstance] = {}
        self._lock = threading.RLock()

    def start_saga(self, context: Optional[Dict[str, Any]] = None) -> str:
        saga_id = f"saga_{uuid.uuid4().hex}"
        inst = SagaInstance(saga_id=saga_id, context=dict(context or {}))
        with self._lock:
            self._instances[saga_id] = inst
        self._journal.append({"event": "saga_started", "saga_id": saga_id, "ts": time.time()})
        return saga_id

    def run(self, saga_id: str, steps: List[SagaStep]) -> None:
        with self._lock:
            inst = self._instances.get(saga_id)
            if not inst:
                raise KeyError(saga_id)
            inst.status = SagaStatus.RUNNING
            inst.updated_at = time.time()

        done: List[SagaStep] = []
        try:
            for step in steps:
                logger.info("Saga %s executing step %s", saga_id, step.name)
                step.action(inst.context)
                done.append(step)
                with self._lock:
                    inst = self._instances[saga_id]
                    inst.completed_steps.append(step.name)
                    inst.updated_at = time.time()
                self._journal.append(
                    {"event": "step_ok", "saga_id": saga_id, "step": step.name, "ts": time.time()}
                )
            with self._lock:
                self._instances[saga_id].status = SagaStatus.COMPLETED
                self._instances[saga_id].updated_at = time.time()
            self._journal.append({"event": "saga_completed", "saga_id": saga_id, "ts": time.time()})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Saga %s failed: %s", saga_id, exc)
            self._journal.append(
                {"event": "saga_failed", "saga_id": saga_id, "error": str(exc), "ts": time.time()}
            )
            with self._lock:
                ctx = dict(self._instances[saga_id].context)
            for step in reversed(done):
                if step.compensate:
                    try:
                        step.compensate(ctx)
                        self._journal.append(
                            {
                                "event": "step_compensated",
                                "saga_id": saga_id,
                                "step": step.name,
                                "ts": time.time(),
                            }
                        )
                    except Exception as cexc:  # noqa: BLE001
                        logger.critical(
                            "Compensation failed saga=%s step=%s: %s", saga_id, step.name, cexc
                        )
                        self._journal.append(
                            {
                                "event": "compensation_failed",
                                "saga_id": saga_id,
                                "step": step.name,
                                "error": str(cexc),
                                "ts": time.time(),
                            }
                        )
            with self._lock:
                self._instances[saga_id].status = SagaStatus.COMPENSATED
                self._instances[saga_id].updated_at = time.time()
            raise


__all__ = ["SagaStatus", "SagaStep", "SagaInstance", "SagaOrchestrator", "SagaJournal"]
