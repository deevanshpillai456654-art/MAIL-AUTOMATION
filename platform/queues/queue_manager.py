from __future__ import annotations
from collections import deque
from typing import Deque, Dict, List
from sdk.models import QueueJob, utc_now

class TenantQueue:
    def __init__(self, name: str = "default") -> None:
        self.name = name
        self.queues: Dict[str, Deque[QueueJob]] = {}
        self.dead_letters: Dict[str, List[QueueJob]] = {}

    def enqueue(self, job: QueueJob) -> QueueJob:
        self.queues.setdefault(job.tenant_id, deque()).append(job)
        return job

    def dequeue(self, tenant_id: str) -> QueueJob | None:
        q = self.queues.setdefault(tenant_id, deque())
        return q.popleft() if q else None

    def fail(self, job: QueueJob, error: str) -> None:
        job.attempts += 1
        job.last_error = error
        job.updated_at = utc_now()
        if job.attempts >= job.max_attempts:
            job.status = "dead_letter"
            self.dead_letters.setdefault(job.tenant_id, []).append(job)
        else:
            job.status = "retry_queued"
            self.enqueue(job)

    def stats(self, tenant_id: str) -> dict:
        return {"queued": len(self.queues.get(tenant_id, [])), "dead_letters": len(self.dead_letters.get(tenant_id, []))}
