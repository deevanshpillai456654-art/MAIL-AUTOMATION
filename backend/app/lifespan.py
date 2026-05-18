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
            from backend.api.event_bus import get_event_bus
            await get_event_bus().start()
            app_logger.info("Operational event bus started")
        except Exception as e:
            app_logger.warning("Event bus startup failed: %s", e)

        try:
            from backend.api.agents import ensure_agents_running
            await ensure_agents_running()
            app_logger.info("Autonomous operational agents started")
        except Exception as e:
            app_logger.warning("Agent supervisor startup failed: %s", e)

        try:
            from backend.api.reconciler import ensure_reconciler_running
            await ensure_reconciler_running()
            app_logger.info("Operational reconciler started")
        except Exception as e:
            app_logger.warning("Reconciler startup failed: %s", e)

        try:
            from backend.api.workflow_scheduler import ensure_scheduler_running
            await ensure_scheduler_running()
            app_logger.info("Workflow scheduler started")
        except Exception as e:
            app_logger.warning("Workflow scheduler startup failed: %s", e)

        try:
            from backend.api.webhooks import ensure_webhook_dispatcher
            ensure_webhook_dispatcher()
            app_logger.info("Outbound webhook dispatcher started")
        except Exception as e:
            app_logger.warning("Webhook dispatcher startup failed: %s", e)

        try:
            from backend.api.alert_rules import ensure_alert_rules_running
            await ensure_alert_rules_running()
            app_logger.info("Alert rules engine started")
        except Exception as e:
            app_logger.warning("Alert rules engine startup failed: %s", e)

        try:
            from backend.api.notifications import ensure_notification_center
            ensure_notification_center()
            app_logger.info("Notification center started")
        except Exception as e:
            app_logger.warning("Notification center startup failed: %s", e)

        try:
            from backend.api.metric_snapshots import ensure_metric_recorder_running
            await ensure_metric_recorder_running()
            app_logger.info("Metric snapshot recorder started")
        except Exception as e:
            app_logger.warning("Metric snapshot recorder startup failed: %s", e)

        try:
            from backend.api.audit_log import ensure_audit_log_running
            ensure_audit_log_running()
            app_logger.info("Audit log started")
        except Exception as e:
            app_logger.warning("Audit log startup failed: %s", e)

        try:
            from backend.api.incidents import ensure_incident_manager_running
            ensure_incident_manager_running()
            app_logger.info("Incident manager started")
        except Exception as e:
            app_logger.warning("Incident manager startup failed: %s", e)

        try:
            from backend.api.scheduled_reports import ensure_report_scheduler_running
            await ensure_report_scheduler_running()
            app_logger.info("Report scheduler started")
        except Exception as e:
            app_logger.warning("Report scheduler startup failed: %s", e)

        try:
            from backend.api.playbooks import ensure_playbooks_running
            ensure_playbooks_running()
            app_logger.info("Playbooks engine started")
        except Exception as e:
            app_logger.warning("Playbooks engine startup failed: %s", e)

        try:
            from backend.api.sla import ensure_sla_running
            await ensure_sla_running()
            app_logger.info("SLA checker started")
        except Exception as e:
            app_logger.warning("SLA checker startup failed: %s", e)

        try:
            from backend.api.maintenance import ensure_maintenance_running
            await ensure_maintenance_running()
            app_logger.info("Maintenance checker started")
        except Exception as e:
            app_logger.warning("Maintenance checker startup failed: %s", e)

        try:
            from backend.api.oncall import ensure_oncall_running
            await ensure_oncall_running()
            app_logger.info("On-call escalation engine started")
        except Exception as e:
            app_logger.warning("On-call engine startup failed: %s", e)

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
            app_logger.info("Event-driven workflow activation subscriptions registered")
        except Exception as e:
            app_logger.warning("Event-driven workflow activation setup failed: %s", e)

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
            await get_event_bus().stop()
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
