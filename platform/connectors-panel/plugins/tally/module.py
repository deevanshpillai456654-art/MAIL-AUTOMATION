from __future__ import annotations

from typing import Any

from ...sdk.plugin_sdk import ConnectorPlugin


class TallyConnector(ConnectorPlugin):
    @property
    def plugin_id(self) -> str:
        return "tally_connector"

    @property
    def name(self) -> str:
        return "Tally"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def category(self) -> str:
        return "accounting"

    def health_check(self, tenant_id: str) -> dict[str, Any]:
        return {
            "status": "ok",
            "message": "Tally connector module loaded",
            "tenant_id": tenant_id,
            "capabilities": ["xml_api", "multi_company", "gst", "inventory", "workflows"],
        }

    def test_connection(self, tenant_id: str, config: dict[str, Any]) -> bool:
        host = str(config.get("host") or "").strip()
        port = int(config.get("port") or 0)
        company = str(config.get("company_name") or "").strip()
        return bool(host and 0 < port <= 65535 and company)


Plugin = TallyConnector
