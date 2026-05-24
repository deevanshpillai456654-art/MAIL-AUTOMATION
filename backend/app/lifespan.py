import inspect
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from backend import config
from backend.api.ws_alerts import alert_manager
from backend.core.enterprise_system import EnterpriseSystem
from backend.core.runtime_control import get_runtime_control


async def start_optional_service(app_logger: logging.Logger, service_id: str, label: str, starter):
    """Start a service only when the runtime profile allows it."""
    runtime = get_runtime_control()
    if not runtime.should_autostart_service(service_id):
        app_logger.info("Skipping %s: disabled by runtime profile '%s'", label, runtime.profile)
        return {"service": service_id, "status": "skipped", "profile": runtime.profile}
    try:
        result = starter()
        if inspect.isawaitable(result):
            result = await result
        app_logger.info("%s started", label)
        return {"service": service_id, "status": "started", "result": result}
    except Exception as e:
        app_logger.warning("%s startup failed: %s", label, e)
        return {"service": service_id, "status": "failed", "error": str(e)}


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

        runtime = get_runtime_control()
        app.state.runtime_control = runtime.snapshot()
        app.state.service_startup = []
        app_logger.info(
            "Runtime profile=%s ai_mode=%s low_resource=%s max_workers=%s",
            runtime.profile,
            runtime.ai_mode,
            runtime.low_resource,
            runtime.limits.get("max_workers"),
        )

        async def _record(service_id: str, label: str, starter):
            result = await start_optional_service(app_logger, service_id, label, starter)
            app.state.service_startup.append(result)
            return result

        result = await _record(
            "enterprise_system",
            "Enterprise system",
            lambda: (setattr(app.state, "enterprise_system", EnterpriseSystem()) or app.state.enterprise_system.start()),
        )
        if result.get("status") != "started" and not hasattr(app.state, "enterprise_system"):
            app.state.enterprise_system = None

        try:
            await alert_manager.start()
            app_logger.info("Threat alert WebSocket manager started")
        except Exception as e:
            app_logger.warning("Alert manager startup failed: %s", e)

        await _record("event_bus", "Operational event bus", lambda: __import__("backend.api.event_bus", fromlist=["get_event_bus"]).get_event_bus().start())
        await _record("agents", "Autonomous operational agents", lambda: __import__("backend.api.agents", fromlist=["ensure_agents_running"]).ensure_agents_running())
        await _record("reconciler", "Operational reconciler", lambda: __import__("backend.api.reconciler", fromlist=["ensure_reconciler_running"]).ensure_reconciler_running())
        await _record("workflow_scheduler", "Workflow scheduler", lambda: __import__("backend.api.workflow_scheduler", fromlist=["ensure_scheduler_running"]).ensure_scheduler_running())
        await _record("webhooks", "Outbound webhook dispatcher", lambda: __import__("backend.api.webhooks", fromlist=["ensure_webhook_dispatcher"]).ensure_webhook_dispatcher())
        await _record("alert_rules", "Alert rules engine", lambda: __import__("backend.api.alert_rules", fromlist=["ensure_alert_rules_running"]).ensure_alert_rules_running())
        await _record("notifications", "Notification center", lambda: __import__("backend.api.notifications", fromlist=["ensure_notification_center"]).ensure_notification_center())
        await _record("metric_snapshots", "Metric snapshot recorder", lambda: __import__("backend.api.metric_snapshots", fromlist=["ensure_metric_recorder_running"]).ensure_metric_recorder_running())
        await _record("audit_log", "Audit log", lambda: __import__("backend.api.audit_log", fromlist=["ensure_audit_log_running"]).ensure_audit_log_running())
        await _record("incidents", "Incident manager", lambda: __import__("backend.api.incidents", fromlist=["ensure_incident_manager_running"]).ensure_incident_manager_running())
        await _record("scheduled_reports", "Report scheduler", lambda: __import__("backend.api.scheduled_reports", fromlist=["ensure_report_scheduler_running"]).ensure_report_scheduler_running())
        await _record("playbooks", "Playbooks engine", lambda: __import__("backend.api.playbooks", fromlist=["ensure_playbooks_running"]).ensure_playbooks_running())
        await _record("sla", "SLA checker", lambda: __import__("backend.api.sla", fromlist=["ensure_sla_running"]).ensure_sla_running())
        await _record("maintenance", "Maintenance checker", lambda: __import__("backend.api.maintenance", fromlist=["ensure_maintenance_running"]).ensure_maintenance_running())
        await _record("oncall", "On-call escalation engine", lambda: __import__("backend.api.oncall", fromlist=["ensure_oncall_running"]).ensure_oncall_running())

        try:
            from backend.api.event_bus import get_event_bus
            from backend.api.workflows import trigger_workflow_by_template

            async def _on_threat_detected(event: dict) -> None:
                sev = event.get("severity", "low")
                if sev in ("high", "critical"):
                    await trigger_workflow_by_template(
                        "threat_escalation",
                        input_data=event.get("payload", {}),
                        trigger_type="event",
                    )

            async def _on_email_received(event: dict) -> None:
                await trigger_workflow_by_template(
                    "smart_inbox_organizer",
                    input_data=event.get("payload", {}),
                    trigger_type="event",
                )

            bus = get_event_bus()
            bus.subscribe("threat.detected",  _on_threat_detected)
            bus.subscribe("email.received",    _on_email_received)
            # Record subscriptions so shutdown can drop them (prevents closure
            # leak if the bus is restarted in-process — e.g. test fixtures).
            app.state.event_bus_subscriptions = [
                ("threat.detected", _on_threat_detected),
                ("email.received", _on_email_received),
            ]
            app_logger.info("Event-driven workflow activation subscriptions registered")
        except Exception as e:
            app_logger.warning("Event-driven workflow activation setup failed: %s", e)

        async def _start_system_scheduler():
            from backend.scheduler.tasks import scheduler
            scheduler.set_enterprise_system(app.state.enterprise_system)
            scheduler.start()

        await _record("system_scheduler", "Scheduler", _start_system_scheduler)

        async def _start_job_runner():
            from backend.core.job_runner import init_job_runner
            from backend.core.persistent_job_queue import PersistentJobQueue
            job_queue = PersistentJobQueue(Path(config.DATA_DIR) / "job_queue.db")
            job_runner = init_job_runner(
                job_queue,
                concurrency=runtime.limits.get("job_concurrency", 1),
                poll_interval=float(runtime.limits.get("poll_interval_seconds", 5)),
            )
            await job_runner.start()
            app.state.job_runner = job_runner

        await _record("job_runner", "Async job runner", _start_job_runner)

        yield

        app_logger.info("Shutting down AI Email Organizer")
        try:
            await alert_manager.stop()
        except Exception as e:
            app_logger.warning("Alert manager shutdown failed: %s", e)

        try:
            from backend.api.agents import get_supervisor
            await get_supervisor().stop_all()
        except Exception as e:
            app_logger.warning("Agent supervisor shutdown failed: %s", e)

        try:
            from backend.api.reconciler import get_reconciler
            await get_reconciler().stop()
        except Exception as e:
            app_logger.warning("Reconciler shutdown failed: %s", e)

        try:
            from backend.api.workflow_scheduler import get_workflow_scheduler
            await get_workflow_scheduler().stop()
        except Exception as e:
            app_logger.warning("Workflow scheduler shutdown failed: %s", e)

        try:
            from backend.api.event_bus import get_event_bus
            bus = get_event_bus()
            for event_type, callback in getattr(app.state, "event_bus_subscriptions", []) or []:
                try:
                    bus.unsubscribe(event_type, callback)
                except Exception:
                    pass
            await bus.stop()
        except Exception as e:
            app_logger.warning("Event bus shutdown failed: %s", e)

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
