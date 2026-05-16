from __future__ import annotations
from typing import List, Dict, Any
TEMPLATES = [
    {"id":"invoice-forwarding", "name":"Invoice Forwarding", "category":"Finance Rules", "description":"Detect invoice emails, apply Finance label and forward to accounts."},
    {"id":"rfq-routing", "name":"RFQ Routing", "category":"RFQ Rules", "description":"Detect RFQs, apply RFQ label, forward to operations or sales and create lead."},
    {"id":"support-escalation", "name":"Support Escalation", "category":"Support Rules", "description":"Escalate urgent support emails and notify the support team."},
    {"id":"vip-client-handling", "name":"VIP Client Handling", "category":"VIP Client Rules", "description":"Prioritize VIP sender domains and route to assigned account owners."},
    {"id":"logistics-workflow", "name":"Logistics Workflow", "category":"Logistics Rules", "description":"Detect shipment, customs and freight inquiries and route to operations."},
]

def list_templates() -> List[Dict[str, Any]]: return list(TEMPLATES)
def get_template(template_id: str) -> Dict[str, Any] | None: return next((t for t in TEMPLATES if t["id"] == template_id), None)
