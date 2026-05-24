"""
Scheduled tasks for AI Email Organizer
"""

import json
import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

from backend import config
from backend.core.enterprise_system import EnterpriseSystem
from backend.db.database import Database

ALLOWED_SYNC_INTERVAL_SECONDS = {20, 30, 60}
DEFAULT_SYNC_INTERVAL_SECONDS = 30


class TaskFrequency(str, Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class Task:
    def __init__(
        self,
        task_id: str,
        name: str,
        func: Callable,
        frequency: TaskFrequency,
        interval_hours: int = 1,
        interval_seconds: int = None,
        enabled: bool = True
    ):
        self.task_id = task_id
        self.name = name
        self.func = func
        self.frequency = frequency
        self.interval_hours = interval_hours
        self.interval_seconds = int(interval_seconds) if interval_seconds else None
        self.enabled = enabled
        self.last_run = None
        self.next_run = None
        self.run_count = 0

    def should_run(self) -> bool:
        if not self.enabled:
            return False

        if self.next_run is None:
            return True

        return datetime.now() >= self.next_run

    def execute(self):
        try:
            self.func()
            self.last_run = datetime.now()
            self.run_count += 1
            self._calculate_next_run()
        except Exception as e:
            logger.error("Task %s failed: %s", self.name, e)

    def _calculate_next_run(self):
        now = datetime.now()
        if self.interval_seconds:
            self.next_run = now + timedelta(seconds=self.interval_seconds)
            return

        if self.frequency == TaskFrequency.HOURLY:
            self.next_run = now + timedelta(hours=self.interval_hours)
        elif self.frequency == TaskFrequency.DAILY:
            self.next_run = now + timedelta(days=1)
        elif self.frequency == TaskFrequency.WEEKLY:
            self.next_run = now + timedelta(weeks=1)
        elif self.frequency == TaskFrequency.MONTHLY:
            self.next_run = now + timedelta(days=30)


class Scheduler:
    def __init__(self, max_workers: int = 4):
        self.tasks: List[Task] = []
        self.running = False
        self.thread = None
        self.enterprise_system: Optional[EnterpriseSystem] = None
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._active_futures: Dict[str, Future] = {}

    def set_enterprise_system(self, enterprise_system: EnterpriseSystem):
        self.enterprise_system = enterprise_system

    def add_task(self, task: Task):
        task._calculate_next_run()
        self.tasks.append(task)

    def remove_task(self, task_id: str):
        self.tasks = [t for t in self.tasks if t.task_id != task_id]

    def get_task(self, task_id: str) -> Task:
        for task in self.tasks:
            if task.task_id == task_id:
                return task
        return None

    def enable_task(self, task_id: str):
        task = self.get_task(task_id)
        if task:
            task.enabled = True

    def disable_task(self, task_id: str):
        task = self.get_task(task_id)
        if task:
            task.enabled = False

    def start(self):
        if self.running:
            return

        self.running = True
        self._executor = ThreadPoolExecutor(
            max_workers=self._max_workers,
            thread_name_prefix="scheduler_task",
        )
        self.thread = threading.Thread(target=self._run_loop, daemon=True, name="scheduler_loop")
        self.thread.start()

    def stop(self):
        self.running = False
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None

    def _run_loop(self):
        """Poll tasks every second and dispatch ready ones to the thread pool.

        A task that is already running (its Future is not done) is skipped until
        it completes, preventing concurrent duplicate executions of the same task.
        """
        while self.running:
            for task in list(self.tasks):
                tid = task.task_id
                active = self._active_futures.get(tid)
                if active and not active.done():
                    continue  # still running — skip

                if task.should_run() and self._executor:
                    # Mark next_run immediately so the task is not re-fired
                    # while still in the executor queue
                    task._calculate_next_run()
                    future = self._executor.submit(task.execute)
                    self._active_futures[tid] = future

            # Clean up completed futures to prevent dict growth
            done_ids = [tid for tid, f in self._active_futures.items() if f.done()]
            for tid in done_ids:
                del self._active_futures[tid]

            time.sleep(1)

    def get_status(self) -> Dict:
        return {
            "running": self.running,
            "total_tasks": len(self.tasks),
            "enabled_tasks": sum(1 for t in self.tasks if t.enabled),
            "tasks": [
                {
                    "id": t.task_id,
                    "name": t.name,
                    "frequency": t.frequency.value,
                    "interval_seconds": t.interval_seconds,
                    "enabled": t.enabled,
                    "last_run": t.last_run.isoformat() if t.last_run else None,
                    "next_run": t.next_run.isoformat() if t.next_run else None,
                    "run_count": t.run_count
                }
                for t in self.tasks
            ]
        }


enterprise_system: Optional[EnterpriseSystem] = None


def set_enterprise_system(system: EnterpriseSystem):
    global enterprise_system
    enterprise_system = system


def _local_settings() -> Dict:
    try:
        db = Database(config.DB_PATH)
        user = db.fetch_one("SELECT settings FROM users WHERE email = ? ORDER BY id LIMIT 1", ("local@aiemailorganizer.local",))
        if user and user.get("settings"):
            return json.loads(user["settings"])
    except Exception:
        return {}
    return {}


def sync_emails_task():
    """Sync emails from connected accounts"""
    settings = _local_settings()
    if settings.get("auto_sync") is False:
        logger.info("Auto sync is disabled in settings; skipping scheduled sync.")
        return
    logger.info("Running email sync task")
    active_system = scheduler.enterprise_system or enterprise_system
    if not active_system:
        logger.info("Enterprise system is not configured; skipping scheduled sync.")
        return

    db = Database(config.DB_PATH)
    accounts = db.get_all_accounts()
    total_queued = 0
    total_skipped = 0

    for account in accounts:
        if account.get("status") == "paused":
            total_skipped += 1
            continue

        sync_id = db.add_sync_status(account["id"], "pending")
        queued = active_system.queue_provider_sync(
            account["id"],
            account["provider"],
            50,
            sync_id,
            metadata={"source": "scheduled", "task": "sync_emails"}
        )

        if queued:
            total_queued += 1
        else:
            total_skipped += 1
            logger.warning("Unable to queue sync for account %s provider %s", account['id'], account['provider'])

    logger.info("Scheduled sync queue finished: queued=%d, skipped=%d", total_queued, total_skipped)


def cleanup_old_emails_task():
    """Clean up old processed emails"""
    logger.info("Running email cleanup task")


def generate_metrics_task():
    """Generate daily metrics"""
    logger.info("Generating metrics")


def check_rules_task():
    """Check and apply rules"""
    logger.info("Checking rules")


def db_maintenance_task():
    """Prune stale DB rows and checkpoint WAL files."""
    from pathlib import Path

    from backend.core.db_maintenance import prune_app_db, prune_job_queue, run_wal_checkpoint

    job_queue_path = Path(config.DATA_DIR) / "job_queue.db"
    pruned_jobs = prune_job_queue(job_queue_path)
    pruned_app  = prune_app_db(config.DB_PATH)
    run_wal_checkpoint([config.DB_PATH, str(job_queue_path)])

    total_pruned = pruned_jobs + sum(pruned_app.values())
    if total_pruned:
        logger.info("DB maintenance: pruned %d rows total", total_pruned)


def ai_state_backup_task():
    """Create a scheduled backup of ONNX registry, learning memory, and healing logs."""
    from backend.ai.onnx_control_plane import get_onnx_control_plane

    result = get_onnx_control_plane().run_scheduled_ai_state_backup()
    logger.info("AI state backup task: %s %s", result.get('status'), result.get('reason', ''))


scheduler = Scheduler()

scheduler.add_task(Task(
    task_id="sync_emails",
    name="Email Sync",
    func=sync_emails_task,
    frequency=TaskFrequency.HOURLY,
    interval_hours=1,
    interval_seconds=DEFAULT_SYNC_INTERVAL_SECONDS,
    enabled=True
))

scheduler.add_task(Task(
    task_id="cleanup_emails",
    name="Email Cleanup",
    func=cleanup_old_emails_task,
    frequency=TaskFrequency.DAILY,
    interval_hours=24,
    enabled=False
))

scheduler.add_task(Task(
    task_id="generate_metrics",
    name="Metrics Generation",
    func=generate_metrics_task,
    frequency=TaskFrequency.DAILY,
    interval_hours=24,
    enabled=True
))

scheduler.add_task(Task(
    task_id="check_rules",
    name="Rule Engine",
    func=check_rules_task,
    frequency=TaskFrequency.HOURLY,
    interval_hours=1,
    enabled=True
))

scheduler.add_task(Task(
    task_id="db_maintenance",
    name="DB Maintenance",
    func=db_maintenance_task,
    frequency=TaskFrequency.DAILY,
    interval_hours=24,
    enabled=True
))

scheduler.add_task(Task(
    task_id="ai_state_backup",
    name="AI State Backup",
    func=ai_state_backup_task,
    frequency=TaskFrequency.DAILY,
    interval_hours=24,
    enabled=True
))

def set_sync_interval(seconds: int) -> int:
    seconds = int(seconds or DEFAULT_SYNC_INTERVAL_SECONDS)
    if seconds not in ALLOWED_SYNC_INTERVAL_SECONDS:
        seconds = DEFAULT_SYNC_INTERVAL_SECONDS
    task = scheduler.get_task("sync_emails")
    if task:
        task.interval_seconds = seconds
        task._calculate_next_run()
    return seconds


def set_sync_enabled(enabled: bool) -> bool:
    task = scheduler.get_task("sync_emails")
    if task:
        task.enabled = bool(enabled)
        if task.enabled:
            task._calculate_next_run()
    return bool(enabled)


def get_sync_interval_seconds() -> int:
    task = scheduler.get_task("sync_emails")
    return int(task.interval_seconds or DEFAULT_SYNC_INTERVAL_SECONDS) if task else DEFAULT_SYNC_INTERVAL_SECONDS
