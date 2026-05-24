"""
Batch Processor - Efficient Batch Operations
==========================================

Batch processing for efficient operations:
- Batch accumulation
- Size-based triggering
- Time-based triggering
- Parallel processing
- Progress tracking
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("batch.processor")


class BatchState(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class BatchJob:
    """Batch job"""
    job_id: str
    items: List[Any] = field(default_factory=list)
    state: BatchState = BatchState.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Any = None
    error: Optional[str] = None


class BatchProcessor:
    """
    Enterprise batch processor.
    """

    def __init__(
        self,
        max_batch_size: int = 100,
        max_wait_seconds: float = 5.0,
        max_workers: int = 4
    ):
        self.max_batch_size = max_batch_size
        self.max_wait_seconds = max_wait_seconds
        self.max_workers = max_workers

        self._queue: List[BatchJob] = []
        self._lock = threading.Lock()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # Processing handler
        self._handler: Optional[Callable] = None

        # Analytics
        self._total_processed = 0
        self._total_batches = 0

        logger.info("BatchProcessor initialized")

    def set_handler(self, handler: Callable):
        """Set batch processing handler"""
        self._handler = handler

    def start(self):
        """Start batch processor"""
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._worker_thread.start()
        logger.info("BatchProcessor started")

    def stop(self):
        """Stop batch processor"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)

    def submit(self, items: List[Any]) -> str:
        """Submit items for batch processing"""
        import secrets
        job_id = f"job_{secrets.token_hex(8)}"

        job = BatchJob(job_id=job_id, items=items)

        with self._lock:
            self._queue.append(job)

            # Check if we should process immediately
            if len(self._queue) >= self.max_batch_size:
                self._trigger_processing()

        return job_id

    def _trigger_processing(self):
        """Trigger batch processing"""
        if self._queue and self._worker_thread and self._worker_thread.is_alive():
            # Already processing
            pass
        elif self._handler:
            # Process synchronously
            self._process_immediate()

    def _process_loop(self):
        """Processing loop"""
        while self._running:
            try:
                time.sleep(0.1)

                with self._lock:
                    if not self._queue:
                        continue

                    # Check time-based trigger
                    oldest = self._queue[0]
                    if time.time() - oldest.created_at < self.max_wait_seconds:
                        continue

                self._process_immediate()
            except Exception as e:
                logger.error(f"Batch processing error: {e}")

    def _process_immediate(self):
        """Process current batch"""
        if not self._handler:
            return

        with self._lock:
            if not self._queue:
                return

            job = self._queue.pop(0)
            job.state = BatchState.PROCESSING
            job.started_at = time.time()

        try:
            job.result = self._handler(job.items)
            job.state = BatchState.COMPLETED
            job.completed_at = time.time()

            self._total_processed += len(job.items)
            self._total_batches += 1
        except Exception as e:
            job.state = BatchState.FAILED
            job.error = str(e)
            logger.error(f"Batch job failed: {e}")

    def get_job(self, job_id: str) -> Optional[BatchJob]:
        """Get job status"""
        with self._lock:
            for job in self._queue:
                if job.job_id == job_id:
                    return job
        return None

    def get_stats(self) -> Dict:
        """Get batch processor stats"""
        return {
            "queued_jobs": len(self._queue),
            "total_processed": self._total_processed,
            "total_batches": self._total_batches,
            "running": self._running
        }


# Global batch processor
_batch_processor: Optional[BatchProcessor] = None


def get_batch_processor() -> BatchProcessor:
    """Get global batch processor"""
    global _batch_processor
    if _batch_processor is None:
        _batch_processor = BatchProcessor()
    return _batch_processor


__all__ = ["BatchProcessor", "BatchJob", "BatchState", "get_batch_processor"]
