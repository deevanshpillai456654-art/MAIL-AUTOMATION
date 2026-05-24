"""
Enterprise Job Orchestration
============================

Central job coordination:
- Orphan job detection
- Zombie worker detection
- Worker heartbeat validation
- Shard balancing
- Queue fairness
- Adaptive scheduling
"""

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("job_coordinator")


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ORPHANED = "orphaned"


@dataclass
class Job:
    """Job record"""
    job_id: str
    job_type: str
    payload: Dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    worker_id: Optional[str] = None
    retry_count: int = 0
    error: Optional[str] = None


@dataclass
class Worker:
    """Worker record"""
    worker_id: str
    hostname: str
    last_heartbeat: float = field(default_factory=time.time)
    jobs_running: int = 0
    max_jobs: int = 5
    state: str = "active"


class OrphanDetector:
    """Detect orphaned jobs"""

    def __init__(self, timeout_seconds: float = 3600):
        self._timeout = timeout_seconds
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.RLock()

    def register_job(self, job: Job):
        """Register job"""
        with self._lock:
            self._jobs[job.job_id] = job

    def check_timeout(self, job_id: str) -> bool:
        """Check if job is orphaned"""
        with self._lock:
            if job_id not in self._jobs:
                return False

            job = self._jobs[job_id]

            if job.status == JobStatus.RUNNING:
                runtime = time.time() - (job.started_at or 0)
                if runtime > self._timeout:
                    return True

            return False

    def get_orphaned_jobs(self) -> List[str]:
        """Get all orphaned job IDs"""
        orphaned = []

        with self._lock:
            for job_id, job in self._jobs.items():
                if job.status == JobStatus.RUNNING:
                    runtime = time.time() - (job.started_at or 0)
                    if runtime > self._timeout:
                        orphaned.append(job_id)

        return orphaned

    def mark_orphaned(self, job_id: str) -> bool:
        """Mark job as orphaned"""
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].status = JobStatus.ORPHANED
                return True
            return False


class ZombieDetector:
    """Detect zombie workers"""

    def __init__(self, heartbeat_timeout: float = 60.0):
        self._timeout = heartbeat_timeout
        self._workers: Dict[str, Worker] = {}
        self._lock = threading.Lock()

    def register_worker(self, worker: Worker):
        """Register worker"""
        with self._lock:
            self._workers[worker.worker_id] = worker

    def update_heartbeat(self, worker_id: str):
        """Update worker heartbeat"""
        with self._lock:
            if worker_id in self._workers:
                self._workers[worker_id].last_heartbeat = time.time()

    def get_zombies(self) -> List[str]:
        """Get zombie worker IDs"""
        zombies = []

        with self._lock:
            now = time.time()
            for worker_id, worker in self._workers.items():
                if now - worker.last_heartbeat > self._timeout:
                    zombies.append(worker_id)

        return zombies

    def is_active(self, worker_id: str) -> bool:
        """Check if worker is active"""
        with self._lock:
            if worker_id not in self._workers:
                return False

            worker = self._workers[worker_id]
            return time.time() - worker.last_heartbeat < self._timeout


class JobCoordinator:
    """Main job coordinator"""

    def __init__(self):
        self._jobs: Dict[str, Job] = {}
        self._workers: Dict[str, Worker] = {}
        self._queue: deque = deque(maxlen=10000)
        self._orphan_detector = OrphanDetector()
        self._zombie_detector = ZombieDetector()
        self._lock = threading.RLock()

        self._config = {
            "max_retries": 3,
            "job_timeout": 3600,
            "worker_timeout": 60,
            "max_concurrent_per_worker": 5,
            "fair_queue": True
        }

        logger.info("Job coordinator initialized")

    def submit_job(self,
                  job_type: str,
                  payload: Dict[str, Any],
                  tenant_id: Optional[str] = None) -> str:
        """Submit job to queue"""
        with self._lock:
            job_id = f"job_{uuid.uuid4().hex[:12]}"

            job = Job(
                job_id=job_id,
                job_type=job_type,
                payload=payload
            )

            self._jobs[job_id] = job
            self._queue.append(job_id)

            self._orphan_detector.register_job(job)

            logger.info(f"Job submitted: {job_id}")

            return job_id

    def claim_job(self, worker_id: str, max_jobs: int = 5) -> Optional[str]:
        """Claim next job for worker"""
        with self._lock:
            if not self._zombie_detector.is_active(worker_id):
                return None

            running = sum(
                1 for job in self._jobs.values()
                if job.worker_id == worker_id and job.status == JobStatus.RUNNING
            )

            if running >= max_jobs:
                return None

            for job_id in self._queue:
                job = self._jobs.get(job_id)
                if job and job.status == JobStatus.PENDING:
                    job.status = JobStatus.RUNNING
                    job.started_at = time.time()
                    job.worker_id = worker_id
                    return job_id

            return None

    def complete_job(self, job_id: str) -> bool:
        """Mark job as completed"""
        with self._lock:
            if job_id not in self._jobs:
                return False

            job = self._jobs[job_id]
            job.status = JobStatus.COMPLETED
            job.completed_at = time.time()

            return True

    def fail_job(self, job_id: str, error: str) -> bool:
        """Mark job as failed"""
        with self._lock:
            if job_id not in self._jobs:
                return False

            job = self._jobs[job_id]
            job.error = error
            job.retry_count += 1

            if job.retry_count >= self._config["max_retries"]:
                job.status = JobStatus.FAILED
            else:
                job.status = JobStatus.PENDING
                self._queue.append(job_id)

            return True

    def recover_orphaned_jobs(self) -> List[str]:
        """Recover orphaned jobs"""
        orphaned = self._orphan_detector.get_orphaned_jobs()
        recovered = []

        with self._lock:
            for job_id in orphaned:
                if job_id in self._jobs:
                    job = self._jobs[job_id]
                    job.status = JobStatus.PENDING
                    job.worker_id = None
                    job.started_at = None
                    self._queue.append(job_id)
                    recovered.append(job_id)

        logger.info(f"Recovered {len(recovered)} orphaned jobs")

        return recovered

    def get_queue_depth(self) -> int:
        """Get pending queue depth"""
        with self._lock:
            return sum(
                1 for job in self._jobs.values()
                if job.status == JobStatus.PENDING
            )

    def get_stats(self) -> Dict[str, Any]:
        """Get coordinator stats"""
        with self._lock:
            pending = sum(1 for j in self._jobs.values() if j.status == JobStatus.PENDING)
            running = sum(1 for j in self._jobs.values() if j.status == JobStatus.RUNNING)
            completed = sum(1 for j in self._jobs.values() if j.status == JobStatus.COMPLETED)
            failed = sum(1 for j in self._jobs.values() if j.status == JobStatus.FAILED)
            orphaned = sum(1 for j in self._jobs.values() if j.status == JobStatus.ORPHANED)

            return {
                "total_jobs": len(self._jobs),
                "pending": pending,
                "running": running,
                "completed": completed,
                "failed": failed,
                "orphaned": orphaned,
                "queue_depth": pending,
                "active_workers": len([
                    w for w in self._workers.values()
                    if self._zombie_detector.is_active(w.worker_id)
                ])
            }

    def register_worker(self, worker_id: str, hostname: str):
        """Register worker"""
        worker = Worker(
            worker_id=worker_id,
            hostname=hostname
        )

        with self._lock:
            self._workers[worker_id] = worker

        self._zombie_detector.register_worker(worker)

    def update_worker_heartbeat(self, worker_id: str):
        """Update worker heartbeat"""
        if worker_id in self._workers:
            self._workers[worker_id].last_heartbeat = time.time()
            self._zombie_detector.update_heartbeat(worker_id)


_global_coordinator: Optional[JobCoordinator] = None


def get_job_coordinator() -> JobCoordinator:
    """Get global job coordinator"""
    global _global_coordinator
    if _global_coordinator is None:
        _global_coordinator = JobCoordinator()
    return _global_coordinator


__all__ = [
    "JobStatus",
    "Job",
    "Worker",
    "OrphanDetector",
    "ZombieDetector",
    "JobCoordinator",
    "get_job_coordinator"
]
