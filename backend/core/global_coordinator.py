"""
Routes work to logical shards and applies retry governance across subsystems.

Uses consistent hashing over a tenant or resource key. Shard maps are local until
synced from cluster membership via ClusterStateManager.
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .cluster_state_manager import ClusterStateManager
from .control_plane import ControlPlane, get_control_plane
from .runtime_policy_engine import GlobalPolicyEngine

logger = logging.getLogger("global_coordinator")


@dataclass
class RetryGovernance:
    max_attempts: int = 5
    base_delay_sec: float = 0.5
    max_delay_sec: float = 30.0
    jitter_ratio: float = 0.2

    def next_delay(self, attempt: int) -> float:
        exp = min(self.max_delay_sec, self.base_delay_sec * (2 ** max(0, attempt - 1)))
        jitter = exp * self.jitter_ratio * random.random()
        return min(self.max_delay_sec, exp + jitter)


@dataclass
class RoutedTarget:
    shard_id: int
    preferred_node_id: str
    failover_nodes: List[str] = field(default_factory=list)


class GlobalCoordinator:
    def __init__(
        self,
        control_plane: Optional[ControlPlane] = None,
        policy_engine: Optional[GlobalPolicyEngine] = None,
        shard_count: int = 64,
    ):
        self._cp = control_plane or get_control_plane()
        self._policy = policy_engine or self._cp.policy_engine
        self._shard_count = max(1, shard_count)
        self._retry = RetryGovernance()
        self._lock = threading.RLock()

    def shard_for_key(self, key: str) -> int:
        h = int(hashlib.sha256(key.encode("utf-8")).hexdigest(), 16)
        return h % self._shard_count

    def route(self, tenant_id: str, resource_key: str) -> RoutedTarget:
        composite = f"{tenant_id}:{resource_key}"
        shard = self.shard_for_key(composite)
        nodes = self._cp.cluster_state().get_active_nodes()
        if not nodes:
            nodes = [self._cp.node_id]
        ordered = sorted(nodes)
        preferred = ordered[shard % len(ordered)]
        failover = [n for n in ordered if n != preferred]
        return RoutedTarget(shard_id=shard, preferred_node_id=preferred, failover_nodes=failover)

    def allow_retry(self, policy_name: str, attempt: int, context: Dict[str, Any]) -> Tuple[bool, str]:
        ok, reason = self._policy.check_policy(policy_name, context)
        if not ok:
            return False, reason
        if attempt >= self._retry.max_attempts:
            return False, "max_attempts_exceeded"
        return True, "ok"

    def backoff_seconds(self, attempt: int) -> float:
        return self._retry.next_delay(attempt)

    def rebalance_hint(self, cluster: ClusterStateManager) -> Dict[str, Any]:
        active = cluster.get_active_nodes()
        return {
            "active_nodes": len(active),
            "shard_count": self._shard_count,
            "target_shards_per_node": self._shard_count // max(1, len(active)),
        }


def with_retry_governance(
    coordinator: GlobalCoordinator,
    policy_name: str,
    operation: Callable[[], Any],
    context_builder: Callable[[int], Dict[str, Any]],
) -> Any:
    last_exc: Optional[BaseException] = None
    for attempt in range(1, coordinator._retry.max_attempts + 1):
        ctx = context_builder(attempt)
        allowed, reason = coordinator.allow_retry(policy_name, attempt, ctx)
        if not allowed:
            raise RuntimeError(f"retry blocked: {reason}") from last_exc
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 — caller may wrap
            last_exc = exc
            delay = coordinator.backoff_seconds(attempt)
            logger.warning("operation attempt %s failed: %s; sleeping %.2fs", attempt, exc, delay)
            time.sleep(delay)
    if last_exc:
        raise last_exc
    raise RuntimeError("operation failed without exception")


__all__ = ["RetryGovernance", "RoutedTarget", "GlobalCoordinator", "with_retry_governance"]
