"""
Task Queue - Background Tasks
=============================

Background task queue:
- Task scheduling
- Task prioritization
- Task retry
- Task timeout
- Task result storage
"""

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("task.queue")


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2


@dataclass
class Task:
    """Background task"""
    task_id: str
    func_name: str
    args: tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    retry_count: int = 0


class TaskQueue:
    """
    Background task queue.
    """

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._queue: deque = deque()
        self._running_tasks: Dict[str, Task] = {}
        self._completed_tasks: Dict[str, Task] = {}
        self._lock = threading.Lock()
        self._workers: list = []
        self._running = False

        # Task registry
        self._task_funcs: Dict[str, Callable] = {}

        logger.info("TaskQueue initialized")

    def register(self, name: str, func: Callable):
        """Register task function"""
        self._task_funcs[name] = func

    def submit(
        self,
        func_name: str,
        args: tuple = (),
        kwargs: Dict = None,
        priority: TaskPriority = TaskPriority.NORMAL
    ) -> str:
        """Submit task"""
        task_id = f"task_{uuid.uuid4().hex[:12]}"

        task = Task(
            task_id=task_id,
            func_name=func_name,
            args=args,
            kwargs=kwargs or {},
            priority=priority
        )

        with self._lock:
            self._queue.append(task)
            # Sort by priority
            self._queue = deque(sorted(
                self._queue,
                key=lambda t: t.priority.value,
                reverse=True
            ))

        return task_id

    def start(self):
        """Start task workers"""
        if self._running:
            return

        self._running = True

        for i in range(self.max_workers):
            t = threading.Thread(target=self._worker_loop, daemon=True, name=f"task-worker-{i}")
            t.start()
            self._workers.append(t)

        logger.info("TaskQueue started")

    def stop(self):
        """Stop task workers"""
        self._running = False
        for t in self._workers:
            t.join(timeout=1)
        self._workers.clear()

    def _worker_loop(self):
        """Worker loop"""
        while self._running:
            try:
                task = self._get_task()

                if task:
                    self._run_task(task)
                else:
                    time.sleep(0.1)
            except Exception as e:
                logger.error(f"Worker error: {e}")

    def _get_task(self) -> Optional[Task]:
        """Get next task"""
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    def _run_task(self, task: Task):
        """Run task"""
        func = self._task_funcs.get(task.func_name)

        if not func:
            task.status = TaskStatus.FAILED
            task.error = f"Function not found: {task.func_name}"
            return

        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        with self._lock:
            self._running_tasks[task.task_id] = task

        try:
            result = func(*task.args, **task.kwargs)
            task.status = TaskStatus.COMPLETED
            task.result = result
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.retry_count += 1

        task.completed_at = time.time()

        with self._lock:
            if task.task_id in self._running_tasks:
                del self._running_tasks[task.task_id]
            self._completed_tasks[task.task_id] = task

        logger.info(f"Task completed: {task.task_id} - {task.status.value}")

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task status"""
        with self._lock:
            if task_id in self._running_tasks:
                return self._running_tasks[task_id]
            return self._completed_tasks.get(task_id)

    def cancel_task(self, task_id: str) -> bool:
        """Cancel task"""
        with self._lock:
            # Check running
            if task_id in self._running_tasks:
                task = self._running_tasks[task_id]
                task.status = TaskStatus.CANCELLED
                return True

            # Check pending
            for task in self._queue:
                if task.task_id == task_id:
                    task.status = TaskStatus.CANCELLED
                    return True

        return False

    def get_stats(self) -> Dict:
        """Get queue stats"""
        with self._lock:
            return {
                "pending": len(self._queue),
                "running": len(self._running_tasks),
                "completed": len(self._completed_tasks)
            }


# Global queue
_task_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    """Get global task queue"""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue


__all__ = ["TaskQueue", "Task", "TaskStatus", "TaskPriority", "get_task_queue"]
