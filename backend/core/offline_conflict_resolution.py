"""
Offline Conflict Resolution Engine
===================================

Enterprise offline-first conflict resolution:
- CRDT (Conflict-free Replicated Data Types)
- Vector clocks for causality tracking
- Last-writer-wins with conflict detection
- Three-way merge for email modifications
- Operational transformation support
- Conflict quarantine and manual resolution
- Offline sync reconciliation
"""

import time
import hashlib
import logging
import asyncio
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from collections import deque, defaultdict
from copy import deepcopy
import uuid

logger = logging.getLogger("conflict_resolution")


class ConflictType(Enum):
    NONE = "none"
    UPDATE_UPDATE = "update_update"
    UPDATE_DELETE = "update_delete"
    DELETE_UPDATE = "delete_update"
    CREATE_CONFLICT = "create_conflict"


class ResolutionStrategy(Enum):
    LAST_WRITER_WINS = "last_writer_wins"
    LWW_WITH_VECTOR = "lww_with_vector"
    CRDT_MERGE = "crdt_merge"
    THREE_WAY_MERGE = "three_way_merge"
    MANUAL = "manual"


@dataclass
class VectorClock:
    """Vector clock for causality tracking"""
    clock: Dict[str, int] = field(default_factory=dict)
    
    def increment(self, node_id: str):
        """Increment node's logical timestamp"""
        self.clock[node_id] = self.clock.get(node_id, 0) + 1
    
    def merge(self, other: "VectorClock"):
        """Merge with other vector clock"""
        for node_id, timestamp in other.clock.items():
            self.clock[node_id] = max(self.clock.get(node_id, 0), timestamp)
    
    def compare(self, other: "VectorClock") -> str:
        """Compare vector clocks"""
        dominant = False
        recessive = False
        
        all_nodes = set(self.clock.keys()) | set(other.clock.keys())
        
        for node in all_nodes:
            self_ts = self.clock.get(node, 0)
            other_ts = other.clock.get(node, 0)
            
            if self_ts > other_ts:
                dominant = True
            elif self_ts < other_ts:
                recessive = True
        
        if dominant and recessive:
            return "concurrent"
        elif dominant:
            return "dominant"
        elif recessive:
            return "recessive"
        else:
            return "equal"
    
    def happens_before(self, other: "VectorClock") -> bool:
        """Check if this clock happens before other"""
        return other.compare(self) == "dominant"


@dataclass
class Operation:
    """Reconstructable operation"""
    operation_id: str
    entity_type: str
    entity_id: str
    operation_type: str
    timestamp: float
    vector_clock: VectorClock
    node_id: str
    payload: Dict[str, Any]
    checksum: str = ""
    
    def __post_init__(self):
        if not self.checksum:
            self.checksum = hashlib.sha256(
                f"{self.entity_id}:{self.operation_type}:{self.timestamp}:{self.payload}".encode()
            ).hexdigest()[:16]


@dataclass
class ConflictRecord:
    """Conflict resolution record"""
    conflict_id: str
    entity_type: str
    entity_id: str
    conflict_type: ConflictType
    local_operation: Optional[Operation]
    remote_operations: List[Operation]
    resolution_strategy: ResolutionStrategy
    resolved: bool = False
    resolution: Optional[Dict[str, Any]] = None
    resolved_at: Optional[float] = None


class CRDTSet:
    """Conflict-free Replicated Data Type Set"""
    
    def __init__(self, element_type: str = "string"):
        self._element_type = element_type
        self._add_set: Set[str] = set()
        self._remove_set: Set[str] = set()
        self._lock = threading.RLock()
    
    def add(self, element: str, node_id: str, timestamp: float) -> bool:
        """Add element to CRDT set"""
        with self._lock:
            if element in self._remove_set:
                self._remove_set.discard(element)
            
            if element not in self._add_set:
                self._add_set.add(element)
                return True
            return False
    
    def remove(self, element: str, node_id: str, timestamp: float):
        """Remove element from CRDT set"""
        with self._lock:
            self._remove_set.add(element)
    
    def merge(self, other: "CRDTSet"):
        """Merge with another CRDT set"""
        with self._lock:
            other._add_set = other._add_set - self._remove_set
            self._add_set = (self._add_set | other._add_set) - self._remove_set
            self._remove_set = self._remove_set | other._remove_set
    
    def contains(self, element: str) -> bool:
        """Check if element is in set"""
        with self._lock:
            return element in self._add_set and element not in self._remove_set
    
    def get_all(self) -> Set[str]:
        """Get all elements in set"""
        with self._lock:
            return self._add_set - self._remove_set
    
    def count(self) -> int:
        """Get count of elements"""
        return len(self.get_all())


class CRDTCounter:
    """Conflict-free Replicated Data Type Counter"""
    
    def __init__(self):
        self._increments: Dict[str, int] = {}
        self._decrements: Dict[str, int] = {}
        self._lock = threading.RLock()
    
    def increment(self, delta: int, node_id: str, timestamp: float):
        """Increment counter"""
        with self._lock:
            self._increments[node_id] = self._increments.get(node_id, 0) + delta
    
    def decrement(self, delta: int, node_id: str, timestamp: float):
        """Decrement counter"""
        with self._lock:
            self._decrements[node_id] = self._decrements.get(node_id, 0) + delta
    
    def merge(self, other: "CRDTCounter"):
        """Merge with another CRDT counter"""
        with self._lock:
            for node_id, value in other._increments.items():
                self._increments[node_id] = max(
                    self._increments.get(node_id, 0), value
                )
            for node_id, value in other._decrements.items():
                self._decrements[node_id] = max(
                    self._decrements.get(node_id, 0), value
                )
    
    def value(self) -> int:
        """Get counter value"""
        with self._lock:
            total_incr = sum(self._increments.values())
            total_decr = sum(self._decrements.values())
            return total_incr - total_decr


class CRDTRegister:
    """Conflict-free Replicated Data Type Register (LWW)"""
    
    def __init__(self):
        self._values: Dict[str, Tuple[float, Any]] = {}
        self._lock = threading.RLock()
    
    def set(self, value: Any, node_id: str, timestamp: float):
        """Set register value"""
        with self._lock:
            self._values[node_id] = (timestamp, value)
    
    def merge(self, other: "CRDTRegister"):
        """Merge with another CRDT register"""
        with self._lock:
            for node_id, (ts, value) in other._values.items():
                if node_id not in self._values or ts > self._values[node_id][0]:
                    self._values[node_id] = (ts, value)
    
    def get(self) -> Any:
        """Get current value"""
        with self._lock:
            if not self._values:
                return None
            
            latest = max(self._values.items(), key=lambda x: x[1][0])
            return latest[1][1]


class CRDTMap:
    """Conflict-free Replicated Data Type Map"""
    
    def __init__(self):
        self._registers: Dict[str, CRDTRegister] = {}
        self._lock = threading.RLock()
    
    def set(self, key: str, value: Any, node_id: str, timestamp: float):
        """Set value for key"""
        with self._lock:
            if key not in self._registers:
                self._registers[key] = CRDTRegister()
            self._registers[key].set(value, node_id, timestamp)
    
    def get(self, key: str) -> Any:
        """Get value for key"""
        with self._lock:
            if key not in self._registers:
                return None
            return self._registers[key].get()
    
    def merge(self, other: "CRDTMap"):
        """Merge with another CRDT map"""
        with self._lock:
            for key, register in other._registers.items():
                if key not in self._registers:
                    self._registers[key] = CRDTRegister()
                self._registers[key].merge(register)
    
    def keys(self) -> List[str]:
        """Get all keys"""
        with self._lock:
            return list(self._registers.keys())


class ConflictDetector:
    """Detect conflicts between offline operations"""
    
    def __init__(self):
        self._pending_operations: Dict[str, List[Operation]] = defaultdict(list)
        self._resolved_conflicts: List[ConflictRecord] = []
        self._lock = threading.RLock()
    
    def add_operation(self, operation: Operation):
        """Add operation to track"""
        with self._lock:
            key = f"{operation.entity_type}:{operation.entity_id}"
            self._pending_operations[key].append(operation)
    
    def detect_conflicts(self, 
                    entity_type: str, 
                    entity_id: str,
                    local_ops: List[Operation],
                    remote_ops: List[Operation]) -> ConflictRecord:
        """Detect conflicts between local and remote operations"""
        with self._lock:
            if not local_ops or not remote_ops:
                return ConflictRecord(
                    conflict_id=str(uuid.uuid4()),
                    entity_type=entity_type,
                    entity_id=entity_id,
                    conflict_type=ConflictType.NONE,
                    local_operation=None,
                    remote_operations=[],
                    resolution_strategy=ResolutionStrategy.LAST_WRITER_WINS
                )
            
            conflict_type = ConflictType.NONE
            
            local_types = set(op.operation_type for op in local_ops)
            remote_types = set(op.operation_type for op in remote_ops)
            
            if "CREATE" in local_types and "CREATE" in remote_types:
                conflict_type = ConflictType.CREATE_CONFLICT
            elif "UPDATE" in local_types and "UPDATE" in remote_types:
                conflict_type = ConflictType.UPDATE_UPDATE
            elif "UPDATE" in local_types and "DELETE" in remote_types:
                conflict_type = ConflictType.UPDATE_DELETE
            elif "DELETE" in local_types and "UPDATE" in remote_types:
                conflict_type = ConflictType.DELETE_UPDATE
            
            strategy = ResolutionStrategy.LAST_WRITER_WINS
            
            if conflict_type != ConflictType.NONE:
                strategy = self._select_strategy(conflict_type)
            
            return ConflictRecord(
                conflict_id=str(uuid.uuid4()),
                entity_type=entity_type,
                entity_id=entity_id,
                conflict_type=conflict_type,
                local_operation=local_ops[-1] if local_ops else None,
                remote_operations=remote_ops,
                resolution_strategy=strategy
            )
    
    def _select_strategy(self, conflict_type: ConflictType) -> ResolutionStrategy:
        """Select resolution strategy based on conflict type"""
        if conflict_type == ConflictType.UPDATE_UPDATE:
            return ResolutionStrategy.CRDT_MERGE
        elif conflict_type == ConflictType.CREATE_CONFLICT:
            return ResolutionStrategy.THREE_WAY_MERGE
        else:
            return ResolutionStrategy.LAST_WRITER_WINS


class ConflictResolver:
    """Resolve conflicts between operations"""
    
    def __init__(self):
        self._crdt_map = CRDTMap()
        self._conflict_detector = ConflictDetector()
        self._quarantine: Dict[str, ConflictRecord] = {}
        self._lock = threading.RLock()
    
    async def resolve_operations(self,
                            operations: List[Operation],
                            current_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Resolve a list of operations"""
        if not operations:
            return current_state or {}
        
        operations = sorted(operations, key=lambda op: op.vector_clock.clock)
        
        resolved = deepcopy(current_state) if current_state else {}
        
        with self._lock:
            for operation in operations:
                if operation.operation_type == "CREATE":
                    resolved = self._apply_create(operation, resolved)
                elif operation.operation_type == "UPDATE":
                    resolved = self._apply_update(operation, resolved)
                elif operation.operation_type == "DELETE":
                    resolved = self._apply_delete(operation, resolved)
            
            return resolved
    
    def _apply_create(self, operation: Operation, state: Dict[str, Any]) -> Dict[str, Any]:
        """Apply create operation"""
        new_state = deepcopy(state)
        new_state[operation.entity_id] = operation.payload
        return new_state
    
    def _apply_update(self, operation: Operation, state: Dict[str, Any]) -> Dict[str, Any]:
        """Apply update operation"""
        new_state = deepcopy(state)
        
        if operation.entity_id in new_state:
            new_state[operation.entity_id].update(operation.payload)
            new_state[operation.entity_id]["_last_modified"] = operation.timestamp
            new_state[operation.entity_id]["_modified_by"] = operation.node_id
        else:
            new_state[operation.entity_id] = operation.payload
        
        return new_state
    
    def _apply_delete(self, operation: Operation, state: Dict[str, Any]) -> Dict[str, Any]:
        """Apply delete operation"""
        new_state = deepcopy(state)
        new_state.pop(operation.entity_id, None)
        return new_state
    
    def resolve_lww(self,
                  local: Operation,
                  remote: Operation,
                  base: Optional[Operation] = None) -> Operation:
        """Resolve using Last Writer Wins"""
        if local.timestamp > remote.timestamp:
            return local
        else:
            return remote
    
    def resolve_with_vector_clock(self,
                               local: Operation,
                               remote: Operation) -> Operation:
        """Resolve using vector clock comparison"""
        result = local.vector_clock.compare(remote.vector_clock)
        
        if result == "dominant":
            return local
        elif result == "recessive":
            return remote
        else:
            return local if local.timestamp > remote.timestamp else remote
    
    def three_way_merge(self,
                       local: Dict[str, Any],
                       remote: Dict[str, Any],
                       base: Dict[str, Any]) -> Dict[str, Any]:
        """Three-way merge for email modifications"""
        merged = deepcopy(base)
        
        for key, local_value in local.items():
            base_value = base.get(key)
            remote_value = remote.get(key)
            
            if local_value == base_value:
                merged[key] = remote_value
            elif remote_value == base_value:
                merged[key] = local_value
            else:
                if isinstance(local_value, dict) and isinstance(remote_value, dict):
                    merged[key] = self.three_way_merge(local_value, remote_value, base_value)
                elif local.timestamp > remote.get("_last_modified", 0):
                    merged[key] = local_value
                else:
                    merged[key] = remote_value
        
        merged["_merged"] = True
        merged["_merge_timestamp"] = time.time()
        
        return merged
    
    def quarantine_conflict(self, conflict: ConflictRecord):
        """Quarantine conflict for manual resolution"""
        with self._lock:
            self._quarantine[conflict.conflict_id] = conflict
    
    def get_quarantined_conflicts(self) -> List[ConflictRecord]:
        """Get all quarantined conflicts"""
        with self._lock:
            return list(self._quarantine.values())
    
    def resolve_quarantined(self, conflict_id: str, resolution: Dict[str, Any]) -> bool:
        """Resolve a quarantined conflict"""
        with self._lock:
            if conflict_id in self._quarantine:
                self._quarantine[conflict_id].resolved = True
                self._quarantine[conflict_id].resolution = resolution
                self._quarantine[conflict_id].resolved_at = time.time()
                return True
            return False


class OfflineSyncCoordinator:
    """Coordinate offline sync with conflict resolution"""
    
    def __init__(self, node_id: str):
        self._node_id = node_id
        self._vector_clock = VectorClock()
        self._pending_local: List[Operation] = []
        self._conflict_resolver = ConflictResolver()
        self._sync_state = "idle"
        self._lock = threading.RLock()
    
    def create_operation(self,
                     entity_type: str,
                     entity_id: str,
                     operation_type: str,
                     payload: Dict[str, Any]) -> Operation:
        """Create a new operation"""
        self._vector_clock.increment(self._node_id)
        
        operation = Operation(
            operation_id=str(uuid.uuid4()),
            entity_type=entity_type,
            entity_id=entity_id,
            operation_type=operation_type,
            timestamp=time.time(),
            vector_clock=deepcopy(self._vector_clock),
            node_id=self._node_id,
            payload=payload
        )
        
        with self._lock:
            self._pending_local.append(operation)
        
        return operation
    
    async def sync_with_remote(self,
                               remote_operations: List[Operation],
                               current_state: Dict[str, Any]) -> Tuple[Dict[str, Any], List[ConflictRecord]]:
        """Sync local operations with remote"""
        with self._lock:
            if self._sync_state == "syncing":
                return current_state, []
            
            self._sync_state = "syncing"
        
        try:
            for op in remote_operations:
                self._vector_clock.merge(op.vector_clock)
            
            conflicts = []
            
            operations_by_entity = defaultdict(list)
            for op in self._pending_local:
                key = f"{op.entity_type}:{op.entity_id}"
                operations_by_entity[key].append(op)
            
            remote_by_entity = defaultdict(list)
            for op in remote_operations:
                key = f"{op.entity_type}:{op.entity_id}"
                remote_by_entity[key].append(op)
            
            for key, local_ops in operations_by_entity.items():
                remote_ops = remote_by_entity.get(key, [])
                
                conflict = self._conflict_resolver.detect_conflicts(
                    local_ops[0].entity_type,
                    local_ops[0].entity_id,
                    local_ops,
                    remote_ops
                )
                
                if conflict.conflict_type != ConflictType.NONE:
                    conflicts.append(conflict)
                    
                    if len(conflicts) <= 10:
                        self._conflict_resolver.quarantine_conflict(conflict)
            
            all_operations = self._pending_local + remote_operations
            
            resolved_state = await self._conflict_resolver.resolve_operations(
                all_operations, current_state
            )
            
            self._pending_local.clear()
            
            return resolved_state, conflicts
        
        finally:
            with self._lock:
                self._sync_state = "idle"
    
    def get_pending_count(self) -> int:
        """Get count of pending local operations"""
        with self._lock:
            return len(self._pending_local)
    
    def get_vector_clock(self) -> VectorClock:
        """Get current vector clock"""
        return deepcopy(self._vector_clock)


_global_coordinators: Dict[str, "OfflineSyncCoordinator"] = {}


def get_offline_coordinator(node_id: str) -> OfflineSyncCoordinator:
    """Get or create offline sync coordinator"""
    global _global_coordinators
    if node_id not in _global_coordinators:
        _global_coordinators[node_id] = OfflineSyncCoordinator(node_id)
    return _global_coordinators[node_id]


__all__ = [
    "ConflictType",
    "ResolutionStrategy",
    "VectorClock",
    "Operation",
    "ConflictRecord",
    "CRDTSet",
    "CRDTCounter",
    "CRDTRegister",
    "CRDTMap",
    "ConflictDetector",
    "ConflictResolver",
    "OfflineSyncCoordinator",
    "get_offline_coordinator"
]