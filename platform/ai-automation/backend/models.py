"""Pydantic v2 models for the AI Automation Platform."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_APPROVAL = "waiting_approval"


class NodeType(str, Enum):
    TRIGGER_EMAIL = "trigger_email"
    TRIGGER_WEBHOOK = "trigger_webhook"
    TRIGGER_SCHEDULE = "trigger_schedule"
    TRIGGER_MANUAL = "trigger_manual"
    AI_CLASSIFY = "ai_classify"
    AI_EXTRACT = "ai_extract"
    AI_SUMMARIZE = "ai_summarize"
    AI_GENERATE = "ai_generate"
    AI_TRANSLATE = "ai_translate"
    AI_SENTIMENT = "ai_sentiment"
    OCR_PROCESS = "ocr_process"
    OCR_VALIDATE = "ocr_validate"
    CONDITION = "condition"
    SWITCH = "switch"
    LOOP = "loop"
    APPROVAL_REQUEST = "approval_request"
    APPROVAL_GATE = "approval_gate"
    SEND_EMAIL = "send_email"
    SEND_WHATSAPP = "send_whatsapp"
    SEND_SMS = "send_sms"
    SEND_NOTIFICATION = "send_notification"
    HTTP_REQUEST = "http_request"
    DATABASE_QUERY = "database_query"
    TRANSFORM = "transform"
    DELAY = "delay"
    LOG = "log"
    SEARCH = "search"
    AGENT_RUN = "agent_run"
    MERGE = "merge"


class AgentType(str, Enum):
    OCR = "ocr"
    COMMUNICATION = "communication"
    APPROVAL = "approval"
    SEARCH = "search"
    WORKFLOW = "workflow"
    CUSTOM = "custom"


class AIProvider(str, Enum):
    OPENAI = "openai"
    CLAUDE = "claude"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    LOCAL = "local"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Workflow models
# ---------------------------------------------------------------------------

class NodeConnection(BaseModel):
    source_id: str
    target_id: str
    condition: Optional[str] = None
    label: Optional[str] = None


class WorkflowNode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: NodeType
    label: str
    config: Dict[str, Any] = Field(default_factory=dict)
    position: Dict[str, float] = Field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: Optional[str] = None
    tenant_id: str
    version: int = 1
    status: WorkflowStatus = WorkflowStatus.DRAFT
    nodes: List[WorkflowNode] = Field(default_factory=list)
    connections: List[NodeConnection] = Field(default_factory=list)
    variables: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[str] = None


class WorkflowCreate(BaseModel):
    name: str
    description: Optional[str] = None
    nodes: List[WorkflowNode] = Field(default_factory=list)
    connections: List[NodeConnection] = Field(default_factory=list)
    variables: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[WorkflowStatus] = None
    nodes: Optional[List[WorkflowNode]] = None
    connections: Optional[List[NodeConnection]] = None
    variables: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None


# ---------------------------------------------------------------------------
# Execution models
# ---------------------------------------------------------------------------

class ExecutionStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str
    node_id: str
    node_type: NodeType
    status: ExecutionStatus = ExecutionStatus.PENDING
    input_data: Dict[str, Any] = Field(default_factory=dict)
    output_data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    retry_count: int = 0


class WorkflowExecution(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    workflow_name: str
    tenant_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    trigger_data: Dict[str, Any] = Field(default_factory=dict)
    context: Dict[str, Any] = Field(default_factory=dict)
    steps: List[ExecutionStep] = Field(default_factory=list)
    current_node_id: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    triggered_by: Optional[str] = None


class ExecutionCreate(BaseModel):
    workflow_id: str
    trigger_data: Dict[str, Any] = Field(default_factory=dict)
    triggered_by: Optional[str] = None


# ---------------------------------------------------------------------------
# AI models
# ---------------------------------------------------------------------------

class AIRequest(BaseModel):
    provider: Optional[AIProvider] = None
    model: Optional[str] = None
    prompt: str
    system_prompt: Optional[str] = None
    max_tokens: int = 1024
    temperature: float = 0.7
    context: Dict[str, Any] = Field(default_factory=dict)
    tenant_id: Optional[str] = None


class AIResponse(BaseModel):
    provider: AIProvider
    model: str
    content: str
    tokens_used: int = 0
    cost_estimate: float = 0.0
    latency_ms: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AIProviderConfig(BaseModel):
    provider: AIProvider
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None
    enabled: bool = True
    rate_limit_rpm: int = 60
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# OCR models
# ---------------------------------------------------------------------------

class OCRRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_url: Optional[str] = None
    document_base64: Optional[str] = None
    document_type: Optional[str] = None
    extract_fields: List[str] = Field(default_factory=list)
    should_validate: bool = Field(default=True, alias="validate")
    tenant_id: Optional[str] = None


class OCRField(BaseModel):
    name: str
    value: Optional[str] = None
    confidence: float = 0.0
    bounding_box: Optional[Dict[str, float]] = None


class OCRResult(BaseModel):
    document_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_type: str = "unknown"
    raw_text: str = ""
    fields: List[OCRField] = Field(default_factory=list)
    confidence: float = 0.0
    needs_review: bool = False
    review_reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Approval models
# ---------------------------------------------------------------------------

class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    execution_id: str
    workflow_id: str
    tenant_id: str
    title: str
    description: str
    risk_level: RiskLevel = RiskLevel.LOW
    data: Dict[str, Any] = Field(default_factory=dict)
    assignee: Optional[str] = None
    assignee_group: Optional[str] = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    decision: Optional[str] = None
    decision_notes: Optional[str] = None
    decided_by: Optional[str] = None
    expires_at: Optional[datetime] = None
    escalate_after_minutes: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    decided_at: Optional[datetime] = None


class ApprovalDecision(BaseModel):
    status: ApprovalStatus
    notes: Optional[str] = None
    decided_by: str


# ---------------------------------------------------------------------------
# Agent models
# ---------------------------------------------------------------------------

class AgentTask(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_type: AgentType
    task_name: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    config: Dict[str, Any] = Field(default_factory=dict)
    tenant_id: Optional[str] = None
    execution_id: Optional[str] = None


class AgentResult(BaseModel):
    task_id: str
    agent_type: AgentType
    success: bool
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    latency_ms: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Analytics models
# ---------------------------------------------------------------------------

class WorkflowAnalytics(BaseModel):
    workflow_id: str
    workflow_name: str
    tenant_id: str
    total_executions: int = 0
    successful: int = 0
    failed: int = 0
    pending_approvals: int = 0
    avg_duration_ms: float = 0.0
    success_rate: float = 0.0
    last_executed: Optional[datetime] = None


class PlatformStats(BaseModel):
    total_workflows: int = 0
    active_workflows: int = 0
    total_executions: int = 0
    running_executions: int = 0
    pending_approvals: int = 0
    ai_requests_today: int = 0
    ocr_documents_today: int = 0
    tenant_id: str = "global"


# ---------------------------------------------------------------------------
# Search models
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    tenant_id: str
    limit: int = 20
    offset: int = 0
    filters: Dict[str, Any] = Field(default_factory=dict)
    include_content: bool = True


class SearchResult(BaseModel):
    id: str
    type: str
    title: str
    snippet: str = ""
    score: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    total: int
    results: List[SearchResult]
    took_ms: int = 0
