"""Platform Database — plugin repositories, schema registry, migrations."""
from .plugin_repository import PluginRepository, QueryBuilder
from .tenant_repository import TenantRepository
from .schema_registry   import SchemaRegistry, TableSchema
from .migration_manager import MigrationManager

__all__ = [
    "PluginRepository",
    "QueryBuilder",
    "TenantRepository",
    "SchemaRegistry",
    "TableSchema",
    "MigrationManager",
]
