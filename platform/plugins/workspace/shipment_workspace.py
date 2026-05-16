from __future__ import annotations
from typing import Dict, List
from sdk.models import ShipmentReference, ShipmentWorkspace, TimelineItem, TenantContext, utc_now

class ShipmentWorkspaceService:
    def __init__(self) -> None:
        self._workspaces: Dict[str, ShipmentWorkspace] = {}

    def _key(self, tenant_id: str, shipment_key: str) -> str:
        return f"{tenant_id}:{shipment_key}"

    def get_or_create(self, context: TenantContext, shipment_key: str, references: ShipmentReference | None = None) -> ShipmentWorkspace:
        key = self._key(context.tenant_id, shipment_key)
        if key not in self._workspaces:
            self._workspaces[key] = ShipmentWorkspace(
                workspace_id=key,
                tenant_id=context.tenant_id,
                shipment_key=shipment_key,
                references=references or ShipmentReference(shipment_id=shipment_key),
            )
        return self._workspaces[key]

    def link_item(self, context: TenantContext, shipment_key: str, source: str, event_type: str, title: str, description: str = "", metadata: dict | None = None) -> TimelineItem:
        workspace = self.get_or_create(context, shipment_key)
        item = TimelineItem(
            item_id=f"{shipment_key}-{len(workspace.timeline)+1}",
            tenant_id=context.tenant_id,
            shipment_key=shipment_key,
            source=source,
            event_type=event_type,
            title=title,
            description=description,
            occurred_at=metadata.get("occurred_at", utc_now()) if metadata else utc_now(),
            metadata=metadata or {},
        )
        workspace.add_timeline(item)
        return item

    def search(self, context: TenantContext, query: str) -> List[ShipmentWorkspace]:
        query_l = query.lower()
        return [w for w in self._workspaces.values() if w.tenant_id == context.tenant_id and query_l in w.shipment_key.lower()]

    def dashboard(self, context: TenantContext) -> dict:
        items = [w for w in self._workspaces.values() if w.tenant_id == context.tenant_id]
        return {
            "active_shipments": len(items),
            "pending_approvals": sum(len(w.approvals) for w in items),
            "timeline_items": sum(len(w.timeline) for w in items),
            "updated_at": utc_now(),
        }
