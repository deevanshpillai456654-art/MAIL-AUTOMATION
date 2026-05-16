-- ============================================================
-- Migration 001: Connector Panel Tables
-- MailPilot Connector & Plugin Panel
-- Version: 1.0.0
-- ============================================================

-- Enable WAL mode and performance pragmas
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA cache_size   = -8000;

-- ============================================================
-- connectors
-- Stores all installed connector instances per tenant.
-- ============================================================
CREATE TABLE IF NOT EXISTS connectors (
    id              TEXT PRIMARY KEY,               -- Unique installed-connector ID (con_<uuid>)
    tenant_id       TEXT NOT NULL,                  -- Owning tenant
    manifest_id     TEXT NOT NULL,                  -- Marketplace connector ID (e.g. 'whatsapp')
    name            TEXT NOT NULL,                  -- Human-readable connector name
    category        TEXT NOT NULL,                  -- communication | erp | crm | ... (ConnectorCategory)
    status          TEXT NOT NULL DEFAULT 'inactive', -- active | inactive | installing | failed | degraded
    version         TEXT NOT NULL DEFAULT '1.0.0',
    config_json     TEXT NOT NULL DEFAULT '{}',     -- Connector config (non-secret fields)
    installed_at    TEXT NOT NULL,                  -- ISO 8601 UTC datetime
    last_sync       TEXT,                           -- ISO 8601 UTC datetime of last successful sync
    last_heartbeat  TEXT,                           -- ISO 8601 UTC datetime of last heartbeat
    failure_count   INTEGER NOT NULL DEFAULT 0,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    health_score    REAL    NOT NULL DEFAULT 1.0,   -- [0.0, 1.0]
    is_active       INTEGER NOT NULL DEFAULT 1      -- 1 = active, 0 = soft-deleted / disabled
);

CREATE INDEX IF NOT EXISTS idx_connectors_tenant   ON connectors(tenant_id);
CREATE INDEX IF NOT EXISTS idx_connectors_status   ON connectors(status);
CREATE INDEX IF NOT EXISTS idx_connectors_category ON connectors(category);
CREATE INDEX IF NOT EXISTS idx_connectors_manifest ON connectors(manifest_id);

-- ============================================================
-- oauth_tokens
-- Encrypted OAuth access/refresh tokens per connector+tenant.
-- NEVER expose token values in API responses.
-- ============================================================
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id                  TEXT PRIMARY KEY,           -- tok_<uuid>
    connector_id        TEXT NOT NULL,              -- FK → connectors.id
    tenant_id           TEXT NOT NULL,
    provider            TEXT NOT NULL,              -- google | microsoft | shopify | slack | ...
    access_token_enc    TEXT NOT NULL,              -- Fernet-encrypted access token
    refresh_token_enc   TEXT,                       -- Fernet-encrypted refresh token (nullable)
    expires_at          TEXT,                       -- ISO 8601 UTC expiry datetime
    scopes              TEXT NOT NULL DEFAULT '[]', -- JSON array of granted scopes
    created_at          TEXT NOT NULL,              -- ISO 8601 UTC
    is_valid            INTEGER NOT NULL DEFAULT 1, -- 0 = revoked / expired
    FOREIGN KEY (connector_id) REFERENCES connectors(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_oauth_connector ON oauth_tokens(connector_id);
CREATE INDEX IF NOT EXISTS idx_oauth_tenant    ON oauth_tokens(tenant_id);
CREATE INDEX IF NOT EXISTS idx_oauth_provider  ON oauth_tokens(provider);
CREATE INDEX IF NOT EXISTS idx_oauth_valid     ON oauth_tokens(is_valid);

-- ============================================================
-- webhooks
-- Outbound webhook endpoints registered per connector+tenant.
-- Secrets are stored Fernet-encrypted.
-- ============================================================
CREATE TABLE IF NOT EXISTS webhooks (
    id              TEXT PRIMARY KEY,           -- wh_<uuid>
    connector_id    TEXT NOT NULL,              -- FK → connectors.id
    tenant_id       TEXT NOT NULL,
    url             TEXT NOT NULL,              -- Delivery URL
    secret_enc      TEXT,                       -- Fernet-encrypted signing secret (nullable)
    events_json     TEXT NOT NULL DEFAULT '[]', -- JSON array of subscribed event types
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    last_triggered  TEXT,                       -- ISO 8601 UTC
    failure_count   INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (connector_id) REFERENCES connectors(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_webhooks_connector ON webhooks(connector_id);
CREATE INDEX IF NOT EXISTS idx_webhooks_tenant    ON webhooks(tenant_id);
CREATE INDEX IF NOT EXISTS idx_webhooks_active    ON webhooks(is_active);

-- ============================================================
-- connector_logs
-- Per-connector log entries (INFO / WARN / ERROR / DEBUG).
-- Retention policy: rows older than LOG_RETENTION_DAYS (30) are purged.
-- ============================================================
CREATE TABLE IF NOT EXISTS connector_logs (
    id              TEXT PRIMARY KEY,           -- log_<uuid>
    connector_id    TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    level           TEXT NOT NULL DEFAULT 'INFO', -- INFO | WARN | ERROR | DEBUG
    message         TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}', -- Arbitrary structured metadata
    timestamp       TEXT NOT NULL               -- ISO 8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_logs_connector  ON connector_logs(connector_id);
CREATE INDEX IF NOT EXISTS idx_logs_tenant     ON connector_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_logs_level      ON connector_logs(level);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp  ON connector_logs(timestamp);

-- ============================================================
-- queue_jobs
-- Async job queue per connector+tenant.
-- Dead-letter queue: jobs where status='dead'
-- ============================================================
CREATE TABLE IF NOT EXISTS queue_jobs (
    id              TEXT PRIMARY KEY,               -- job_<uuid>
    connector_id    TEXT NOT NULL,
    tenant_id       TEXT NOT NULL,
    job_type        TEXT NOT NULL,                  -- e.g. 'sync', 'send_message', 'process_document'
    status          TEXT NOT NULL DEFAULT 'queued', -- queued | processing | completed | failed | dead | cancelled
    payload_json    TEXT NOT NULL DEFAULT '{}',     -- Job input parameters
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 3,
    error           TEXT,                           -- Last error message
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_connector ON queue_jobs(connector_id);
CREATE INDEX IF NOT EXISTS idx_jobs_tenant    ON queue_jobs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status    ON queue_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_type      ON queue_jobs(job_type);
CREATE INDEX IF NOT EXISTS idx_jobs_created   ON queue_jobs(created_at);

-- ============================================================
-- plugin_permissions
-- Per-plugin, per-tenant permission grants.
-- ============================================================
CREATE TABLE IF NOT EXISTS plugin_permissions (
    id          TEXT PRIMARY KEY,
    plugin_id   TEXT NOT NULL,
    tenant_id   TEXT NOT NULL,
    permission  TEXT NOT NULL,  -- read | write | admin
    granted_at  TEXT NOT NULL,
    granted_by  TEXT NOT NULL,  -- user or system identifier
    UNIQUE(plugin_id, tenant_id, permission)
);

CREATE INDEX IF NOT EXISTS idx_perm_plugin ON plugin_permissions(plugin_id);
CREATE INDEX IF NOT EXISTS idx_perm_tenant ON plugin_permissions(tenant_id);

-- ============================================================
-- events
-- Published platform events for audit and subscriber delivery.
-- ============================================================
CREATE TABLE IF NOT EXISTS events (
    id                  TEXT PRIMARY KEY,    -- evt_<uuid>
    event_type          TEXT NOT NULL,       -- e.g. 'invoice.created', 'email.received'
    source_connector_id TEXT NOT NULL,       -- Plugin that published the event
    tenant_id           TEXT NOT NULL,
    payload_json        TEXT NOT NULL DEFAULT '{}',
    published_at        TEXT NOT NULL,       -- ISO 8601 UTC
    processed_by_json   TEXT NOT NULL DEFAULT '[]' -- JSON array of subscriber IDs that processed this
);

CREATE INDEX IF NOT EXISTS idx_events_type      ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_tenant    ON events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_events_source    ON events(source_connector_id);
CREATE INDEX IF NOT EXISTS idx_events_published ON events(published_at);

-- ============================================================
-- marketplace_cache
-- Cached marketplace connector manifests.
-- ============================================================
CREATE TABLE IF NOT EXISTS marketplace_cache (
    id              TEXT PRIMARY KEY,
    connector_id    TEXT NOT NULL UNIQUE,   -- Marketplace connector ID
    manifest_json   TEXT NOT NULL,          -- Full manifest JSON
    cached_at       TEXT NOT NULL           -- ISO 8601 UTC
);

-- ============================================================
-- connector_health
-- Latest health metrics per connector+tenant.
-- ============================================================
CREATE TABLE IF NOT EXISTS connector_health (
    id                  TEXT PRIMARY KEY,
    connector_id        TEXT NOT NULL,
    tenant_id           TEXT NOT NULL,
    checks_json         TEXT NOT NULL DEFAULT '{}', -- Key-value health check results
    response_latency_ms REAL,                       -- Last API response latency in ms
    api_quota_used      INTEGER,                    -- API calls used in current window
    api_quota_limit     INTEGER,                    -- API call limit for current window
    updated_at          TEXT NOT NULL,              -- ISO 8601 UTC
    UNIQUE(connector_id, tenant_id)
);

CREATE INDEX IF NOT EXISTS idx_health_connector ON connector_health(connector_id);
CREATE INDEX IF NOT EXISTS idx_health_tenant    ON connector_health(tenant_id);
CREATE INDEX IF NOT EXISTS idx_health_updated   ON connector_health(updated_at);
