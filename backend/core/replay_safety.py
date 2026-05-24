"""
Event Loop & Replay Elimination Engine
=====================================

Enterprise-grade replay safety system:
- event lineage DAG
- causal graph tracking
- replay boundary markers
- replay depth limits
- poison replay detection
- recursive retry detection
- distributed replay budget
- loop breaker engine
- replay quarantine
- event origin tagging

Prevents loops like:
Sync → AI → Replay → WebSocket → Offline Queue → Replay → Sync → infinite loop
"""

import asyncio
import hashlib
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("replay.safety")


class ReplayStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"


class ReplaySeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class EventLineage:
    """Event lineage for DAG tracking"""
    event_id: str
    topic: str
    parent_events: Set[str] = field(default_factory=set)
    child_events: Set[str] = field(default_factory=set)
    origin_service: str = ""
    origin_timestamp: float = field(default_factory=time.time)
    replay_count: int = 0
    max_replays: int = 3


@dataclass
class ReplayBoundary:
    """Replay boundary marker"""
    boundary_id: str
    event_id: str
    boundary_type: str  # "depth", "time", "fingerprint"
    limit: int
    created_at: float = field(default_factory=time.time)


@dataclass
class ReplayFingerprint:
    """Replay event fingerprint"""
    fingerprint: str
    hash: str
    first_seen: float
    last_seen: float
    occurrence_count: int = 1
    blocked: bool = False


@dataclass
class LoopDetectionEvent:
    """Loop detection event"""
    event_id: str
    loop_type: str
    severity: ReplaySeverity
    events_involved: List[str]
    detected_at: float = field(default_factory=time.time)
    action_taken: str = ""


# =============================================================================
# Event Lineage DAG
# =============================================================================

class EventLineageDAG:
    """
    Event lineage DAG for tracking causal relationships.
    Prevents infinite replay loops.
    """

    def __init__(self, max_depth: int = 10, max_nodes: int = 10000):
        self.max_depth = max_depth
        self.max_nodes = max_nodes

        self._events: Dict[str, EventLineage] = {}
        self._boundaries: Dict[str, ReplayBoundary] = {}
        self._fingerprints: Dict[str, ReplayFingerprint] = {}

        self._lock = threading.RLock()

        # Loop detection callbacks
        self._loop_callbacks: List[Callable] = []

        # Statistics
        self._loops_detected = 0
        self._replays_blocked = 0
        self._quarantined_events = 0

    def register_event(
        self,
        event_id: str,
        topic: str,
        parent_events: List[str] = None,
        origin_service: str = ""
    ) -> EventLineage:
        """Register event in lineage"""
        with self._lock:
            # Check if event exists
            if event_id in self._events:
                event = self._events[event_id]
                event.replay_count += 1
                return event

            # Check max nodes
            if len(self._events) >= self.max_nodes:
                self._prune_old_events()

            # Create lineage
            event = EventLineage(
                event_id=event_id,
                topic=topic,
                parent_events=set(parent_events or []),
                origin_service=origin_service,
                replay_count=0
            )

            self._events[event_id] = event

            # Update parent-child relationships
            for parent_id in event.parent_events:
                if parent_id in self._events:
                    self._events[parent_id].child_events.add(event_id)

            return event

    def create_boundary(
        self,
        event_id: str,
        boundary_type: str,
        limit: int
    ) -> ReplayBoundary:
        """Create replay boundary"""
        boundary = ReplayBoundary(
            boundary_id=f"boundary_{event_id}",
            event_id=event_id,
            boundary_type=boundary_type,
            limit=limit
        )

        self._boundaries[boundary.boundary_id] = boundary
        return boundary

    def compute_depth(self, event_id: str) -> int:
        """Compute event depth in DAG"""
        if event_id not in self._events:
            return 0

        event = self._events[event_id]

        if not event.parent_events:
            return 1

        max_parent_depth = 0
        for parent_id in event.parent_events:
            parent_depth = self.compute_depth(parent_id)
            max_parent_depth = max(max_parent_depth, parent_depth)

        return max_parent_depth + 1

    def check_replay_allowed(self, event_id: str) -> Tuple[bool, str]:
        """
        Check if replay is allowed for event.
        Returns (allowed, reason)
        """
        with self._lock:
            # Event exists check
            if event_id not in self._events:
                return True, "new_event"

            event = self._events[event_id]

            # Replay count check
            if event.replay_count >= event.max_replays:
                self._replays_blocked += 1
                return False, f"max_replays_exceeded:{event.replay_count}"

            # Depth check
            depth = self.compute_depth(event_id)
            if depth > self.max_depth:
                self._loops_detected += 1
                return False, f"max_depth_exceeded:{depth}"

            # Fingerprint check
            fingerprint = self._create_fingerprint(event)
            if fingerprint in self._fingerprints:
                fp = self._fingerprints[fingerprint]
                if fp.blocked:
                    self._replays_blocked += 1
                    return False, "fingerprint_blocked"

                # Duplicate detection
                if fp.occurrence_count > 10:
                    self._loops_detected += 1
                    return False, f"duplicate_pattern:{fp.occurrence_count}"

            return True, "allowed"

    def _create_fingerprint(self, event: EventLineage) -> str:
        """Create event fingerprint for duplicate detection"""
        content = f"{event.topic}:{','.join(sorted(event.parent_events))}"
        return hashlib.sha256(content.encode()).hexdigest()

    def _prune_old_events(self):
        """Prune old events to stay within limit"""
        if not self._events:
            return

        # Sort by timestamp (oldest first)
        sorted_events = sorted(
            self._events.items(),
            key=lambda x: x[1].origin_timestamp
        )

        # Remove oldest 20%
        remove_count = self.max_nodes // 5
        for event_id, event in sorted_events[:remove_count]:
            del self._events[event_id]

    def detect_loop(self, event_id: str) -> Optional[LoopDetectionEvent]:
        """Detect if current chain forms a loop"""
        if event_id not in self._events:
            return None

        event = self._events[event_id]

        # If we have more ancestors than depth limit, likely a loop
        visited = set()

        def has_cyclic_ancestor(eid: str, depth: int = 0) -> bool:
            if depth > self.max_depth:
                return True
            if eid in visited:
                return True
            if eid not in self._events:
                return False

            visited.add(eid)
            event = self._events[eid]

            for parent_id in event.parent_events:
                if has_cyclic_ancestor(parent_id, depth + 1):
                    return True

            return False

        if has_cyclic_ancestor(event_id):
            loop_event = LoopDetectionEvent(
                event_id=event_id,
                loop_type="cyclic_ancestry",
                severity=ReplaySeverity.CRITICAL,
                events_involved=list(visited),
                action_taken="quarantined"
            )

            self._loops_detected += 1
            self._quarantined_events += 1

            # Trigger callbacks
            for callback in self._loop_callbacks:
                try:
                    callback(loop_event)
                except Exception as e:
                    logger.error(f"Loop callback error: {e}")

            return loop_event

        return None

    def quarantine_event(self, event_id: str, reason: str) -> bool:
        """Quarantine problematic event"""
        with self._lock:
            if event_id not in self._events:
                return False

            event = self._events[event_id]

            # Create fingerprint and block
            fingerprint = self._create_fingerprint(event)

            if fingerprint not in self._fingerprints:
                self._fingerprints[fingerprint] = ReplayFingerprint(
                    fingerprint=fingerprint,
                    hash=hashlib.sha256(fingerprint.encode()).hexdigest(),
                    first_seen=time.time(),
                    last_seen=time.time(),
                    blocked=True
                )
            else:
                self._fingerprints[fingerprint].blocked = True
                self._fingerprints[fingerprint].last_seen = time.time()

            self._quarantined_events += 1

            logger.warning(f"Event quarantined: {event_id} - {reason}")

            return True

    def register_loop_callback(self, callback: Callable):
        """Register loop detection callback"""
        self._loop_callbacks.append(callback)

    def get_stats(self) -> Dict:
        """Get replay safety statistics"""
        with self._lock:
            return {
                "total_events": len(self._events),
                "boundaries": len(self._boundaries),
                "fingerprints": len(self._fingerprints),
                "loops_detected": self._loops_detected,
                "replays_blocked": self._replays_blocked,
                "quarantined": self._quarantined_events,
                "max_depth": self.max_depth
            }


# =============================================================================
# Replay Safety Engine
# =============================================================================

class ReplaySafetyEngine:
    """
    Enterprise replay safety engine.
    Eliminates replay loops and ensures safe event processing.
    """

    def __init__(self, config: Dict = None):
        self.config = config or {}

        self.max_replay_depth = self.config.get("max_replay_depth", 10)
        self.max_replay_count = self.config.get("max_replay_count", 3)
        self.replay_ttl = self.config.get("replay_ttl", 3600)  # 1 hour
        self.max_concurrent_replays = self.config.get("max_concurrent_replays", 100)

        # Create DAG
        self.dag = EventLineageDAG(
            max_depth=self.max_replay_depth,
            max_nodes=self.config.get("max_nodes", 10000)
        )

        # Active replays tracking
        self._active_replays: Dict[str, asyncio.Task] = {}
        self._replay_lock = asyncio.Lock()

        # Replay budget
        self._replay_budget: int = self.max_concurrent_replays
        self._budget_lock = asyncio.Lock()

        logger.info("ReplaySafetyEngine initialized")

    async def safe_replay_event(
        self,
        event_id: str,
        topic: str,
        handler: Callable,
        parent_events: List[str] = None,
        origin_service: str = "",
        **kwargs
    ) -> Any:
        """
        Safely replay event with full safety checks.
        Returns result or raises ReplaySafetyError
        """
        # Check replay budget
        async with self._budget_lock:
            if self._replay_budget <= 0:
                raise ReplaySafetyError("Replay budget exhausted")
            self._replay_budget -= 1

        try:
            # Register in lineage
            lineage = self.dag.register_event(
                event_id=event_id,
                topic=topic,
                parent_events=parent_events,
                origin_service=origin_service
            )

            # Check if replay allowed
            allowed, reason = self.dag.check_replay_allowed(event_id)

            if not allowed:
                self.dag.quarantine_event(event_id, reason)
                raise ReplaySafetyError(f"Replay blocked: {reason}")

            # Check for loops
            loop = self.dag.detect_loop(event_id)
            if loop:
                self.dag.quarantine_event(event_id, f"loop_detected:{loop.loop_type}")
                raise ReplaySafetyError(f"Loop detected: {loop.loop_type}")

            # Execute handler
            with self._replay_lock:
                self._active_replays[event_id] = asyncio.current_task()

            try:
                result = await handler(**kwargs)
                return result
            finally:
                with self._replay_lock:
                    self._active_replays.pop(event_id, None)

        finally:
            async with self._budget_lock:
                self._replay_budget += 1

    async def wait_for_replay_completion(self, timeout: float = 30.0):
        """Wait for all active replays to complete"""
        start = time.time()

        while True:
            async with self._replay_lock:
                active = len(self._active_replays)

            if active == 0:
                return

            if time.time() - start > timeout:
                logger.warning(f"Replay timeout: {active} still active")
                return

            await asyncio.sleep(0.1)

    def get_active_replays(self) -> List[str]:
        """Get list of active replay IDs"""
        with self._replay_lock:
            return list(self._active_replays.keys())

    def get_stats(self) -> Dict:
        """Get replay safety statistics"""
        return {
            **self.dag.get_stats(),
            "active_replays": len(self._active_replays),
            "replay_budget": self._replay_budget,
            "max_concurrent": self.max_concurrent_replays
        }


class ReplaySafetyError(Exception):
    """Replay safety error"""
    pass


# =============================================================================
# Distributed Replay Coordination
# =============================================================================

class DistributedReplayCoordinator:
    """
    Distributed replay coordination across multiple workers/nodes.
    """

    def __init__(self, redis_manager, node_id: str = None):
        self.redis = redis_manager
        self.node_id = node_id or f"node_{uuid.uuid4().hex[:8]}"

        self._active_replays_key = "replay:active"
        self._replay_locks_key = "replay:locks"
        self._budget_key = "replay:budget"

        logger.info(f"ReplayCoordinator initialized: {self.node_id}")

    async def acquire_replay_slot(self, event_id: str, timeout: float = 5.0) -> bool:
        """Acquire distributed replay slot"""
        key = f"{self._replay_locks_key}:{event_id}"

        # Try to acquire lock
        acquired = await self.redis.lock_acquire(key, timeout=int(timeout), worker_id=self.node_id)

        if acquired:
            # Decrement global budget
            await self.redis.incr(self._budget_key, -1)

        return acquired

    async def release_replay_slot(self, event_id: str):
        """Release distributed replay slot"""
        key = f"{self._replay_locks_key}:{event_id}"

        await self.redis.lock_release(key, self.node_id)
        await self.redis.incr(self._budget_key, 1)

    async def register_active_replay(self, event_id: str):
        """Register as active replay"""
        await self.redis.hset(
            self._active_replays_key,
            {event_id: json.dumps({
                "node_id": self.node_id,
                "started_at": time.time()
            })}
        )

    async def unregister_active_replay(self, event_id: str):
        """Unregister active replay"""
        await self.redis.hdel(self._active_replays_key, event_id)

    async def get_active_replays(self) -> Dict:
        """Get all active replays"""
        return await self.redis.hgetall(self._active_replays_key)

    async def get_replay_budget(self) -> int:
        """Get remaining replay budget"""
        value = await self.redis.get(self._budget_key)
        return int(value or 100)

    async def set_replay_budget(self, budget: int):
        """Set replay budget"""
        await self.redis.set(self._budget_key, str(budget))


# =============================================================================
# Global Instances
# =============================================================================

_replay_safety_engine: Optional[ReplaySafetyEngine] = None


def get_replay_safety_engine() -> ReplaySafetyEngine:
    """Get global replay safety engine"""
    global _replay_safety_engine
    if _replay_safety_engine is None:
        _replay_safety_engine = ReplaySafetyEngine()
    return _replay_safety_engine


__all__ = [
    "EventLineage",
    "EventLineageDAG",
    "ReplaySafetyEngine",
    "DistributedReplayCoordinator",
    "ReplaySafetyError",
    "get_replay_safety_engine"
]
