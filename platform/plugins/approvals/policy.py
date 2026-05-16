from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Set
from sdk.models import RiskLevel, WorkflowMode, TenantContext
from sdk.exceptions import AutomationBlocked

HIGH_RISK_DOCS = {"invoice", "customs_document", "payment_document", "financial_document", "bill_of_entry"}
MEDIUM_RISK_DOCS = {"awb", "bl", "shipment_copy", "shipping_document"}
LOW_RISK_DOCS = {"shipment_status", "eta_update", "tracking_milestone", "pod_notification"}

@dataclass
class AutomationPolicy:
    tenant_id: str
    default_mode: WorkflowMode = WorkflowMode.SEMI_AUTOMATIC
    full_auto_enabled_workflows: Set[str] = field(default_factory=set)
    trusted_customers: Set[str] = field(default_factory=set)
    manual_only_customers: Set[str] = field(default_factory=set)
    high_risk_requires_approval: bool = True

class AutomationPolicyEngine:
    def __init__(self) -> None:
        self.policies: Dict[str, AutomationPolicy] = {}

    def get_policy(self, tenant_id: str) -> AutomationPolicy:
        if tenant_id not in self.policies:
            self.policies[tenant_id] = AutomationPolicy(tenant_id=tenant_id)
        return self.policies[tenant_id]

    def classify_document(self, document_type: str) -> RiskLevel:
        doc = (document_type or "").lower()
        if doc in HIGH_RISK_DOCS:
            return RiskLevel.HIGH
        if doc in MEDIUM_RISK_DOCS:
            return RiskLevel.MEDIUM
        if doc in LOW_RISK_DOCS:
            return RiskLevel.LOW
        return RiskLevel.MEDIUM

    def evaluate(self, context: TenantContext, workflow_type: str, document_type: str | None = None, customer_id: str | None = None) -> dict:
        policy = self.get_policy(context.tenant_id)
        risk = self.classify_document(document_type or workflow_type)
        if customer_id and customer_id in policy.manual_only_customers:
            return {"decision": "approval_required", "mode": "manual", "risk": risk.value, "reason": "customer manual-only"}
        if risk == RiskLevel.HIGH and policy.high_risk_requires_approval:
            return {"decision": "approval_required", "mode": "semi_automatic", "risk": risk.value, "reason": "high-risk document"}
        if workflow_type in policy.full_auto_enabled_workflows and (risk == RiskLevel.LOW or customer_id in policy.trusted_customers):
            return {"decision": "allowed", "mode": "full_automatic", "risk": risk.value, "reason": "explicitly enabled"}
        return {"decision": "approval_required", "mode": policy.default_mode.value, "risk": risk.value, "reason": "default human-control policy"}

    def enforce(self, context: TenantContext, workflow_type: str, document_type: str | None = None, customer_id: str | None = None) -> dict:
        result = self.evaluate(context, workflow_type, document_type, customer_id)
        if result["decision"] != "allowed":
            raise AutomationBlocked(result["reason"])
        return result
