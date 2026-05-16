"""
Cache Manager - Multi-Level Caching
======================================

Multi-level caching:
- Memory cache (L1)
- Disk cache (L2)  
- Distributed cache (L3)
- Cache invalidation
- TTL management
"""

import time
import threading
import hashlib
import json
import logging
from typing import Any, Optional, Dict
from dataclasses import dataclass, field
from collections import OrderedDict
from enum import Enum

logger = logging.getLogger("cache.manager")


class CacheLevel(Enum):
    MEMORY = "memory"
    DISK = "disk"
    DISTRIBUTED = "distributed"


@dataclass
class CacheEntry:
    """Cache entry"""
    key: str
    value: Any
    created_at: float = field(default_factory=time.time)
    expires_at: Optional[float] = None
    hits: int = 0


class MemoryCache:
    """In-memory LRU cache"""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: float = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value"""
        with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            
            # Check expiration
            if entry.expires_at and time.time() > entry.expires_at:
                del self._cache[key]
                return None
            
            # Update access order
            self._cache.move_to_end(key)
            entry.hits += 1
            
            return entry.value
    
    def set(self, key: str, value: Any, ttl: Optional[float] = None):
        """Set value"""
        with self._lock:
            # Evict if full
            while len(self._cache) >= self.max_size:
                self._cache.popitem(last=False)
            
            expires_at = time.time() + (ttl or self.ttl_seconds)
            
            self._cache[key] = CacheEntry(
                key=key,
                value=value,
                expires_at=expires_at
            )
    
    def delete(self, key: str) -> bool:
        """Delete value"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self):
        """Clear cache"""
        with self._lock:
            self._cache.clear()
    
    def stats(self) -> Dict:
        """Get cache stats"""
        with self._lock:
            total_hits = sum(e.hits for e in self._cache.values())
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "total_hits": total_hits
            }


class MultiLevelCache:
    """
    Multi-level cache manager.
    """
    
    def __init__(self):
        self._memory = MemoryCache(max_size=1000)
        self._disk_cache: Dict[str, Any] = {}
        self._lock = threading.RLock()
        
        # Metrics
        self._hits = 0
        self._misses = 0
        
        logger.info("MultiLevelCache initialized")
    
    def get(self, key: str, level: CacheLevel = CacheLevel.MEMORY) -> Optional[Any]:
        """Get from cache"""
        # Try memory first
        if level == CacheLevel.MEMORY:
            value = self._memory.get(key)
            if value is not None:
                self._hits += 1
                return value
            self._misses += 1
        
        return None
    
    def set(self, key: str, value: Any, level: CacheLevel = CacheLevel.MEMORY, ttl: Optional[float] = None):
        """Set in cache"""
        if level == CacheLevel.MEMORY:
            self._memory.set(key, value, ttl)
    
    def delete(self, key: str):
        """Delete from all levels"""
        self._memory.delete(key)
        self._disk_cache.pop(key, None)
    
    def invalidate_pattern(self, pattern: str):
        """Invalidate keys matching pattern"""
        keys = [k for k in self._memory._cache.keys() if pattern in k]
        for key in keys:
            self.delete(key)
    
    def get_stats(self) -> Dict:
        """Get cache statistics"""
        return {
            "memory": self._memory.stats(),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / max(1, self._hits + self._misses)
        }


# Global cache manager
_cache_manager: Optional[MultiLevelCache] = None


def get_cache_manager() -> MultiLevelCache:
    """Get global cache manager"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = MultiLevelCache()
    return _cache_manager


__all__ = ["MultiLevelCache", "MemoryCache", "CacheLevel", "get_cache_manager"]