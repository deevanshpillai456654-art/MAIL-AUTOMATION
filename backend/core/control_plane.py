"""
Unified control plane: leader hints, locks, leases, cluster view, and policies.

In-process coordination suits the local-first service. For multi-instance HA,
back locks and leases with a shared atomic store and run an external election.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .cluster_state_manager import ClusterStateManager, NodeState
from .lease_manager import DistributedLockManager, LeaseManager, LockType
from .runtime_policy_engine import GlobalPolicyEngine

logger = logging.getLogger("control_plane")


class LeaderElection:
    """Single-process leader election with configurable quorum (votes required)."""

    def __init__(self, node_id: str, election_timeout: float = 5.0, quorum_votes: int = 1):
        self._node_id = node_id
        self._election_timeout = election_timeout
        self._quorum_votes = max(1, quorum_votes)
        self._current_state = NodeState.FOLLOWER
        self._term = 0
        self._votes: Set[str] = set()
        self._voted_for: Optional[str] = None
        self._last_election = 0.0
        self._lock = threading.RLock()

    def start_election(self) -> bool:
        with self._lock:
            self._current_state = NodeState.CANDIDATE
            self._term += 1
            self._votes = {self._node_id}
            self._voted_for = self._node_id
            self._last_election = time.time()
            return True

    def request_vote(self, candidate_id: str, term: int) -> Tuple[bool, int]:
        with self._lock:
            if term > self._term:
                self._term = term
                self._current_state = NodeState.FOLLOWER
                self._voted_for = None

            if self._current_state == NodeState.LEADER:
                return False, self._term

            can_vote = self._voted_for is None or self._voted_for == candidate_id
            if can_vote:
                self._voted_for = candidate_id
                return True, self._term
            return False, self._term

    def receive_vote(self, voter_id: str) -> bool:
        with self._lock:
            if self._current_state != NodeState.CANDIDATE:
                return False
            self._votes.add(voter_id)
            if len(self._votes) >= self._quorum_votes:
                self._current_state = NodeState.LEADER
                return True
            return False

    def get_state(self) -> NodeState:
        return self._current_state

    def get_term(self) -> int:
        return self._term

    def demote_to_follower(self) -> None:
        with self._lock:
            self._current_state = NodeState.FOLLOWER


class ControlPlane:
    def __init__(self, node_id: str, quorum_votes: int = 1):
        self._node_id = node_id
        self._leader_election = LeaderElection(node_id, quorum_votes=quorum_votes)
        self._lock_manager = DistributedLockManager()
        self._lease_manager = LeaseManager()
        self._cluster_state = ClusterStateManager(node_id)
        self._policy_engine = GlobalPolicyEngine()
        self._running = True
        self._election_task: Optional[asyncio.Task] = None
        logger.info("Control plane initialized node_id=%s", node_id)

    async def start(self) -> None:
        self._running = True
        self._election_task = asyncio.create_task(self._election_loop())
        logger.info("Control plane started %s", self._node_id)

    async def stop(self) -> None:
        self._running = False
        if self._election_task:
            self._election_task.cancel()
            try:
                await self._election_task
            except asyncio.CancelledError:
                pass
        logger.info("Control plane stopped %s", self._node_id)

    async def _election_loop(self) -> None:
        while self._running:
            await asyncio.sleep(1.0)
            if self._leader_election.get_state() == NodeState.FOLLOWER:
                if time.time() - self._leader_election._last_election > self._leader_election._election_timeout:
                    self._leader_election.start_election()

    async def become_leader(self) -> bool:
        return self._leader_election.start_election()

    async def acquire_lock(
        self,
        lock_type: LockType,
        resource_id: str,
        ttl_seconds: int = 60,
    ) -> Optional[str]:
        return await self._lock_manager.acquire_lock(lock_type, resource_id, self._node_id, ttl_seconds)

    async def release_lock(self, lock_id: str) -> bool:
        return await self._lock_manager.release_lock(lock_id, self._node_id)

    async def acquire_lease(self, resource_type: str, resource_id: str, ttl_seconds: int = 60) -> Optional[str]:
        return await self._lease_manager.acquire_lease(resource_type, resource_id, self._node_id, ttl_seconds)

    async def renew_lease(self, lease_id: str, ttl_seconds: int = 60) -> bool:
        return await self._lease_manager.renew_lease(lease_id, self._node_id, ttl_seconds)

    async def release_lease(self, lease_id: str) -> bool:
        return await self._lease_manager.release_lease(lease_id, self._node_id)

    def get_orphaned_resources(self) -> List[str]:
        return self._lease_manager.get_orphaned_leases()

    def sweep_stale_leases(self) -> List[str]:
        return self._lease_manager.reclaim_expired()

    def sweep_expired_locks(self) -> int:
        return self._lock_manager.sweep_expired_locks()

    def apply_policy(self, policy_name: str, policy: Dict[str, Any]) -> None:
        self._policy_engine.apply_policy(policy_name, policy)

    def check_policy(self, policy_name: str, context: Dict[str, Any]) -> Tuple[bool, str]:
        return self._policy_engine.check_policy(policy_name, context)

    def cluster_state(self) -> ClusterStateManager:
        return self._cluster_state

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def policy_engine(self) -> GlobalPolicyEngine:
        return self._policy_engine

    def get_cluster_health(self) -> Dict[str, Any]:
        return {
            "node_id": self._node_id,
            "state": self._leader_election.get_state().value,
            "term": self._leader_election.get_term(),
            "active_nodes": len(self._cluster_state.get_active_nodes()),
            "leader": self._cluster_state.get_leader(),
        }


_global_control_plane: Optional[ControlPlane] = None


def get_control_plane(node_id: str = "default") -> ControlPlane:
    global _global_control_plane
    if _global_control_plane is None:
        _global_control_plane = ControlPlane(node_id)
    return _global_control_plane


__all__ = [
    "NodeState",
    "LeaderElection",
    "ControlPlane",
    "get_control_plane",
    "LockType",
]
