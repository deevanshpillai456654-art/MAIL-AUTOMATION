"""
System health and monitoring endpoints
"""

import logging
import os
import platform
from datetime import datetime
from typing import Dict

import psutil
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from backend import config
from backend.ai.metrics import metrics_collector
from backend.auth.local_auth import require_local_auth_or_localhost
from backend.core.production_readiness import ProductionReadinessValidator, evidence_templates
from backend.db.database import Database
from backend.runtime_version import APP_VERSION, DISPLAY_VERSION

router = APIRouter()
db = Database(config.DB_PATH)
_logger = logging.getLogger(__name__)


@router.get("/health")
async def health_v1():
    """Lightweight liveness for ``/api/v1/health`` (no dependency on DB query path)."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


def get_db_status() -> Dict:
    try:
        # Use COUNT(*) — never load all rows just to count them
        user_count    = (db.fetch_one("SELECT COUNT(*) AS n FROM users") or {}).get("n", 0)
        account_count = (db.fetch_one("SELECT COUNT(*) AS n FROM accounts") or {}).get("n", 0)
        email_count   = (db.fetch_one("SELECT COUNT(*) AS n FROM emails") or {}).get("n", 0)
        rule_count    = (db.fetch_one("SELECT COUNT(*) AS n FROM rules") or {}).get("n", 0)

        return {
            "connected": True,
            "users": user_count,
            "accounts": account_count,
            "emails": email_count,
            "rules": rule_count,
        }
    except Exception as e:
        return {"connected": False, "error": str(e)}


def get_system_status() -> Dict:
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk_root = "/"
        if os.name == "nt":
            disk_root = os.environ.get("SystemDrive", "C:") + os.sep
        disk = psutil.disk_usage(disk_root)

        return {
            "platform": platform.system(),
            "platform_version": platform.version(),
            "python_version": platform.python_version(),
            "cpu": {
                "usage_percent": cpu_percent,
                "count": psutil.cpu_count()
            },
            "memory": {
                "total_gb": round(memory.total / (1024**3), 2),
                "used_gb": round(memory.used / (1024**3), 2),
                "available_gb": round(memory.available / (1024**3), 2),
                "percent": memory.percent
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent
            }
        }
    except Exception as e:
        return {"error": str(e)}


def get_storage_info() -> Dict:
    data_dir = os.path.dirname(config.DB_PATH)
    logs_dir = config.LOG_DIR

    info = {}

    for name, path in [("data", data_dir), ("logs", logs_dir)]:
        if os.path.exists(path):
            try:
                total_size = 0
                for dirpath, dirnames, filenames in os.walk(path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        if os.path.exists(fp):
                            total_size += os.path.getsize(fp)

                info[name] = {
                    "path": path,
                    "size_bytes": total_size,
                    "size_mb": round(total_size / (1024**2), 2)
                }
            except Exception as exc:
                _logger.debug("storage walk failed for %s: %s", path, exc)

    return info


@router.get("/health/detailed", dependencies=[Depends(require_local_auth_or_localhost)])
async def detailed_health():
    db_status = get_db_status()
    system_status = get_system_status()
    storage = get_storage_info()
    metrics = metrics_collector.get_summary()

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": {
            "name": DISPLAY_VERSION,
            "version": APP_VERSION,
            "uptime": metrics.get("uptime", "unknown")
        },
        "database": db_status,
        "system": system_status,
        "storage": storage,
        "metrics": metrics
    }


@router.get("/health/components", dependencies=[Depends(require_local_auth_or_localhost)])
async def component_health():
    components = {
        "api": {"status": "up", "version": APP_VERSION},
        "database": get_db_status(),
        "classifier": {"status": "loaded", "type": "hybrid"},
        "storage": {"status": "ok" if os.path.exists(os.path.dirname(config.DB_PATH)) else "error"}
    }

    return {
        "timestamp": datetime.now().isoformat(),
        "components": components
    }


@router.get("/health/ready")
async def readiness_check():
    db_ok = False
    try:
        db.fetch_one("SELECT 1")
        db_ok = True
    except Exception:
        pass

    return {
        "ready": db_ok,
        "checks": {
            "database": db_ok
        }
    }


@router.get("/metrics/accuracy")
async def get_accuracy(days: int = 7):
    return metrics_collector.get_accuracy(days)


@router.get("/metrics/categories")
async def get_category_metrics():
    return metrics_collector.get_category_stats()


@router.get("/metrics/api")
async def get_api_metrics(days: int = 1):
    return metrics_collector.get_api_usage(days)


@router.post("/metrics/reset")
async def reset_metrics():
    metrics_collector.reset()
    return {"status": "success", "message": "Metrics reset"}


@router.get("/orchestrator/status")
async def get_orchestrator_status():
    from backend.orchestrator.self_healing_orchestrator import get_orchestrator
    orchestrator = get_orchestrator()
    return orchestrator.get_status()


@router.get("/orchestrator/dependencies")
async def get_dependency_graph():
    from backend.orchestrator.self_healing_orchestrator import get_orchestrator
    orchestrator = get_orchestrator()
    return {"dependencies": orchestrator.get_dependency_graph()}


@router.post("/orchestrator/restart/{component}")
async def restart_component(component: str):
    from backend.orchestrator.self_healing_orchestrator import get_orchestrator
    orchestrator = get_orchestrator()
    success = orchestrator.restart_component(component)
    return {"component": component, "success": success}


@router.post("/orchestrator/degrade")
async def enter_degraded_mode(reason: str):
    from backend.orchestrator.self_healing_orchestrator import get_orchestrator
    orchestrator = get_orchestrator()
    orchestrator.enter_degraded_mode(reason)
    return {"status": "entered_degraded_mode", "reason": reason}


@router.get("/orchestrator/metrics")
async def get_orchestrator_metrics():
    from backend.orchestrator.self_healing_orchestrator import get_orchestrator
    orchestrator = get_orchestrator()
    return orchestrator.get_metrics()


@router.post("/orchestrator/scale/{pool}")
async def scale_worker_pool(pool: str, workers: int):
    from backend.orchestrator.self_healing_orchestrator import get_orchestrator
    orchestrator = get_orchestrator()
    success = orchestrator.scale_worker_pool(pool, workers)
    return {"pool": pool, "workers": workers, "success": success}

@router.get("/queue/status")
async def queue_status():
    """Return job runner and scheduler status."""
    from backend.core.job_runner import get_job_runner
    from backend.scheduler.tasks import scheduler

    runner = get_job_runner()
    return {
        "job_runner": runner.status() if runner else {"running": False, "error": "not_initialized"},
        "scheduler": scheduler.get_status(),
    }


@router.get("/readiness/production")
async def production_readiness(target: int = 95):
    """Return enforceable 95/97 production-readiness gates.

    This endpoint intentionally reports `ready=false` until real provider,
    security, load, HA, and DR evidence is attached.
    """
    target = 97 if int(target) >= 97 else 95
    return ProductionReadinessValidator().evaluate(target=target)


@router.get("/readiness/evidence/templates")
async def readiness_evidence_templates():
    """Return JSON evidence templates required before claiming 95/97."""
    return {"templates": evidence_templates()}


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Expose minimal Prometheus text metrics without requiring a collector sidecar."""
    summary = metrics_collector.get_summary()
    db_status = get_db_status()
    lines = [
        "# HELP aiemail_service_up Service liveness indicator",
        "# TYPE aiemail_service_up gauge",
        "aiemail_service_up 1",
        "# HELP aiemail_database_connected Database connectivity indicator",
        "# TYPE aiemail_database_connected gauge",
        f"aiemail_database_connected {1 if db_status.get('connected') else 0}",
        "# HELP aiemail_accounts_total Connected account count",
        "# TYPE aiemail_accounts_total gauge",
        f"aiemail_accounts_total {int(db_status.get('accounts') or 0)}",
        "# HELP aiemail_emails_total Stored email count",
        "# TYPE aiemail_emails_total gauge",
        f"aiemail_emails_total {int(db_status.get('emails') or 0)}",
        "# HELP aiemail_rules_total Rule count",
        "# TYPE aiemail_rules_total gauge",
        f"aiemail_rules_total {int(db_status.get('rules') or 0)}",
    ]
    uptime = summary.get("uptime_seconds") or summary.get("uptime")
    try:
        lines.extend([
            "# HELP aiemail_uptime_seconds Runtime uptime",
            "# TYPE aiemail_uptime_seconds gauge",
            f"aiemail_uptime_seconds {float(uptime)}",
        ])
    except (TypeError, ValueError):
        pass
    return "\n".join(lines) + "\n"
