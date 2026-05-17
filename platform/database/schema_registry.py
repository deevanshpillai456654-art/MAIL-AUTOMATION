"""
SchemaRegistry — tracks table schemas contributed by plugins.

Plugins declare their required tables in plugin.json under "db_tables".
The registry validates those declarations and prevents naming collisions
with core tables.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

log = logging.getLogger(__name__)

CORE_TABLES: Set[str] = {
    "connectors", "tenants", "oauth_tokens", "events", "jobs",
    "shipments", "webhook_registrations", "connector_logs",
    "crm_contacts", "crm_leads", "erp_invoices", "erp_orders",
}


@dataclass
class TableSchema:
    table_name: str
    plugin_id:  str
    columns:    List[Dict]  # [{name, type, nullable, default}]
    indexes:    List[str] = field(default_factory=list)
    description: str = ""


class SchemaRegistry:
    """Thread-safe registry of plugin-declared table schemas."""

    _instance: Optional["SchemaRegistry"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "SchemaRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._schemas: Dict[str, TableSchema] = {}
        self._lock = threading.RLock()

    def register(self, schema: TableSchema) -> None:
        if schema.table_name in CORE_TABLES:
            raise ValueError(
                f"Plugin '{schema.plugin_id}' cannot override core table '{schema.table_name}'"
            )
        with self._lock:
            if schema.table_name in self._schemas:
                existing = self._schemas[schema.table_name]
                if existing.plugin_id != schema.plugin_id:
                    raise ValueError(
                        f"Table '{schema.table_name}' already registered by plugin '{existing.plugin_id}'"
                    )
            self._schemas[schema.table_name] = schema
        log.debug("SchemaRegistry: registered table=%s for plugin=%s", schema.table_name, schema.plugin_id)

    def deregister_plugin(self, plugin_id: str) -> None:
        with self._lock:
            keys = [k for k, v in self._schemas.items() if v.plugin_id == plugin_id]
            for k in keys:
                del self._schemas[k]

    def get_schema(self, table_name: str) -> Optional[TableSchema]:
        with self._lock:
            return self._schemas.get(table_name)

    def tables_for_plugin(self, plugin_id: str) -> List[str]:
        with self._lock:
            return [k for k, v in self._schemas.items() if v.plugin_id == plugin_id]
