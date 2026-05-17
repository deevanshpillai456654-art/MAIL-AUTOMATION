"""
ConnectorRegistry — discovers, stores, and instantiates connectors.
"""
from __future__ import annotations

import importlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Type

from .base import ConnectorBase
from .manifest import ConnectorManifest

log = logging.getLogger(__name__)

_CONNECTOR_MODULES = [
    "connectors_panel.connectors.salesforce.connector",
    "connectors_panel.connectors.hubspot.connector",
    "connectors_panel.connectors.zoho_crm.connector",
    "connectors_panel.connectors.shopify.connector",
    "connectors_panel.connectors.whatsapp.connector",
    "connectors_panel.connectors.gmail.connector",
    "connectors_panel.connectors.sap.connector",
    "connectors_panel.connectors.odoo.connector",
    "connectors_panel.connectors.erpnext.connector",
    "connectors_panel.connectors.quickbooks.connector",
    "connectors_panel.connectors.xero.connector",
    "connectors_panel.connectors.slack_enterprise.connector",
    "connectors_panel.connectors.teams.connector",
    "connectors_panel.connectors.shipping.fedex.connector",
    "connectors_panel.connectors.shipping.ups.connector",
    "connectors_panel.connectors.shipping.dhl.connector",
    "connectors_panel.connectors.shipping.delhivery.connector",
    "connectors_panel.connectors.shipping.shiprocket.connector",
    "connectors_panel.connectors.shipping.aftership.connector",
]


def _utc() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ConnectorRegistry:
    """
    Singleton registry.  Loads connector classes at startup and
    manages installed instances per tenant.
    """

    _instance: Optional["ConnectorRegistry"] = None

    def __init__(self) -> None:
        # connector_id -> ConnectorBase subclass
        self._classes: Dict[str, Type[ConnectorBase]] = {}
        self._db = None

    @classmethod
    def get(cls) -> "ConnectorRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def init(self, db) -> None:
        """Load connector classes and store db reference."""
        self._db = db
        self._discover()

    def _discover(self) -> None:
        for module_path in _CONNECTOR_MODULES:
            try:
                mod = importlib.import_module(module_path)
                for attr in dir(mod):
                    obj = getattr(mod, attr)
                    if (isinstance(obj, type)
                            and issubclass(obj, ConnectorBase)
                            and obj is not ConnectorBase
                            and hasattr(obj, "MANIFEST")):
                        cid = obj.MANIFEST.id
                        self._classes[cid] = obj
                        log.debug("Registered connector: %s", cid)
            except Exception as exc:
                log.warning("Could not load connector module %s: %s", module_path, exc)

    def list_manifests(self) -> List[Dict]:
        return [cls.MANIFEST.to_dict() for cls in self._classes.values()]

    def get_manifest(self, connector_id: str) -> Optional[ConnectorManifest]:
        cls = self._classes.get(connector_id)
        return cls.MANIFEST if cls else None

    def get_class(self, connector_id: str) -> Optional[Type[ConnectorBase]]:
        return self._classes.get(connector_id)

    def _load_config(self, row: dict) -> dict:
        from ...shared.utils import decrypt_config
        return decrypt_config(row.get("config_json", "") or "")

    def instantiate(self, instance_id: str, connector_id: str,
                    tenant_id: str, config: dict) -> Optional[ConnectorBase]:
        cls = self._classes.get(connector_id)
        if not cls:
            return None
        return cls(instance_id=instance_id, tenant_id=tenant_id,
                   config=config, db=self._db)

    # ------------------------------------------------------------------
    # Install / uninstall
    # ------------------------------------------------------------------

    async def install(self, connector_id: str, tenant_id: str,
                      config: dict, name: Optional[str] = None) -> str:
        cls = self._classes.get(connector_id)
        if not cls:
            raise ValueError(f"Unknown connector: {connector_id}")
        manifest = cls.MANIFEST
        instance_id = f"con_{uuid.uuid4().hex}"
        now = _utc()
        from ...shared.utils import encrypt_config
        self._db.execute(
            """INSERT INTO connectors
               (id, tenant_id, manifest_id, name, category, status, version,
                config_json, is_active, installed_at, last_heartbeat,
                health_score, failure_count, retry_count)
               VALUES (?,?,?,?,?,'active',?,?,1,?,?,1.0,0,0)""",
            (instance_id, tenant_id, connector_id,
             name or manifest.name, manifest.category, manifest.version,
             encrypt_config(config), now, now),
        )
        connector = cls(instance_id=instance_id, tenant_id=tenant_id,
                        config=config, db=self._db)
        await connector.on_install()
        log.info("Installed connector %s (%s) for tenant %s", connector_id, instance_id, tenant_id)
        return instance_id

    async def uninstall(self, instance_id: str, tenant_id: Optional[str] = None) -> None:
        if tenant_id:
            row = self._db.fetch_one(
                "SELECT * FROM connectors WHERE id=? AND tenant_id=?",
                (instance_id, tenant_id),
            )
        else:
            row = self._db.fetch_one("SELECT * FROM connectors WHERE id=?", (instance_id,))
        if not row:
            return
        config = self._load_config(row)
        connector_id = row.get("manifest_id") or row.get("category", "")
        cls = self._classes.get(connector_id) or self._find_class_by_instance(instance_id)
        if cls:
            c = cls(instance_id=instance_id, tenant_id=row["tenant_id"],
                    config=config, db=self._db)
            await c.on_uninstall()
        if tenant_id:
            self._db.execute(
                "DELETE FROM connectors WHERE id=? AND tenant_id=?",
                (instance_id, tenant_id),
            )
        else:
            self._db.execute("DELETE FROM connectors WHERE id=?", (instance_id,))
        log.info("Uninstalled connector instance %s", instance_id)

    def _find_class_by_instance(self, instance_id: str) -> Optional[Type[ConnectorBase]]:
        """Look up connector class by finding which class name matches the installed record."""
        row = self._db.fetch_one("SELECT name FROM connectors WHERE id=?", (instance_id,))
        if not row:
            return None
        name = row["name"].lower().replace(" ", "_")
        for cid, cls in self._classes.items():
            if cid.lower() == name or cls.MANIFEST.name.lower().replace(" ", "_") == name:
                return cls
        return None
