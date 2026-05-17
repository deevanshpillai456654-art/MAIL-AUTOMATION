"""
ConnectorPanelDB — isolated SQLite database for the connector panel.
Uses WAL mode, thread-local connections, and a singleton pattern.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_db_path() -> str:
    """
    Resolve the DB path.  Priority:
      1. CONNECTOR_PANEL_DB_PATH env var
      2. Alongside the connectors-panel package at platform level
    """
    env_path = os.environ.get("CONNECTOR_PANEL_DB_PATH", "")
    if env_path:
        return env_path
    # __file__ is  .../platform/connectors-panel/backend/db.py
    # We want      .../platform/connectors_panel.db
    this_file = Path(__file__).resolve()
    platform_dir = this_file.parent.parent.parent  # platform/
    return str(platform_dir / "connectors_panel.db")


# ---------------------------------------------------------------------------
# ConnectorPanelDB
# ---------------------------------------------------------------------------

class ConnectorPanelDB:
    """
    Thread-safe SQLite wrapper using thread-local connections.
    Each thread gets its own connection; WAL mode is enabled for concurrency.
    """

    _local = threading.local()

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _resolve_db_path()
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute("PRAGMA cache_size=-8000;")  # 8 MB page cache
            conn.commit()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ------------------------------------------------------------------
    # Core query methods
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        conn = self._get_conn()
        try:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor
        except sqlite3.Error:
            conn.rollback()
            raise

    def fetch_one(self, sql: str, params: tuple | list = ()) -> Optional[dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.execute(sql, params)
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetch_all(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        conn = self._get_conn()
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]

    def executemany(self, sql: str, params_list: list) -> None:
        conn = self._get_conn()
        try:
            conn.executemany(sql, params_list)
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Schema creation
    # ------------------------------------------------------------------

    def create_tables(self) -> None:
        ddl_statements = [
            # ----------------------------------------------------------------
            # connectors
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS connectors (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                manifest_id     TEXT NOT NULL,
                name            TEXT NOT NULL,
                category        TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'inactive',
                version         TEXT NOT NULL DEFAULT '1.0.0',
                config_json     TEXT NOT NULL DEFAULT '{}',
                installed_at    TEXT NOT NULL,
                last_sync       TEXT,
                last_heartbeat  TEXT,
                failure_count   INTEGER NOT NULL DEFAULT 0,
                retry_count     INTEGER NOT NULL DEFAULT 0,
                health_score    REAL NOT NULL DEFAULT 1.0,
                is_active       INTEGER NOT NULL DEFAULT 1
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_connectors_tenant ON connectors(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_connectors_status  ON connectors(status)",
            "CREATE INDEX IF NOT EXISTS idx_connectors_category ON connectors(category)",

            # ----------------------------------------------------------------
            # oauth_tokens
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                id                  TEXT PRIMARY KEY,
                connector_id        TEXT NOT NULL,
                tenant_id           TEXT NOT NULL,
                provider            TEXT NOT NULL,
                access_token_enc    TEXT NOT NULL,
                refresh_token_enc   TEXT,
                expires_at          TEXT,
                scopes              TEXT NOT NULL DEFAULT '[]',
                created_at          TEXT NOT NULL,
                is_valid            INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (connector_id) REFERENCES connectors(id) ON DELETE CASCADE,
                UNIQUE(connector_id, tenant_id, provider)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_oauth_connector  ON oauth_tokens(connector_id)",
            "CREATE INDEX IF NOT EXISTS idx_oauth_tenant     ON oauth_tokens(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_oauth_provider   ON oauth_tokens(provider)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_oauth_uq ON oauth_tokens(connector_id, tenant_id, provider)",

            # ----------------------------------------------------------------
            # webhooks
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS webhooks (
                id              TEXT PRIMARY KEY,
                connector_id    TEXT NOT NULL,
                tenant_id       TEXT NOT NULL,
                url             TEXT NOT NULL,
                secret_enc      TEXT,
                events_json     TEXT NOT NULL DEFAULT '[]',
                is_active       INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL,
                last_triggered  TEXT,
                failure_count   INTEGER NOT NULL DEFAULT 0,
                success_count   INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (connector_id) REFERENCES connectors(id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_webhooks_connector ON webhooks(connector_id)",
            "CREATE INDEX IF NOT EXISTS idx_webhooks_tenant    ON webhooks(tenant_id)",

            # ----------------------------------------------------------------
            # connector_logs
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS connector_logs (
                id              TEXT PRIMARY KEY,
                connector_id    TEXT NOT NULL,
                tenant_id       TEXT NOT NULL,
                level           TEXT NOT NULL DEFAULT 'INFO',
                message         TEXT NOT NULL,
                metadata_json   TEXT NOT NULL DEFAULT '{}',
                timestamp       TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_logs_connector  ON connector_logs(connector_id)",
            "CREATE INDEX IF NOT EXISTS idx_logs_tenant     ON connector_logs(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_logs_level      ON connector_logs(level)",
            "CREATE INDEX IF NOT EXISTS idx_logs_timestamp  ON connector_logs(timestamp)",

            # ----------------------------------------------------------------
            # queue_jobs
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS queue_jobs (
                id              TEXT PRIMARY KEY,
                connector_id    TEXT NOT NULL,
                tenant_id       TEXT NOT NULL,
                job_type        TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'queued',
                payload_json    TEXT NOT NULL DEFAULT '{}',
                attempts        INTEGER NOT NULL DEFAULT 0,
                max_attempts    INTEGER NOT NULL DEFAULT 3,
                error           TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_jobs_connector ON queue_jobs(connector_id)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_tenant    ON queue_jobs(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_status    ON queue_jobs(status)",
            "CREATE INDEX IF NOT EXISTS idx_jobs_created   ON queue_jobs(created_at)",

            # ----------------------------------------------------------------
            # plugin_permissions
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS plugin_permissions (
                id          TEXT PRIMARY KEY,
                plugin_id   TEXT NOT NULL,
                tenant_id   TEXT NOT NULL,
                permission  TEXT NOT NULL,
                granted_at  TEXT NOT NULL,
                granted_by  TEXT NOT NULL,
                UNIQUE(plugin_id, tenant_id, permission)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_perm_plugin ON plugin_permissions(plugin_id)",
            "CREATE INDEX IF NOT EXISTS idx_perm_tenant ON plugin_permissions(tenant_id)",

            # ----------------------------------------------------------------
            # events
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS events (
                id                  TEXT PRIMARY KEY,
                event_type          TEXT NOT NULL,
                source_connector_id TEXT NOT NULL,
                tenant_id           TEXT NOT NULL,
                payload_json        TEXT NOT NULL DEFAULT '{}',
                published_at        TEXT NOT NULL,
                processed_by_json   TEXT NOT NULL DEFAULT '[]'
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_events_type      ON events(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_events_tenant    ON events(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_events_source    ON events(source_connector_id)",
            "CREATE INDEX IF NOT EXISTS idx_events_published ON events(published_at)",

            # ----------------------------------------------------------------
            # marketplace_cache
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS marketplace_cache (
                id              TEXT PRIMARY KEY,
                connector_id    TEXT NOT NULL UNIQUE,
                manifest_json   TEXT NOT NULL,
                cached_at       TEXT NOT NULL
            )
            """,

            # ----------------------------------------------------------------
            # connector_health
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS connector_health (
                id                  TEXT PRIMARY KEY,
                connector_id        TEXT NOT NULL,
                tenant_id           TEXT NOT NULL,
                checks_json         TEXT NOT NULL DEFAULT '{}',
                response_latency_ms REAL,
                api_quota_used      INTEGER,
                api_quota_limit     INTEGER,
                updated_at          TEXT NOT NULL,
                UNIQUE(connector_id, tenant_id)
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_health_connector ON connector_health(connector_id)",
            "CREATE INDEX IF NOT EXISTS idx_health_tenant    ON connector_health(tenant_id)",

            # ----------------------------------------------------------------
            # shipments  (unified tracking engine)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS shipments (
                id                  TEXT PRIMARY KEY,
                tenant_id           TEXT NOT NULL,
                tracking_number     TEXT NOT NULL,
                reference_number    TEXT,
                carrier             TEXT NOT NULL,
                tracking_type       TEXT NOT NULL DEFAULT 'awb',
                status              TEXT NOT NULL DEFAULT 'pending',
                origin_location     TEXT,
                destination_location TEXT,
                shipper_name        TEXT,
                consignee_name      TEXT,
                estimated_delivery  TEXT,
                actual_delivery     TEXT,
                weight_kg           REAL,
                pieces              INTEGER,
                description         TEXT,
                connector_id        TEXT,
                order_ref           TEXT,
                invoice_ref         TEXT,
                vendor_ref          TEXT,
                ai_delay_risk       TEXT DEFAULT 'low',
                ai_eta_predicted    TEXT,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_ship_tenant    ON shipments(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_ship_tracking  ON shipments(tracking_number)",
            "CREATE INDEX IF NOT EXISTS idx_ship_status    ON shipments(status)",
            "CREATE INDEX IF NOT EXISTS idx_ship_carrier   ON shipments(carrier)",

            """
            CREATE TABLE IF NOT EXISTS tracking_events (
                id           TEXT PRIMARY KEY,
                shipment_id  TEXT NOT NULL,
                tenant_id    TEXT NOT NULL,
                status       TEXT NOT NULL,
                location     TEXT,
                description  TEXT,
                carrier_code TEXT,
                timestamp    TEXT NOT NULL,
                raw_json     TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (shipment_id) REFERENCES shipments(id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_tevt_shipment  ON tracking_events(shipment_id)",
            "CREATE INDEX IF NOT EXISTS idx_tevt_tenant    ON tracking_events(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_tevt_timestamp ON tracking_events(timestamp)",

            # ----------------------------------------------------------------
            # ERP — vendors, purchase orders, invoices, inventory, warehouses
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS erp_vendors (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                name            TEXT NOT NULL,
                code            TEXT,
                email           TEXT,
                phone           TEXT,
                address_json    TEXT NOT NULL DEFAULT '{}',
                payment_terms   INTEGER NOT NULL DEFAULT 30,
                currency        TEXT NOT NULL DEFAULT 'USD',
                category        TEXT,
                status          TEXT NOT NULL DEFAULT 'active',
                tags_json       TEXT NOT NULL DEFAULT '[]',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_vendor_tenant ON erp_vendors(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_vendor_status ON erp_vendors(status)",

            """
            CREATE TABLE IF NOT EXISTS erp_purchase_orders (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                vendor_id       TEXT,
                po_number       TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'draft',
                items_json      TEXT NOT NULL DEFAULT '[]',
                subtotal        REAL NOT NULL DEFAULT 0,
                tax_amount      REAL NOT NULL DEFAULT 0,
                total_amount    REAL NOT NULL DEFAULT 0,
                currency        TEXT NOT NULL DEFAULT 'USD',
                order_date      TEXT NOT NULL,
                delivery_date   TEXT,
                delivery_addr   TEXT,
                notes           TEXT,
                approved_by     TEXT,
                approved_at     TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES erp_vendors(id) ON DELETE SET NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_po_tenant  ON erp_purchase_orders(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_po_vendor  ON erp_purchase_orders(vendor_id)",
            "CREATE INDEX IF NOT EXISTS idx_po_status  ON erp_purchase_orders(status)",
            "CREATE INDEX IF NOT EXISTS idx_po_number  ON erp_purchase_orders(po_number)",

            """
            CREATE TABLE IF NOT EXISTS erp_invoices (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                vendor_id       TEXT,
                po_id           TEXT,
                invoice_number  TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'draft',
                amount          REAL NOT NULL DEFAULT 0,
                tax_amount      REAL NOT NULL DEFAULT 0,
                total_amount    REAL NOT NULL DEFAULT 0,
                currency        TEXT NOT NULL DEFAULT 'USD',
                invoice_date    TEXT NOT NULL,
                due_date        TEXT,
                paid_at         TEXT,
                payment_method  TEXT,
                notes           TEXT,
                items_json      TEXT NOT NULL DEFAULT '[]',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv_tenant  ON erp_invoices(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_inv_vendor  ON erp_invoices(vendor_id)",
            "CREATE INDEX IF NOT EXISTS idx_inv_status  ON erp_invoices(status)",
            "CREATE INDEX IF NOT EXISTS idx_inv_due     ON erp_invoices(due_date)",

            """
            CREATE TABLE IF NOT EXISTS erp_warehouses (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                name            TEXT NOT NULL,
                code            TEXT,
                location        TEXT,
                address_json    TEXT NOT NULL DEFAULT '{}',
                capacity        INTEGER,
                current_stock   INTEGER NOT NULL DEFAULT 0,
                status          TEXT NOT NULL DEFAULT 'active',
                manager         TEXT,
                contact_json    TEXT NOT NULL DEFAULT '{}',
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_wh_tenant ON erp_warehouses(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_wh_status ON erp_warehouses(status)",

            """
            CREATE TABLE IF NOT EXISTS erp_inventory (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                warehouse_id    TEXT,
                sku             TEXT NOT NULL,
                name            TEXT NOT NULL,
                category        TEXT,
                quantity        INTEGER NOT NULL DEFAULT 0,
                reserved        INTEGER NOT NULL DEFAULT 0,
                unit            TEXT NOT NULL DEFAULT 'pcs',
                reorder_level   INTEGER NOT NULL DEFAULT 0,
                cost_price      REAL,
                sell_price      REAL,
                status          TEXT NOT NULL DEFAULT 'active',
                updated_at      TEXT NOT NULL,
                FOREIGN KEY (warehouse_id) REFERENCES erp_warehouses(id) ON DELETE SET NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_inv2_tenant    ON erp_inventory(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_inv2_warehouse ON erp_inventory(warehouse_id)",
            "CREATE INDEX IF NOT EXISTS idx_inv2_sku       ON erp_inventory(sku)",

            # ----------------------------------------------------------------
            # CRM — contacts, leads, opportunities, activities
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS crm_contacts (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                external_id     TEXT,
                first_name      TEXT NOT NULL,
                last_name       TEXT,
                email           TEXT,
                phone           TEXT,
                company         TEXT,
                job_title       TEXT,
                source          TEXT,
                status          TEXT NOT NULL DEFAULT 'active',
                lead_score      INTEGER NOT NULL DEFAULT 0,
                tags_json       TEXT NOT NULL DEFAULT '[]',
                custom_fields   TEXT NOT NULL DEFAULT '{}',
                assigned_to     TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_crmc_tenant   ON crm_contacts(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_crmc_email    ON crm_contacts(email)",
            "CREATE INDEX IF NOT EXISTS idx_crmc_company  ON crm_contacts(company)",
            "CREATE INDEX IF NOT EXISTS idx_crmc_status   ON crm_contacts(status)",

            """
            CREATE TABLE IF NOT EXISTS crm_leads (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                external_id     TEXT,
                contact_id      TEXT,
                title           TEXT NOT NULL,
                source          TEXT,
                status          TEXT NOT NULL DEFAULT 'new',
                score           INTEGER NOT NULL DEFAULT 0,
                estimated_value REAL,
                currency        TEXT DEFAULT 'USD',
                assigned_to     TEXT,
                notes           TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                FOREIGN KEY (contact_id) REFERENCES crm_contacts(id) ON DELETE SET NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_crml_tenant   ON crm_leads(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_crml_contact  ON crm_leads(contact_id)",
            "CREATE INDEX IF NOT EXISTS idx_crml_status   ON crm_leads(status)",

            """
            CREATE TABLE IF NOT EXISTS crm_opportunities (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                external_id     TEXT,
                contact_id      TEXT,
                lead_id         TEXT,
                title           TEXT NOT NULL,
                stage           TEXT NOT NULL DEFAULT 'prospecting',
                value           REAL NOT NULL DEFAULT 0,
                currency        TEXT NOT NULL DEFAULT 'USD',
                probability     INTEGER NOT NULL DEFAULT 0,
                close_date      TEXT,
                assigned_to     TEXT,
                won_at          TEXT,
                lost_at         TEXT,
                lost_reason     TEXT,
                notes           TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_crmo_tenant   ON crm_opportunities(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_crmo_contact  ON crm_opportunities(contact_id)",
            "CREATE INDEX IF NOT EXISTS idx_crmo_stage    ON crm_opportunities(stage)",

            """
            CREATE TABLE IF NOT EXISTS crm_activities (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                contact_id      TEXT,
                opportunity_id  TEXT,
                activity_type   TEXT NOT NULL,
                subject         TEXT,
                description     TEXT,
                outcome         TEXT,
                scheduled_at    TEXT,
                completed_at    TEXT,
                created_by      TEXT,
                created_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_crma_tenant      ON crm_activities(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_crma_contact     ON crm_activities(contact_id)",
            "CREATE INDEX IF NOT EXISTS idx_crma_opportunity ON crm_activities(opportunity_id)",

            # ----------------------------------------------------------------
            # Workflow engine
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS workflow_definitions (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                name            TEXT NOT NULL,
                description     TEXT,
                trigger_type    TEXT NOT NULL DEFAULT 'manual',
                trigger_config  TEXT NOT NULL DEFAULT '{}',
                steps_json      TEXT NOT NULL DEFAULT '[]',
                status          TEXT NOT NULL DEFAULT 'draft',
                run_count       INTEGER NOT NULL DEFAULT 0,
                last_run        TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_wfdef_tenant ON workflow_definitions(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_wfdef_status ON workflow_definitions(status)",

            """
            CREATE TABLE IF NOT EXISTS workflow_executions (
                id              TEXT PRIMARY KEY,
                workflow_id     TEXT NOT NULL,
                tenant_id       TEXT NOT NULL,
                trigger_event   TEXT NOT NULL DEFAULT '{}',
                status          TEXT NOT NULL DEFAULT 'running',
                current_step    INTEGER NOT NULL DEFAULT 0,
                steps_result    TEXT NOT NULL DEFAULT '[]',
                started_at      TEXT NOT NULL,
                completed_at    TEXT,
                error           TEXT,
                FOREIGN KEY (workflow_id) REFERENCES workflow_definitions(id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_wfexe_workflow ON workflow_executions(workflow_id)",
            "CREATE INDEX IF NOT EXISTS idx_wfexe_tenant   ON workflow_executions(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_wfexe_status   ON workflow_executions(status)",

            # ----------------------------------------------------------------
            # Customer support
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS support_tickets (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                contact_id      TEXT,
                ticket_number   TEXT NOT NULL,
                subject         TEXT NOT NULL,
                description     TEXT,
                status          TEXT NOT NULL DEFAULT 'open',
                priority        TEXT NOT NULL DEFAULT 'normal',
                channel         TEXT NOT NULL DEFAULT 'email',
                assigned_to     TEXT,
                tags_json       TEXT NOT NULL DEFAULT '[]',
                sla_due_at      TEXT,
                first_response  TEXT,
                resolved_at     TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_tkt_tenant   ON support_tickets(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_tkt_status   ON support_tickets(status)",
            "CREATE INDEX IF NOT EXISTS idx_tkt_priority ON support_tickets(priority)",
            "CREATE INDEX IF NOT EXISTS idx_tkt_contact  ON support_tickets(contact_id)",

            """
            CREATE TABLE IF NOT EXISTS support_messages (
                id              TEXT PRIMARY KEY,
                ticket_id       TEXT NOT NULL,
                tenant_id       TEXT NOT NULL,
                sender_type     TEXT NOT NULL DEFAULT 'agent',
                sender_id       TEXT,
                content         TEXT NOT NULL,
                is_internal     INTEGER NOT NULL DEFAULT 0,
                attachments     TEXT NOT NULL DEFAULT '[]',
                created_at      TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES support_tickets(id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_msg_ticket  ON support_messages(ticket_id)",
            "CREATE INDEX IF NOT EXISTS idx_msg_tenant  ON support_messages(tenant_id)",

            # ----------------------------------------------------------------
            # Audit events (security)
            # ----------------------------------------------------------------
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id              TEXT PRIMARY KEY,
                tenant_id       TEXT NOT NULL,
                user_id         TEXT,
                action          TEXT NOT NULL,
                resource_type   TEXT,
                resource_id     TEXT,
                details_json    TEXT NOT NULL DEFAULT '{}',
                ip_address      TEXT,
                user_agent      TEXT,
                created_at      TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_audit_tenant   ON audit_events(tenant_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_action   ON audit_events(action)",
            "CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit_events(resource_type)",
            "CREATE INDEX IF NOT EXISTS idx_audit_created  ON audit_events(created_at)",
        ]

        conn = self._get_conn()
        try:
            for stmt in ddl_statements:
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            raise

        self._run_column_migrations(conn)

    def _run_column_migrations(self, conn: sqlite3.Connection) -> None:
        """
        Add columns that were introduced after the initial schema.
        SQLite does not support IF NOT EXISTS on ALTER TABLE, so each
        migration is wrapped in a try/except to be idempotent.
        """
        migrations = [
            # Add external_id to CRM tables (for connector sync deduplication)
            "ALTER TABLE crm_contacts     ADD COLUMN external_id TEXT",
            "ALTER TABLE crm_leads        ADD COLUMN external_id TEXT",
            "ALTER TABLE crm_opportunities ADD COLUMN external_id TEXT",
            # Indexes for external_id lookups
            "CREATE INDEX IF NOT EXISTS idx_crmc_external ON crm_contacts(external_id)",
            "CREATE INDEX IF NOT EXISTS idx_crml_external ON crm_leads(external_id)",
            "CREATE INDEX IF NOT EXISTS idx_crmo_external ON crm_opportunities(external_id)",
        ]
        for stmt in migrations:
            try:
                conn.execute(stmt)
                conn.commit()
            except sqlite3.OperationalError:
                # Column already exists or table doesn't exist yet — both are fine
                pass


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_panel_db_instance: Optional[ConnectorPanelDB] = None
_panel_db_lock = threading.Lock()


def get_panel_db() -> ConnectorPanelDB:
    """Return the module-level singleton ConnectorPanelDB instance."""
    global _panel_db_instance
    if _panel_db_instance is None:
        with _panel_db_lock:
            if _panel_db_instance is None:
                _panel_db_instance = ConnectorPanelDB()
                _panel_db_instance.create_tables()
    return _panel_db_instance


def init_panel_db(db_path: Optional[str] = None) -> ConnectorPanelDB:
    """
    Explicitly initialise (or re-initialise) the singleton with a specific path.
    Call this during app startup before the first request arrives.
    """
    global _panel_db_instance
    with _panel_db_lock:
        _panel_db_instance = ConnectorPanelDB(db_path)
        _panel_db_instance.create_tables()
    return _panel_db_instance
