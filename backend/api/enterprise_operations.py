"""Enterprise operations control-plane API."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend import config
from backend.auth.local_auth import require_local_auth
from backend.core.enterprise_operations import EnterpriseOperationsCenter

router = APIRouter(
    prefix="/enterprise-operations",
    tags=["enterprise-operations"],
    dependencies=[Depends(require_local_auth)],
)


class ServiceControls(BaseModel):
    enabled: Optional[bool] = None
    auto_start: Optional[bool] = None


class ServiceFailure(BaseModel):
    error: str = Field(..., max_length=2000)


class QueueCleanup(BaseModel):
    max_age_seconds: int = 86400


def _center(request: Request) -> EnterpriseOperationsCenter:
    paths = getattr(request.app.state, "enterprise_operations_paths", {}) or {}
    return EnterpriseOperationsCenter(
        project_root=Path(paths.get("project_root") or config.APP_DIR),
        data_dir=Path(paths.get("data_dir") or config.DATA_DIR),
        log_dir=Path(paths.get("log_dir") or config.LOG_DIR),
        app_state=request.app.state,
    )


@router.get("/overview")
async def overview(request: Request):
    return _center(request).overview()


@router.get("/services")
async def services(request: Request):
    return _center(request).services()


@router.post("/services/{service_id}/controls")
async def set_service_controls(service_id: str, body: ServiceControls, request: Request):
    return _center(request).set_service_controls(
        service_id,
        enabled=body.enabled,
        auto_start=body.auto_start,
    )


@router.post("/services/{service_id}/failure")
async def record_service_failure(service_id: str, body: ServiceFailure, request: Request):
    return _center(request).record_service_failure(service_id, body.error)


@router.post("/services/{service_id}/failures/reset")
async def reset_service_failures(service_id: str, request: Request):
    return _center(request).reset_service_failures(service_id)


@router.post("/services/{service_id}/restart")
async def restart_service(service_id: str, request: Request):
    return _center(request).restart_service(service_id)


@router.get("/queues")
async def queues(request: Request):
    return _center(request).queue_report()


@router.get("/queues/backend")
async def queue_backend(request: Request):
    return _center(request).queue_backend_diagnostics()


@router.post("/queues/recover")
async def recover_queues(request: Request):
    return _center(request).recover_queues()


@router.post("/queues/cleanup")
async def cleanup_queues(body: QueueCleanup, request: Request):
    return _center(request).cleanup_queues(max_age_seconds=body.max_age_seconds)


@router.get("/deployment/validate")
async def deployment_validate(request: Request):
    return _center(request).deployment_validation()


@router.get("/deployment/profiles")
async def deployment_profiles(request: Request):
    return {"profiles": _center(request).deployment_profiles()}


@router.post("/deployment/profiles/{profile}/template")
async def write_deployment_template(profile: str, request: Request):
    return _center(request).write_deployment_template(profile)


@router.get("/updates/diagnostics")
async def update_diagnostics(request: Request):
    return _center(request).update_diagnostics()


@router.get("/observability")
async def observability(request: Request):
    return _center(request).observability()


@router.get("/database")
async def database(request: Request):
    return _center(request).database_diagnostics()


@router.get("/security")
async def security(request: Request):
    return _center(request).security_posture()


@router.get("/electron")
async def electron(request: Request):
    return _center(request).electron_diagnostics()


@router.get("/resources")
async def resources(request: Request):
    return _center(request).resource_pressure()


@router.get("/connectors")
async def connectors(request: Request):
    return _center(request).connector_inventory()


@router.get("/agents")
async def agents(request: Request):
    return _center(request).agent_runtime_diagnostics()


@router.get("/agents/runtime")
async def agent_runtime(request: Request):
    return _center(request).agent_runtime_diagnostics()


@router.get("/sync/transport")
async def sync_transport(request: Request):
    return _center(request).sync_transport_diagnostics()


@router.get("/production/readiness")
async def production_readiness(request: Request):
    return _center(request).production_readiness_gates()


@router.get("/production/provisioning-pack/{profile}")
async def provisioning_pack(profile: str, request: Request):
    return _center(request).provisioning_pack(profile)


@router.post("/production/provisioning-pack/{profile}")
async def write_provisioning_pack(profile: str, request: Request):
    return _center(request).write_provisioning_pack(profile)


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request):
    return PlainTextResponse(_center(request).operations_metrics_text(), media_type="text/plain; version=0.0.4")


@router.get("/reports")
async def reports(request: Request):
    return {"reports": _center(request).build_reports()}


@router.post("/support/bundle")
async def support_bundle(request: Request):
    return _center(request).create_support_bundle()


__all__ = ["router"]
