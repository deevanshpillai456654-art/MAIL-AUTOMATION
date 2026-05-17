import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from backend import config
from backend.api.ws_alerts import alert_manager
from backend.core.enterprise_system import EnterpriseSystem


def create_lifespan(project_root: Path, logger: logging.Logger | None = None):
    app_logger = logger or logging.getLogger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            from backend.utils.port_manager import discovery
            discovery.write_discovery(config.API_PORT, config.API_HOST)
        except Exception as e:
            app_logger.warning("Service discovery issue: %s", e)

        app_logger.info("Starting AI Email Organizer on %s:%s", config.API_HOST, config.API_PORT)
        os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
        try:
            from backend.auth.local_auth import get_local_token
            get_local_token()
        except Exception as e:
            app_logger.warning("Local API token bootstrap failed: %s", e)

        try:
            from backend.core.offline_first_run import initialize_offline_first_run
            offline_report = initialize_offline_first_run(Path(config.RUNTIME_HOME), project_root)
            app.state.offline_first_run = offline_report
        except Exception as e:
            app_logger.warning("Offline first-run bootstrap failed: %s", e)

        try:
            app.state.enterprise_system = EnterpriseSystem()
            app.state.enterprise_system.start()
            app_logger.info("Enterprise system initialized")
        except Exception as e:
            app_logger.warning("Enterprise system initialization failed: %s", e)

        try:
            await alert_manager.start()
            app_logger.info("Threat alert WebSocket manager started")
        except Exception as e:
            app_logger.warning("Alert manager startup failed: %s", e)

        try:
            from backend.scheduler.tasks import scheduler
            scheduler.set_enterprise_system(app.state.enterprise_system)
            scheduler.start()
            app_logger.info("Scheduler started")
        except Exception as e:
            app_logger.warning("Scheduler not started: %s", e)

        try:
            from backend.core.persistent_job_queue import PersistentJobQueue
            from backend.core.job_runner import init_job_runner
            job_queue = PersistentJobQueue(Path(config.DATA_DIR) / "job_queue.db")
            job_runner = init_job_runner(job_queue, concurrency=4, poll_interval=2.0)
            await job_runner.start()
            app.state.job_runner = job_runner
            app_logger.info("Async job runner started")
        except Exception as e:
            app_logger.warning("Job runner not started: %s", e)

        yield

        app_logger.info("Shutting down AI Email Organizer")
        try:
            await alert_manager.stop()
        except Exception as e:
            app_logger.warning("Alert manager shutdown failed: %s", e)

        enterprise_system = getattr(app.state, "enterprise_system", None)
        if enterprise_system:
            try:
                enterprise_system.shutdown()
            except Exception as e:
                app_logger.warning("Enterprise system shutdown failed: %s", e)

        try:
            from backend.db.database import Database
            Database.close_all_instances()
        except Exception as e:
            app_logger.warning("Database shutdown failed: %s", e)

        try:
            from backend.utils.sqlite_connection_guard import close_all_tracked_connections
            close_all_tracked_connections()
        except Exception as e:
            app_logger.warning("SQLite cleanup failed: %s", e)

        try:
            runner = getattr(app.state, "job_runner", None)
            if runner:
                await runner.stop()
        except Exception as e:
            app_logger.warning("Job runner shutdown failed: %s", e)

        try:
            from backend.core.async_http import close_http_client
            await close_http_client()
        except Exception as e:
            app_logger.warning("Async HTTP client shutdown failed: %s", e)

    return lifespan


__all__ = ["create_lifespan"]
