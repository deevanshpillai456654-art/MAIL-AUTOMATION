"""
Scheduler API endpoints
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth.local_auth import require_local_auth_or_localhost
from backend.core.runtime_control import get_runtime_control
from backend.scheduler.tasks import TaskFrequency, scheduler

router = APIRouter()

_auth = Depends(require_local_auth_or_localhost)


class TaskInput(BaseModel):
    task_id: Optional[str] = None
    name: str
    frequency: str
    interval_hours: int = 1
    enabled: bool = True


@router.get("/scheduler/status", dependencies=[_auth])
async def get_scheduler_status():
    return scheduler.get_status()


@router.post("/scheduler/start", dependencies=[_auth])
async def start_scheduler():
    if not get_runtime_control().is_service_enabled("system_scheduler"):
        return {"status": "disabled", "message": "Scheduler disabled by runtime policy"}
    if not scheduler.running:
        scheduler.start()
        return {"status": "success", "message": "Scheduler started"}
    return {"status": "success", "message": "Scheduler already running"}


@router.post("/scheduler/stop", dependencies=[_auth])
async def stop_scheduler():
    if scheduler.running:
        scheduler.stop()
        return {"status": "success", "message": "Scheduler stopped"}
    return {"status": "success", "message": "Scheduler not running"}


@router.post("/scheduler/tasks", dependencies=[_auth])
async def create_task(task: TaskInput):
    from fastapi import HTTPException

    from backend.scheduler.tasks import Task

    try:
        frequency = TaskFrequency(task.frequency)
    except ValueError:
        valid = [f.value for f in TaskFrequency]
        raise HTTPException(status_code=422, detail=f"Invalid frequency '{task.frequency}'. Must be one of: {valid}")

    new_task = Task(
        task_id=task.task_id,
        name=task.name,
        func=lambda: print(f"Task {task.name} executed"),
        frequency=frequency,
        interval_hours=task.interval_hours,
        enabled=task.enabled
    )

    scheduler.add_task(new_task)
    return {"status": "success", "message": f"Task {task.name} created"}


@router.post("/scheduler/tasks/{task_id}/toggle", dependencies=[_auth])
async def toggle_task(task_id: str):
    task = scheduler.get_task(task_id)
    if task:
        task.enabled = not task.enabled
        return {"status": "success", "message": f"Task is now {'enabled' if task.enabled else 'disabled'}"}
    return {"status": "error", "message": "Task not found"}


@router.delete("/scheduler/tasks/{task_id}", dependencies=[_auth])
async def delete_task(task_id: str):
    scheduler.remove_task(task_id)
    return {"status": "success", "message": f"Task {task_id} deleted"}


@router.get("/scheduler/tasks", dependencies=[_auth])
async def list_tasks():
    status = scheduler.get_status()
    return {"tasks": status.get("tasks", []), "total": status.get("total_tasks", 0)}
