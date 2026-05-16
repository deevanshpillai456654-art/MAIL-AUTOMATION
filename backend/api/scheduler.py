"""
Scheduler API endpoints
"""

import uuid
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from backend.scheduler.tasks import scheduler, TaskFrequency

router = APIRouter()


class TaskInput(BaseModel):
    task_id: Optional[str] = None
    name: str
    frequency: str
    interval_hours: int = 1
    enabled: bool = True


@router.get("/scheduler/status")
async def get_scheduler_status():
    return scheduler.get_status()


@router.post("/scheduler/start")
async def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        return {"status": "success", "message": "Scheduler started"}
    return {"status": "success", "message": "Scheduler already running"}


@router.post("/scheduler/stop")
async def stop_scheduler():
    if scheduler.running:
        scheduler.stop()
        return {"status": "success", "message": "Scheduler stopped"}
    return {"status": "success", "message": "Scheduler not running"}


@router.post("/scheduler/tasks")
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


@router.post("/scheduler/tasks/{task_id}/toggle")
async def toggle_task(task_id: str):
    task = scheduler.get_task(task_id)
    if task:
        task.enabled = not task.enabled
        return {"status": "success", "message": f"Task is now {'enabled' if task.enabled else 'disabled'}"}
    return {"status": "error", "message": "Task not found"}


@router.delete("/scheduler/tasks/{task_id}")
async def delete_task(task_id: str):
    scheduler.remove_task(task_id)
    return {"status": "success", "message": f"Task {task_id} deleted"}


@router.get("/scheduler/tasks")
async def list_tasks():
    status = scheduler.get_status()
    return {"tasks": status.get("tasks", []), "total": status.get("total_tasks", 0)}