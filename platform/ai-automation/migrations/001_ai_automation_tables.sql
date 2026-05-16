-- AI Automation Platform – Initial Schema
-- Applied automatically by init_ai_automation_db()

CREATE TABLE IF NOT EXISTS workflows (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    tenant_id TEXT NOT NULL,
    version INTEGER DEFAULT 1,
    status TEXT DEFAULT 'draft' CHECK(status IN ('draft','active','paused','archived')),
    nodes_json TEXT DEFAULT '[]',
    connections_json TEXT DEFAULT '[]',
    variables_json TEXT DEFAULT '{}',
    tags_json TEXT DEFAULT '[]',
    created_at TEXT,
    updated_at TEXT,
    created_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_workflows_tenant ON workflows(tenant_id);
CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status);
CREATE INDEX IF NOT EXISTS idx_workflows_updated ON workflows(updated_at DESC);

CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NOT NULL,
    workflow_name TEXT,
    tenant_id TEXT NOT NULL,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending','running','paused','completed','failed','cancelled','waiting_approval')),
    trigger_data_json TEXT DEFAULT '{}',
    context_json TEXT DEFAULT '{}',
    current_node_id TEXT,
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    triggered_by TEXT,
    FOREIGN KEY(workflow_id) REFERENCES workflows(id)
);

CREATE INDEX IF NOT EXISTS idx_executions_workflow ON executions(workflow_id);
CREATE INDEX IF NOT EXISTS idx_executions_tenant ON executions(tenant_id);
CREATE INDEX IF NOT EXISTS idx_executions_status ON executions(status);
CREATE INDEX IF NOT EXISTS idx_executions_started ON executions(started_at DESC);

CREATE TABLE IF NOT EXISTS execution_steps (
    id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    node_type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    input_data_json TEXT DEFAULT '{}',
    output_data_json TEXT DEFAULT '{}',
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    retry_count INTEGER DEFAULT 0,
    FOREIGN KEY(execution_id) REFERENCES executions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_steps_execution ON execution_steps(execution_id);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    execution_id TEXT,
    workflow_id TEXT,
    tenant_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    risk_level TEXT DEFAULT 'low' CHECK(risk_level IN ('low','medium','high','critical')),
    data_json TEXT DEFAULT '{}',
    assignee TEXT,
    assignee_group TEXT,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected','escalated','expired')),
    decision TEXT,
    decision_notes TEXT,
    decided_by TEXT,
    expires_at TEXT,
    escalate_after_minutes INTEGER,
    created_at TEXT,
    decided_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approvals_tenant ON approval_requests(tenant_id);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approval_requests(status);
CREATE INDEX IF NOT EXISTS idx_approvals_execution ON approval_requests(execution_id);

CREATE TABLE IF NOT EXISTS ai_requests_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT,
    provider TEXT,
    model TEXT,
    tokens_used INTEGER DEFAULT 0,
    cost_estimate REAL DEFAULT 0,
    latency_ms INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_log_tenant ON ai_requests_log(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ai_log_created ON ai_requests_log(created_at);

CREATE TABLE IF NOT EXISTS ocr_results (
    id TEXT PRIMARY KEY,
    tenant_id TEXT,
    document_type TEXT,
    raw_text TEXT,
    fields_json TEXT DEFAULT '[]',
    confidence REAL DEFAULT 0,
    needs_review INTEGER DEFAULT 0,
    review_reason TEXT,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_ocr_tenant ON ocr_results(tenant_id);
CREATE INDEX IF NOT EXISTS idx_ocr_review ON ocr_results(needs_review);

CREATE TABLE IF NOT EXISTS ai_provider_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    api_key_enc TEXT,
    base_url TEXT,
    default_model TEXT,
    enabled INTEGER DEFAULT 1,
    rate_limit_rpm INTEGER DEFAULT 60,
    metadata_json TEXT DEFAULT '{}',
    UNIQUE(tenant_id, provider)
);
