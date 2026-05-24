"""Approval Agent – risk assessment and approval routing."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import BaseAgent

logger = logging.getLogger(__name__)


class ApprovalAgent(BaseAgent):
    agent_type = "approval"

    async def run(self, task_name: str, input_data: Dict[str, Any],
                  tenant_id: Optional[str] = None) -> Dict[str, Any]:
        if task_name == "assess_risk":
            return await self._assess_risk(input_data)
        elif task_name == "route":
            return self._route(input_data)
        return {"error": f"Unknown approval task: {task_name}"}

    async def _assess_risk(self, data: Dict) -> Dict:
        from ..ai.provider import get_registry
        context = data.get("context", "")
        amount = data.get("amount", 0)

        # Rule-based risk assessment
        risk = "low"
        reasons = []
        if amount > 50000:
            risk = "critical"
            reasons.append(f"High value transaction: {amount}")
        elif amount > 10000:
            risk = "high"
            reasons.append(f"Significant amount: {amount}")
        elif amount > 1000:
            risk = "medium"
            reasons.append(f"Moderate amount: {amount}")

        # AI-enhanced assessment
        try:
            registry = get_registry()
            prov = registry.get()
            ai_result = await prov.classify(
                f"Transaction context: {context}\nAmount: {amount}",
                ["low_risk", "medium_risk", "high_risk", "critical_risk"],
            )
            ai_risk = ai_result.replace("_risk", "")
            # Take the higher risk level
            levels = ["low", "medium", "high", "critical"]
            if levels.index(ai_risk) > levels.index(risk):
                risk = ai_risk
                reasons.append(f"AI assessment: {ai_risk}")
        except Exception as _e:
            logger.warning("AI risk assessment failed, using rule-based result: %s", _e)

        return {"risk_level": risk, "reasons": reasons, "requires_approval": risk != "low"}

    def _route(self, data: Dict) -> Dict:
        risk = data.get("risk_level", "low")
        routing = {
            "low": {"assignee": None, "auto_approve": True},
            "medium": {"assignee_group": "team_lead", "auto_approve": False},
            "high": {"assignee_group": "manager", "auto_approve": False, "escalate_after_minutes": 60},
            "critical": {"assignee_group": "director", "auto_approve": False, "escalate_after_minutes": 30},
        }
        return routing.get(risk, routing["medium"])
