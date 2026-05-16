"""Replay lineage DAG with recursion and amplification protection."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple


@dataclass(frozen=True)
class ReplayScope:
    tenant_id: str = "local"
    account_id: str = "default"
    stream_id: str = "mailbox"

    @property
    def key(self) -> str:
        return f"{self.tenant_id}:{self.account_id}:{self.stream_id}"


@dataclass
class LineageNode:
    event_id: str
    scope: ReplayScope
    parents: Set[str] = field(default_factory=set)
    children: Set[str] = field(default_factory=set)
    replay_count: int = 0
    created_at: float = field(default_factory=time.time)
    quarantined: bool = False
    quarantine_reason: str = ""


class ReplayLineageDAG:
    """Tracks replay causality and blocks recursive replay loops."""

    def __init__(self, max_depth: int = 25, max_replays_per_event: int = 3, max_children_per_event: int = 250):
        self.max_depth = max(1, max_depth)
        self.max_replays_per_event = max(1, max_replays_per_event)
        self.max_children_per_event = max(1, max_children_per_event)
        self._nodes: Dict[str, LineageNode] = {}
        self._lock = threading.RLock()

    def register_event(
        self,
        event_id: str,
        parents: Optional[Iterable[str]] = None,
        scope: Optional[ReplayScope] = None,
        replay: bool = False,
    ) -> Tuple[bool, str]:
        parents_set = set(parents or [])
        scope = scope or ReplayScope()
        with self._lock:
            node = self._nodes.get(event_id)
            if node is None:
                node = LineageNode(event_id=event_id, scope=scope, parents=parents_set)
                self._nodes[event_id] = node
            else:
                node.parents.update(parents_set)
                if replay:
                    node.replay_count += 1

            for parent_id in parents_set:
                parent = self._nodes.setdefault(parent_id, LineageNode(event_id=parent_id, scope=scope))
                parent.children.add(event_id)
                if len(parent.children) > self.max_children_per_event:
                    node.quarantined = True
                    node.quarantine_reason = "replay_amplification"
                    return False, "replay_amplification"

            if node.replay_count > self.max_replays_per_event:
                node.quarantined = True
                node.quarantine_reason = "max_replays_exceeded"
                return False, "max_replays_exceeded"

            if self._has_cycle(event_id):
                node.quarantined = True
                node.quarantine_reason = "lineage_cycle"
                return False, "lineage_cycle"

            depth = self.depth(event_id)
            if depth > self.max_depth:
                node.quarantined = True
                node.quarantine_reason = f"max_depth_exceeded:{depth}"
                return False, node.quarantine_reason

            return True, "accepted"

    def _has_cycle(self, event_id: str) -> bool:
        visiting: Set[str] = set()
        visited: Set[str] = set()

        def visit(node_id: str) -> bool:
            if node_id in visiting:
                return True
            if node_id in visited:
                return False
            visiting.add(node_id)
            for parent_id in self._nodes.get(node_id, LineageNode(node_id, ReplayScope())).parents:
                if visit(parent_id):
                    return True
            visiting.remove(node_id)
            visited.add(node_id)
            return False

        return visit(event_id)

    def depth(self, event_id: str) -> int:
        def compute(node_id: str, seen: Set[str]) -> int:
            if node_id in seen:
                return self.max_depth + 1
            node = self._nodes.get(node_id)
            if not node or not node.parents:
                return 1
            seen.add(node_id)
            try:
                return 1 + max(compute(parent, seen) for parent in node.parents)
            finally:
                seen.discard(node_id)
        return compute(event_id, set())

    def lineage(self, event_id: str) -> List[str]:
        ordered: List[str] = []
        seen: Set[str] = set()
        def walk(node_id: str) -> None:
            if node_id in seen:
                return
            seen.add(node_id)
            for parent in sorted(self._nodes.get(node_id, LineageNode(node_id, ReplayScope())).parents):
                walk(parent)
            ordered.append(node_id)
        with self._lock:
            walk(event_id)
        return ordered

    def quarantined(self) -> List[LineageNode]:
        with self._lock:
            return [node for node in self._nodes.values() if node.quarantined]

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "nodes": len(self._nodes),
                "quarantined": sum(1 for node in self._nodes.values() if node.quarantined),
                "edges": sum(len(node.parents) for node in self._nodes.values()),
            }


__all__ = ["ReplayScope", "LineageNode", "ReplayLineageDAG"]
