from __future__ import annotations
from typing import Dict

class OperationalTemplateService:
    DEFAULTS = {
        "shipment_update": "Dear {customer_name}, shipment {shipment_ref} status is {status}. ETA: {eta}.",
        "document_request": "Dear {customer_name}, please share {document_name} for shipment {shipment_ref}.",
        "delay_alert": "Update: shipment {shipment_ref} is delayed due to {reason}. Revised ETA: {eta}.",
        "pod_shared": "POD for shipment {shipment_ref} is ready. Please review the attached document.",
    }

    def list_templates(self) -> Dict[str, str]:
        return dict(self.DEFAULTS)

    def render(self, template_id: str, values: Dict[str, str]) -> str:
        template = self.DEFAULTS.get(template_id)
        if not template:
            raise KeyError(f"Unknown template: {template_id}")
        safe_values = {key: str(value) for key, value in values.items()}
        return template.format_map(DefaultDict(safe_values))

class DefaultDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"
