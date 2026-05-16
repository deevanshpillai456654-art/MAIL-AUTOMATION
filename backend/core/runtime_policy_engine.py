"""
Runtime policy propagation and evaluation for rate limits and concurrency caps.

Policies are in-memory and scoped to this process unless wired to a shared store.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("runtime_policy")


class GlobalPolicyEngine:
    def __init__(self) -> None:
        self._policies: Dict[str, Dict[str, Any]] = {}
        self._versions: Dict[str, int] = {}
        self._updated_at: Dict[str, float] = {}
        self._lock = threading.RLock()

    def apply_policy(self, policy_name: str, policy: Dict[str, Any]) -> None:
        with self._lock:
            self._policies[policy_name] = dict(policy)
            self._versions[policy_name] = self._versions.get(policy_name, 0) + 1
            self._updated_at[policy_name] = time.time()
            logger.info("Policy %s applied version=%s", policy_name, self._versions[policy_name])

    def get_policy(self, policy_name: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            p = self._policies.get(policy_name)
            return dict(p) if p else None

    def policy_version(self, policy_name: str) -> int:
        with self._lock:
            return self._versions.get(policy_name, 0)

    def check_policy(self, policy_name: str, context: Dict[str, Any]) -> Tuple[bool, str]:
        policy = self.get_policy(policy_name)
        if not policy:
            return True, "no_policy"

        if "max_concurrent" in policy:
            max_concurrent = int(policy["max_concurrent"])
            current = int(context.get("current_concurrent", 0))
            if current >= max_concurrent:
                return False, f"max_concurrent_exceeded:{current}/{max_concurrent}"

        if "rate_limit" in policy:
            rate_limit = float(policy["rate_limit"])
            current_rate = float(context.get("rate", 0))
            if current_rate >= rate_limit:
                return False, f"rate_limit_exceeded:{current_rate}/{rate_limit}"

        return True, "allowed"


__all__ = ["GlobalPolicyEngine"]
