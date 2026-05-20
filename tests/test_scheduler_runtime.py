"""Runtime policy tests for backend/api/scheduler.py."""
from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_start_scheduler_honors_runtime_service_toggle(monkeypatch):
    monkeypatch.setenv("AIO_SERVICE_SYSTEM_SCHEDULER", "false")
    from backend.api import scheduler as scheduler_api

    class FakeScheduler:
        def __init__(self):
            self.running = False
            self.started = False

        def start(self):
            self.started = True
            self.running = True

        def get_status(self):
            return {"running": self.running, "total_tasks": 0, "enabled_tasks": 0}

    fake = FakeScheduler()
    monkeypatch.setattr(scheduler_api, "scheduler", fake)

    app = FastAPI()
    app.include_router(scheduler_api.router, prefix="/api/v1")
    client = TestClient(app)

    response = client.post("/api/v1/scheduler/start")

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert fake.started is False
    assert fake.running is False
