"""Enterprise policy evaluation engine."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple


@dataclass
class PolicyRule:
    name: str
    require: Dict[str, Any] = field(default_factory=dict)
    deny_if: Dict[str, Any] = field(default_factory=dict)


class EnterprisePolicyEngine:
    def __init__(self):
        self._rules: Dict[str, PolicyRule] = {}

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules[rule.name] = rule

    def enforce(self, policy: Dict[str, Any] | PolicyRule, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        rule = policy if isinstance(policy, PolicyRule) else PolicyRule(**policy)
        ok, reason = self.evaluate(rule, context or {})
        return {"status": "enforced" if ok else "denied", "allowed": ok, "reason": reason}

    def evaluate(self, rule: PolicyRule, context: Dict[str, Any]) -> Tuple[bool, str]:
        for key, expected in rule.require.items():
            if context.get(key) != expected:
                return False, f"missing_requirement:{key}"
        for key, denied in rule.deny_if.items():
            if context.get(key) == denied:
                return False, f"denied_by:{key}"
        return True, "allowed"


__all__ = ["EnterprisePolicyEngine", "PolicyRule"]
