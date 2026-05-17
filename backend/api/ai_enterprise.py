"""AIEmailOrganizer v9.7 local-first enterprise AI API."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.ai.local_first import (
    WorkflowEngine,
    WorkflowStep,
    get_agent_orchestrator,
    get_execution_queue,
    get_governance_engine,
    get_runtime,
    get_semantic_store,
    get_workflow_engine,
    get_ai_cache,
    get_ai_telemetry,
    get_indexing_worker,
    get_nlp_pipeline,
    get_vector_db,
)
from backend.ai.onnx_control_plane import get_onnx_control_plane
from backend.auth.local_auth import request_has_valid_local_auth
from backend.runtime_version import APP_VERSION, DISPLAY_VERSION, VERSION_INFO

router = APIRouter()


def _model_to_dict(model: BaseModel) -> Dict[str, Any]:
    dumper = getattr(model, "model_dump", None)
    if callable(dumper):
        return dumper()
    return model.dict()


def _request_has_ai_admin(request: Request, permission: str) -> bool:
    return request_has_valid_local_auth(request)


def _require_ai_admin(request: Request, permission: str) -> None:
    if not _request_has_ai_admin(request, permission):
        raise HTTPException(status_code=401, detail="Authentication required")


class InferRequest(BaseModel):
    task: str = Field(default="classify_email", max_length=80)
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=5, ge=1, le=10)
    run_async: bool = False


class MemoryUpsertRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=50000)
    namespace: str = Field(default="emails", max_length=80)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    record_id: Optional[str] = None


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    namespace: Optional[str] = Field(default=None, max_length=80)
    top_k: int = Field(default=10, ge=1, le=50)


class AgentRunRequest(BaseModel):
    agent: str = Field(default="email", max_length=80)
    task: str = Field(default="classify_email", max_length=80)
    payload: Dict[str, Any] = Field(default_factory=dict)


class WorkflowRequest(BaseModel):
    name: str = Field(default="workflow", max_length=120)
    steps: List[Dict[str, Any]] = Field(default_factory=list)


class TextPayloadRequest(BaseModel):
    subject: str = Field(default="", max_length=1000)
    sender: str = Field(default="", max_length=500)
    sender_email: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=50000)
    text: str = Field(default="", max_length=50000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LearningFeedbackRequest(BaseModel):
    sender: str = Field(default="", max_length=500)
    sender_email: str = Field(default="", max_length=500)
    predicted_category: str = Field(default="", max_length=120)
    actual_category: str = Field(default="", max_length=120)
    priority: str = Field(default="Medium", max_length=80)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    scope: str = Field(default="sender", max_length=40)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LearningImportRequest(BaseModel):
    schema_version: int = Field(default=1)
    replace: bool = False
    overrides: Dict[str, Any] = Field(default_factory=dict)
    corrections: List[Dict[str, Any]] = Field(default_factory=list)
    stats: Dict[str, Any] = Field(default_factory=dict)


class ModelValidationRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=240)


class ModelEvaluationRequest(BaseModel):
    model_name: str = Field(..., min_length=1, max_length=240)
    cases: List[Dict[str, Any]] = Field(default_factory=list)
    min_accuracy: float = Field(default=0.8, ge=0, le=1)
    activate: bool = False


class AiBackupScheduleRequest(BaseModel):
    enabled: bool = True
    interval_seconds: int = Field(default=86400, ge=60, le=2592000)
    retention: int = Field(default=7, ge=1, le=100)


class IndexRecordRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=50000)
    namespace: str = Field(default="emails", max_length=80)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    record_id: Optional[str] = None


class IndexBatchRequest(BaseModel):
    namespace: str = Field(default="emails", max_length=80)
    records: List[Dict[str, Any]] = Field(default_factory=list)


@router.get("/platform/version")
async def platform_version() -> Dict[str, Any]:
    return VERSION_INFO


@router.get("/ai/runtime/status")
async def ai_runtime_status() -> Dict[str, Any]:
    return get_runtime().status()


@router.get("/ai/hardware")
async def ai_hardware() -> Dict[str, Any]:
    return asdict(get_runtime().hardware)


@router.get("/ai/models")
async def ai_models() -> Dict[str, Any]:
    return get_runtime().model_manager.status()


@router.post("/ai/models/{model_name}/validate")
async def validate_model(model_name: str) -> Dict[str, Any]:
    return get_runtime().model_manager.validate_model(model_name)


@router.get("/ai/onnx/status")
async def ai_onnx_status() -> Dict[str, Any]:
    return get_onnx_control_plane().status()


@router.get("/ai/onnx/models")
async def ai_onnx_models() -> Dict[str, Any]:
    plane = get_onnx_control_plane()
    return {"models": plane.discover_models(), "status": plane.status()}


@router.post("/ai/onnx/validate")
async def ai_onnx_validate(request: ModelValidationRequest) -> Dict[str, Any]:
    return get_onnx_control_plane().validate_model(request.model_name)


@router.post("/ai/onnx/evaluate")
async def ai_onnx_evaluate(request: ModelEvaluationRequest, http_request: Request) -> Dict[str, Any]:
    if request.activate:
        _require_ai_admin(http_request, "ai:model:activate")
    return get_onnx_control_plane().evaluate_model(
        request.model_name,
        cases=request.cases,
        min_accuracy=request.min_accuracy,
        activate=request.activate,
    )


@router.post("/ai/onnx/classify")
async def ai_onnx_classify(request: TextPayloadRequest) -> Dict[str, Any]:
    return get_onnx_control_plane().classify(_model_to_dict(request))


@router.get("/ai/backups/status")
async def ai_backup_status(request: Request) -> Dict[str, Any]:
    _require_ai_admin(request, "ai:backup:read")
    return get_onnx_control_plane().ai_state_backup_status()


@router.post("/ai/backups/schedule")
async def ai_configure_backup_schedule(request: AiBackupScheduleRequest, http_request: Request) -> Dict[str, Any]:
    _require_ai_admin(http_request, "ai:backup:schedule")
    schedule = get_onnx_control_plane().configure_ai_state_backup_schedule(
        enabled=request.enabled,
        interval_seconds=request.interval_seconds,
        retention=request.retention,
    )
    return {"status": "scheduled", "schedule": schedule}


@router.post("/ai/backups/run")
async def ai_run_backup(request: Request) -> Dict[str, Any]:
    _require_ai_admin(request, "ai:backup:create")
    return get_onnx_control_plane().create_ai_state_backup(reason="manual")


@router.post("/ai/backups/scheduled/run")
async def ai_run_scheduled_backup(request: Request) -> Dict[str, Any]:
    _require_ai_admin(request, "ai:backup:create")
    return get_onnx_control_plane().run_scheduled_ai_state_backup()


@router.post("/ai/backups/{backup_id}/restore")
async def ai_restore_backup(backup_id: str, request: Request) -> Dict[str, Any]:
    _require_ai_admin(request, "ai:backup:restore")
    return get_onnx_control_plane().restore_ai_state_backup(backup_id)


@router.post("/ai/learning/feedback")
async def ai_learning_feedback(request: LearningFeedbackRequest) -> Dict[str, Any]:
    return get_onnx_control_plane().record_feedback(_model_to_dict(request))


@router.get("/ai/learning/stats")
async def ai_learning_stats() -> Dict[str, Any]:
    return get_onnx_control_plane().learning_stats()


@router.get("/ai/learning/overrides")
async def ai_learning_overrides() -> Dict[str, Any]:
    return get_onnx_control_plane().learning_overrides()


@router.get("/ai/learning/events")
async def ai_learning_events(limit: int = 50) -> Dict[str, Any]:
    return get_onnx_control_plane().learning_events(limit)


@router.delete("/ai/learning/overrides/{override_key:path}")
async def ai_forget_learning_override(override_key: str, request: Request) -> Dict[str, Any]:
    _require_ai_admin(request, "ai:learning:forget")
    return get_onnx_control_plane().forget_learning_override(override_key)


@router.get("/ai/learning/export")
async def ai_export_learning_memory(request: Request) -> Dict[str, Any]:
    _require_ai_admin(request, "ai:learning:export")
    return get_onnx_control_plane().export_learning_memory()


@router.post("/ai/learning/import/preview")
async def ai_preview_learning_import(request: LearningImportRequest, http_request: Request) -> Dict[str, Any]:
    _require_ai_admin(http_request, "ai:learning:import")
    return get_onnx_control_plane().preview_learning_import(_model_to_dict(request))


@router.post("/ai/learning/import")
async def ai_import_learning_memory(request: LearningImportRequest, http_request: Request) -> Dict[str, Any]:
    _require_ai_admin(http_request, "ai:learning:import")
    payload = _model_to_dict(request)
    return get_onnx_control_plane().import_learning_memory(payload, replace=bool(payload.get("replace")))


@router.get("/ai/self-healing/status")
async def ai_self_healing_status() -> Dict[str, Any]:
    return get_onnx_control_plane().self_healing_status()


@router.post("/ai/self-healing/models/{model_name}/failure")
async def ai_report_model_failure(model_name: str, request: Request, reason: str = "manual_failure_report") -> Dict[str, Any]:
    _require_ai_admin(request, "ai:model:quarantine")
    return get_onnx_control_plane().report_model_failure(model_name, reason)


@router.post("/ai/self-healing/models/{model_name}/recover")
async def ai_recover_model(model_name: str, request: Request) -> Dict[str, Any]:
    _require_ai_admin(request, "ai:model:recover")
    return get_onnx_control_plane().recover_model(model_name)


@router.post("/ai/infer")
async def ai_infer(request: InferRequest) -> Dict[str, Any]:
    if request.run_async:
        job_id = get_execution_queue().submit(request.task, request.payload, request.priority)
        return {"queued": True, "job_id": job_id, "version": APP_VERSION}
    return asdict(get_runtime().infer(request.task, request.payload))


@router.post("/ai/queue/{job_id}/run")
async def run_ai_job(job_id: str) -> Dict[str, Any]:
    try:
        result = get_execution_queue().run_now(job_id)
        return {"version": APP_VERSION, "job_id": job_id, "status": "completed", "result": result}
    except KeyError:
        raise HTTPException(status_code=404, detail="job_not_found")


@router.post("/ai/queue/{job_id}/cancel")
async def cancel_ai_job(job_id: str) -> Dict[str, Any]:
    return {"cancelled": get_execution_queue().cancel(job_id), "job_id": job_id}


@router.get("/ai/queue/status")
async def ai_queue_status() -> Dict[str, Any]:
    return get_execution_queue().status()


@router.post("/ai/memory/upsert")
async def memory_upsert(request: MemoryUpsertRequest) -> Dict[str, Any]:
    record_id = get_semantic_store().upsert(request.text, request.namespace, request.metadata, request.record_id)
    return {"id": record_id, "version": APP_VERSION, "status": "stored"}


@router.post("/ai/search")
async def ai_search(request: SearchRequest) -> Dict[str, Any]:
    return {"version": APP_VERSION, "results": get_semantic_store().search(request.query, request.namespace, request.top_k)}


@router.get("/ai/memory/status")
async def ai_memory_status() -> Dict[str, Any]:
    return get_semantic_store().status()


@router.get("/ai/agents")
async def ai_agents() -> Dict[str, Any]:
    return get_agent_orchestrator().status()


@router.post("/ai/agents/run")
async def run_agent(request: AgentRunRequest) -> Dict[str, Any]:
    try:
        return get_agent_orchestrator().run(request.agent, request.task, request.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/ai/workflows")
async def ai_workflows() -> Dict[str, Any]:
    return get_workflow_engine().status()


@router.post("/ai/workflows/execute")
async def run_workflow(request: WorkflowRequest) -> Dict[str, Any]:
    steps = [WorkflowStep(action=str(step.get("action", "noop")), payload=dict(step.get("payload", {}))) for step in request.steps]
    return get_workflow_engine().execute(request.name, steps)


@router.get("/ai/governance/status")
async def ai_governance_status() -> Dict[str, Any]:
    return get_governance_engine().status()




@router.post("/ai/classify")
async def ai_classify(request: TextPayloadRequest) -> Dict[str, Any]:
    return {"version": APP_VERSION, "classification": get_nlp_pipeline().classify(_model_to_dict(request))}


@router.post("/ai/extract")
async def ai_extract(request: TextPayloadRequest) -> Dict[str, Any]:
    return {"version": APP_VERSION, "entities": get_nlp_pipeline().extract(_model_to_dict(request))}


@router.post("/ai/tags")
async def ai_smart_tags(request: TextPayloadRequest) -> Dict[str, Any]:
    return {"version": APP_VERSION, **get_nlp_pipeline().smart_tags(_model_to_dict(request))}


@router.post("/ai/priority")
async def ai_priority(request: TextPayloadRequest) -> Dict[str, Any]:
    return {"version": APP_VERSION, **get_nlp_pipeline().priority(_model_to_dict(request))}


@router.post("/ai/workflows/suggest")
async def ai_workflow_suggest(request: TextPayloadRequest) -> Dict[str, Any]:
    return {"version": APP_VERSION, "suggestion": get_nlp_pipeline().workflow_suggestion(_model_to_dict(request))}


@router.post("/ai/index/record")
async def ai_index_record(request: IndexRecordRequest) -> Dict[str, Any]:
    return {"version": APP_VERSION, **get_indexing_worker().index_record(request.text, request.namespace, request.metadata, request.record_id)}


@router.post("/ai/index/batch")
async def ai_index_batch(request: IndexBatchRequest) -> Dict[str, Any]:
    return {"version": APP_VERSION, **get_indexing_worker().index_batch(request.records, request.namespace)}


@router.get("/ai/index/status")
async def ai_index_status() -> Dict[str, Any]:
    return get_indexing_worker().status()


@router.get("/ai/cache/status")
async def ai_cache_status() -> Dict[str, Any]:
    return get_ai_cache().status()


@router.get("/ai/telemetry/status")
async def ai_telemetry_status() -> Dict[str, Any]:
    return get_ai_telemetry().status()


@router.get("/ai/diagnostics/status")
async def ai_diagnostics_status() -> Dict[str, Any]:
    runtime = get_runtime().status()
    queue = get_execution_queue().status()
    memory = get_semantic_store().status()
    telemetry = get_ai_telemetry().status()
    indexer = get_indexing_worker().status()
    return {
        "version": APP_VERSION,
        "status": "ready" if runtime.get("status") == "ready" else "degraded",
        "runtime": runtime,
        "queue": queue,
        "memory": memory,
        "telemetry": telemetry,
        "indexer": indexer,
        "privacy": {
            "email_content_uploaded": False,
            "attachments_uploaded": False,
            "oauth_tokens_uploaded": False,
            "diagnostics_only": True,
        },
    }


@router.get("/ai/vector-db/status")
async def ai_vector_db_status() -> Dict[str, Any]:
    return get_vector_db().status()


@router.get("/ai/command-center")
async def ai_command_center() -> Dict[str, Any]:
    return {
        "product": DISPLAY_VERSION,
        "version": APP_VERSION,
        "runtime": get_runtime().status(),
        "queue": get_execution_queue().status(),
        "memory": get_semantic_store().status(),
        "agents": get_agent_orchestrator().status(),
        "workflows": get_workflow_engine().status(),
        "governance": get_governance_engine().status(),
        "indexing": get_indexing_worker().status(),
        "cache": get_ai_cache().status(),
        "telemetry": get_ai_telemetry().status(),
        "vector_db": get_vector_db().status(),
        "required_ai_modules": {
            "onnx_runtime_integration": True,
            "embedding_pipeline": True,
            "semantic_search_engine": True,
            "lightweight_nlp_pipeline": True,
            "classification_system": True,
            "extraction_system": True,
            "smart_tagging_system": True,
            "priority_detection_engine": True,
            "workflow_intelligence_engine": True,
            "semantic_indexing_system": True,
            "vector_database_integration": True,
            "contextual_retrieval_engine": True,
            "similarity_ranking_engine": True,
            "ai_telemetry_integration": True,
            "ai_diagnostics_integration": True,
            "ai_settings_system": True,
            "ai_caching_system": True,
            "ai_queue_integration": True,
            "ai_indexing_workers": True,
            "ai_error_handling_system": True,
        },
        "telemetry_privacy": {
            "email_content_uploaded": False,
            "attachments_uploaded": False,
            "oauth_tokens_uploaded": False,
            "diagnostics_only": True,
        },
    }
