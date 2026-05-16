"""
Event Store Hardening - Compaction & Snapshots
=============================================

Event compaction:
- Event compression
- Snapshotting
- Partitioning
- Archival tiers
- Retention policies
"""

import time
import hashlib
import logging
import asyncio
import threading
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum
from collections import deque, defaultdict
import json
import zlib
import uuid

logger = logging.getLogger("event_hardening")


class RetentionPolicy(Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    ARCHIVE = "archive"


@dataclass
class EventSnapshot:
    """Event snapshot"""
    snapshot_id: str
    partition_key: str
    sequence_start: int
    sequence_end: int
    event_count: int
    checksum: str
    created_at: float = field(default_factory=time.time)


@dataclass
class RetentionConfig:
    """Retention configuration"""
    hot_days: int = 7
    warm_days: int = 30
    cold_days: int = 90
    archive_days: int = 365


class EventCompactor:
    """Event compaction engine"""
    
    def __init__(self):
        self._snapshots: Dict[str, EventSnapshot] = {}
        self._retention = RetentionConfig()
        self._lock = threading.RLock()
        
        logger.info("Event compactor initialized")
    
    def create_snapshot(self, 
                      partition_key: str,
                      events: List[Dict[str, Any]],
                      sequence_start: int,
                      sequence_end: int) -> str:
        """Create snapshot of events"""
        snapshot_id = f"snap_{uuid.uuid4().hex[:12]}"
        
        compressed = zlib.compress(json.dumps(events).encode())
        
        checksum = hashlib.sha256(compressed).hexdigest()
        
        snapshot = EventSnapshot(
            snapshot_id=snapshot_id,
            partition_key=partition_key,
            sequence_start=sequence_start,
            sequence_end=sequence_end,
            event_count=len(events),
            checksum=checksum
        )
        
        with self._lock:
            self._snapshots[snapshot_id] = snapshot
        
        logger.info(f"Snapshot created: {snapshot_id} ({len(events)} events)")
        
        return snapshot_id
    
    def get_snapshot(self, snapshot_id: str) -> Optional[EventSnapshot]:
        """Get snapshot metadata"""
        return self._snapshots.get(snapshot_id)
    
    def compact_events(self, events: List[Dict[str, Any]]) -> bytes:
        """Compress events"""
        return zlib.compress(json.dumps(events).encode())
    
    def decompress_events(self, data: bytes) -> List[Dict[str, Any]]:
        """Decompress events"""
        return json.loads(zlib.decompress(data).decode())


class EventPartitioner:
    """Event partitioning"""
    
    def __init__(self, partition_count: int = 100):
        self._partition_count = partition_count
        self._partitions: Dict[int, List[str]] = defaultdict(list)
        self._lock = threading.RLock()
        
        logger.info(f"Event partitioner initialized: {partition_count} partitions")
    
    def get_partition(self, key: str) -> int:
        """Get partition for key"""
        hash_val = int(hashlib.sha256(key.encode()).hexdigest(), 16)
        return hash_val % self._partition_count
    
    def assign_partition(self, event_id: str, key: str) -> int:
        """Assign event to partition"""
        partition = self.get_partition(key)
        
        with self._lock:
            self._partitions[partition].append(event_id)
        
        return partition
    
    def get_partition_events(self, partition: int) -> List[str]:
        """Get events in partition"""
        with self._lock:
            return list(self._partitions.get(partition, []))


class RetentionManager:
    """Event retention management"""
    
    def __init__(self, config: Optional[RetentionConfig] = None):
        self._config = config or RetentionConfig()
        self._event_tiers: Dict[str, RetentionPolicy] = {}
        self._lock = threading.RLock()
        
        logger.info("Retention manager initialized")
    
    def classify_event(self, event_age_days: int) -> RetentionPolicy:
        """Classify event by age"""
        if event_age_days <= self._config.hot_days:
            return RetentionPolicy.HOT
        elif event_age_days <= self._config.warm_days:
            return RetentionPolicy.WARM
        elif event_age_days <= self._config.cold_days:
            return RetentionPolicy.COLD
        else:
            return RetentionPolicy.ARCHIVE
    
    def should_delete(self, event_age_days: int) -> bool:
        """Check if event should be deleted"""
        return event_age_days > self._config.archive_days
    
    def get_events_to_archive(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get events to archive"""
        archive = []
        
        for event in events:
            age_days = (time.time() - event.get("timestamp", 0)) / 86400
            
            if self.should_delete(age_days):
                continue
            
            tier = self.classify_event(int(age_days))
            event["_retention_tier"] = tier.value
            archive.append(event)
        
        return archive


class EventStoreHardening:
    """Main event store hardening"""
    
    def __init__(self):
        self._compactor = EventCompactor()
        self._partitioner = EventPartitioner()
        self._retention = RetentionManager()
        self._lock = threading.RLock()
        
        logger.info("Event store hardening initialized")
    
    def process_events(self, 
                     partition_key: str,
                     events: List[Dict[str, Any]],
                     sequence_start: int,
                     sequence_end: int) -> str:
        """Process and harden events"""
        archived = self._retention.get_events_to_archive(events)
        
        snapshot_id = self._compactor.create_snapshot(
            partition_key, archived, sequence_start, sequence_end
        )
        
        partition = self._partitioner.assign_partition(
            f"{partition_key}:{sequence_start}", partition_key
        )
        
        return snapshot_id
    
    def get_stats(self) -> Dict[str, Any]:
        """Get hardening stats"""
        return {
            "snapshots": len(self._compactor._snapshots),
            "partitions": self._partitioner._partition_count,
            "retention": {
                "hot_days": self._retention._config.hot_days,
                "warm_days": self._retention._config.warm_days,
                "cold_days": self._retention._config.cold_days,
                "archive_days": self._retention._config.archive_days
            }
        }


_global_hardening: Optional[EventStoreHardening] = None


def get_event_hardening() -> EventStoreHardening:
    global _global_hardening
    if _global_hardening is None:
        _global_hardening = EventStoreHardening()
    return _global_hardening


__all__ = ["RetentionPolicy", "EventSnapshot", "RetentionConfig", 
           "EventCompactor", "EventPartitioner", "RetentionManager",
           "EventStoreHardening", "get_event_hardening"]
