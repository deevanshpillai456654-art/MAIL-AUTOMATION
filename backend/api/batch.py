"""
Batch processing for AI Email Organizer
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional


class BatchStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BatchJob:
    def __init__(
        self,
        job_id: str,
        name: str,
        items: List[Dict],
        process_func: Callable,
        batch_size: int = 10
    ):
        self.job_id = job_id
        self.name = name
        self.items = items
        self.process_func = process_func
        self.batch_size = batch_size
        self.status = BatchStatus.PENDING
        self.progress = 0
        self.total = len(items)
        self.processed = 0
        self.results = []
        self.errors = []
        self.started_at = None
        self.completed_at = None

    def start(self):
        self.status = BatchStatus.RUNNING
        self.started_at = datetime.now()

    def complete(self):
        self.status = BatchStatus.COMPLETED
        self.completed_at = datetime.now()

    def fail(self):
        self.status = BatchStatus.FAILED
        self.completed_at = datetime.now()

    def to_dict(self) -> Dict:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "status": self.status.value,
            "total": self.total,
            "processed": self.processed,
            "progress": self.progress,
            "results_count": len(self.results),
            "errors_count": len(self.errors),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }


class BatchProcessor:
    def __init__(self, max_workers: int = 4):
        self.jobs: Dict[str, BatchJob] = {}
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def create_job(
        self,
        name: str,
        items: List[Dict],
        process_func: Callable,
        batch_size: int = 10
    ) -> str:
        job_id = f"batch_{int(time.time())}_{len(self.jobs)}"
        job = BatchJob(job_id, name, items, process_func, batch_size)
        self.jobs[job_id] = job
        return job_id

    def get_job(self, job_id: str) -> Optional[BatchJob]:
        return self.jobs.get(job_id)

    def run_job(self, job_id: str, use_threads: bool = True) -> Dict:
        job = self.get_job(job_id)
        if not job:
            return {"error": "Job not found"}

        job.start()

        if use_threads:
            self._run_parallel(job)
        else:
            self._run_sequential(job)

        if job.errors:
            job.fail()
        else:
            job.complete()

        return job.to_dict()

    def _run_sequential(self, job: BatchJob):
        for i, item in enumerate(job.items):
            try:
                result = job.process_func(item)
                job.results.append(result)
            except Exception as e:
                job.errors.append({"item": i, "error": str(e)})

            job.processed = i + 1
            job.progress = (job.processed / job.total) * 100

    def _run_parallel(self, job: BatchJob):
        futures = []

        for item in job.items:
            future = self.executor.submit(self._process_item, job, item)
            futures.append(future)

        for future in as_completed(futures):
            try:
                result = future.result()
                if result:
                    job.results.append(result)
            except Exception as e:
                job.errors.append({"error": str(e)})

            job.processed += 1
            job.progress = (job.processed / job.total) * 100

    def _process_item(self, job: BatchJob, item: Dict) -> Optional[Dict]:
        try:
            return job.process_func(item)
        except Exception as e:
            job.errors.append({"item": item, "error": str(e)})
            return None

    def run_classification_batch(self, emails: List[Dict], classifier) -> str:
        def process_email(email):
            result = classifier.classify(
                subject=email.get("subject", ""),
                sender=email.get("sender", ""),
                sender_email=email.get("sender_email", ""),
                body=email.get("body", "")
            )
            return {"email": email, "result": result}

        return self.create_job("Classify Emails", emails, process_email)

    def run_sync_batch(self, accounts: List[Dict], sync_func) -> str:
        def process_account(account):
            return sync_func(account)

        return self.create_job("Sync Accounts", accounts, process_account)

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        job = self.get_job(job_id)
        if job:
            return job.to_dict()
        return None

    def cancel_job(self, job_id: str) -> bool:
        job = self.get_job(job_id)
        if job and job.status == BatchStatus.RUNNING:
            job.status = BatchStatus.FAILED
            return True
        return False

    def list_jobs(self) -> List[Dict]:
        return [job.to_dict() for job in self.jobs.values()]

    def clear_completed_jobs(self):
        completed = [j for j in self.jobs.values() if j.status == BatchStatus.COMPLETED]
        for job in completed:
            del self.jobs[job.job_id]


batch_processor = BatchProcessor()


def process_email_batch(emails: List[Dict], classifier) -> str:
    return batch_processor.run_classification_batch(emails, classifier)


def get_batch_status(job_id: str) -> Optional[Dict]:
    return batch_processor.get_job_status(job_id)
