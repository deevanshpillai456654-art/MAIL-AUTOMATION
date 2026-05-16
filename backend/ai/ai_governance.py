"""AI governance controls for classification output."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List

_ALLOWED_CATEGORIES = {
    "Finance", "OTP", "Clients", "Personal", "Promotions", "Spam", "Newsletters",
    "Trading", "Logistics", "Purchases", "HR", "Support", "Bills", "Security", "Urgent",
}


@dataclass
class GovernanceDecision:
    classification: Dict
    warnings: List[str] = field(default_factory=list)
    reviewed_at: float = field(default_factory=time.time)


class AIGovernanceEngine:
    """Validates and normalizes AI classification results before they reach users."""

    def __init__(self, min_auto_move_confidence: float = 0.95):
        self.min_auto_move_confidence = min_auto_move_confidence
        self.audit_log: List[GovernanceDecision] = []

    def govern(self, classification: Dict) -> Dict:
        result = dict(classification or {})
        warnings: List[str] = []
        category = result.get("category") or "Personal"
        if category not in _ALLOWED_CATEGORIES:
            warnings.append(f"unknown_category:{category}")
            result["category"] = "Personal"
        confidence = result.get("confidence", 0.0)
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
            warnings.append("invalid_confidence")
        result["confidence"] = min(1.0, max(0.0, confidence))
        if result.get("action") == "auto_move" and result["confidence"] < self.min_auto_move_confidence:
            result["action"] = "suggest"
            warnings.append("auto_move_downgraded")
        if "reason" in result:
            result["reason"] = self._redact(str(result["reason"]))
        decision = GovernanceDecision(result, warnings)
        self.audit_log.append(decision)
        return result

    def _redact(self, text: str) -> str:
        text = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[email]", text, flags=re.I)
        text = re.sub(r"\b\d{6,}\b", "[number]", text)
        return text

    def last_decision(self) -> GovernanceDecision | None:
        return self.audit_log[-1] if self.audit_log else None


__all__ = ["AIGovernanceEngine", "GovernanceDecision"]
