from __future__ import annotations
from typing import Callable
from queues.queue_manager import TenantQueue

class TenantWorker:
    def __init__(self, queue: TenantQueue, handler: Callable) -> None:
        self.queue = queue
        self.handler = handler

    def run_once(self, tenant_id: str) -> dict:
        job = self.queue.dequeue(tenant_id)
        if not job:
            return {"processed": 0}
        try:
            self.handler(job)
            job.status = "done"
            return {"processed": 1, "status": "done"}
        except Exception as exc:
            self.queue.fail(job, str(exc))
            return {"processed": 1, "status": "failed", "error": str(exc)}
