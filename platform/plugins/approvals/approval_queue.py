from __future__ import annotations
from typing import Dict, List
from sdk.models import ApprovalRequest, RiskLevel, WorkflowMode, utc_now

class ApprovalQueue:
    def __init__(self) -> None:
        self.items: Dict[str, ApprovalRequest] = {}

    def create(self, tenant_id: str, workflow_type: str, requester: str, payload: dict, risk_level: RiskLevel = RiskLevel.MEDIUM, mode: WorkflowMode = WorkflowMode.SEMI_AUTOMATIC, reason: str = "") -> ApprovalRequest:
        approval_id = f"appr-{tenant_id}-{len(self.items)+1}"
        req = ApprovalRequest(approval_id=approval_id, tenant_id=tenant_id, workflow_type=workflow_type, risk_level=risk_level, requester=requester, payload=payload, mode=mode, reason=reason)
        self.items[approval_id] = req
        return req

    def decide(self, approval_id: str, user_id: str, decision: str, reason: str = "") -> ApprovalRequest:
        req = self.items[approval_id]
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be approved or rejected")
        req.status = decision
        req.decided_by = user_id
        req.decided_at = utc_now()
        req.reason = reason or req.reason
        return req

    def pending(self, tenant_id: str) -> List[ApprovalRequest]:
        return [item for item in self.items.values() if item.tenant_id == tenant_id and item.status == "pending"]
