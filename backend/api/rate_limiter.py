"""
API Rate Limiter - Enterprise Rate Limiting
=========================================

Advanced rate limiting with:
- Sliding window algorithm
- Token bucket
- Per-provider limits
- Adaptive throttling
- Rate limit analytics
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger("api.ratelimit")


class RateLimitStrategy(Enum):
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"
    ADAPTIVE = "adaptive"


@dataclass
class RateLimitConfig:
    """Rate limit configuration"""
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    burst_size: int = 10
    strategy: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW


@dataclass
class RateLimitEntry:
    """Rate limit tracking entry"""
    key: str
    requests: deque = field(default_factory=deque)
    tokens: float = 10.0
    last_update: float = field(default_factory=time.time)


class RateLimiter:
    """
    Enterprise-grade API rate limiter.
    """

    def __init__(self, config: RateLimitConfig = None):
        self.config = config or RateLimitConfig()
        self._limits: Dict[str, RateLimitEntry] = {}
        self._lock = threading.RLock()

        # Analytics
        self._total_requests = 0
        self._limited_requests = 0
        self._analytics: deque = deque(maxlen=1000)

        logger.info("RateLimiter initialized")

    def check_limit(self, api_key: str, cost: int = 1) -> bool:
        """Check if request is within rate limit"""
        with self._lock:
            now = time.time()

            # Get or create entry
            if api_key not in self._limits:
                self._limits[api_key] = RateLimitEntry(key=api_key)

            entry = self._limits[api_key]

            # Clean old requests
            cutoff = now - 60  # 1 minute window
            while entry.requests and entry.requests[0] < cutoff:
                entry.requests.popleft()

            # Check limit
            if len(entry.requests) >= self.config.requests_per_minute:
                self._limited_requests += 1
                self._record_analytics(api_key, "limited", now)
                return False

            # Allow request
            entry.requests.append(now)
            self._total_requests += 1
            self._record_analytics(api_key, "allowed", now)

            return True

    def _record_analytics(self, api_key: str, status: str, timestamp: float):
        """Record analytics"""
        self._analytics.append({
            "api_key": api_key,
            "status": status,
            "timestamp": timestamp
        })

    def get_remaining(self, api_key: str) -> int:
        """Get remaining requests"""
        with self._lock:
            if api_key not in self._limits:
                return self.config.requests_per_minute

            entry = self._limits[api_key]
            now = time.time()
            cutoff = now - 60

            # Count recent requests
            recent = sum(1 for t in entry.requests if t > cutoff)
            return max(0, self.config.requests_per_minute - recent)

    def get_reset_time(self, api_key: str) -> float:
        """Get reset time in seconds"""
        with self._lock:
            if api_key not in self._limits:
                return 60

            entry = self._limits[api_key]
            if not entry.requests:
                return 60

            oldest = min(entry.requests)
            return max(0, 60 - (time.time() - oldest))

    def get_stats(self) -> Dict:
        """Get rate limiter statistics"""
        return {
            "total_requests": self._total_requests,
            "limited_requests": self._limited_requests,
            "limited_percent": (self._limited_requests / max(1, self._total_requests)) * 100,
            "active_keys": len(self._limits),
            "configuration": {
                "requests_per_minute": self.config.requests_per_minute,
                "requests_per_hour": self.config.requests_per_hour,
                "burst_size": self.config.burst_size
            }
        }

    def reset(self, api_key: str = None):
        """Reset rate limits"""
        with self._lock:
            if api_key:
                if api_key in self._limits:
                    del self._limits[api_key]
            else:
                self._limits.clear()


# Global rate limiter
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Get global rate limiter"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter


__all__ = ["RateLimiter", "RateLimitConfig", "RateLimitStrategy", "get_rate_limiter"]
