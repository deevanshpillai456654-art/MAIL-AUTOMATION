"""
Cluster membership and heartbeat state for the in-process control plane.

Tracks node liveness and leader hints. Multi-node consistency requires an
external consensus store; this module provides the local coordinator view.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("cluster_state")


class NodeState(Enum):
    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    LEADER = "leader"
    SHUTDOWN = "shutdown"


@dataclass
class ClusterNode:
    node_id: str
    hostname: str
    state: NodeState = NodeState.FOLLOWER
    last_heartbeat: float = 0.0
    votes: int = 0
    term: int = 0

    def __post_init__(self) -> None:
        if self.last_heartbeat == 0.0:
            self.last_heartbeat = time.time()


class ClusterStateManager:
    def __init__(self, node_id: str):
        self._node_id = node_id
        self._nodes: Dict[str, ClusterNode] = {}
        self._leader_id: Optional[str] = None
        self._lock = threading.RLock()

    def register_node(self, node_id: str, hostname: str) -> None:
        with self._lock:
            self._nodes[node_id] = ClusterNode(node_id=node_id, hostname=hostname)
            logger.debug("Registered cluster node %s (%s)", node_id, hostname)

    def unregister_node(self, node_id: str) -> None:
        with self._lock:
            self._nodes.pop(node_id, None)

    def update_heartbeat(self, node_id: str) -> None:
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].last_heartbeat = time.time()

    def get_active_nodes(self, max_age: float = 30.0) -> List[str]:
        now = time.time()
        with self._lock:
            return [
                nid
                for nid, node in self._nodes.items()
                if now - node.last_heartbeat < max_age
            ]

    def get_leader(self) -> Optional[str]:
        return self._leader_id

    def set_leader(self, leader_id: str) -> None:
        with self._lock:
            self._leader_id = leader_id
            for node_id, node in self._nodes.items():
                node.state = NodeState.LEADER if node_id == leader_id else NodeState.FOLLOWER

    def local_node_id(self) -> str:
        return self._node_id


__all__ = ["NodeState", "ClusterNode", "ClusterStateManager"]
