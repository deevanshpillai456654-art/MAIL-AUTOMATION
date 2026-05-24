"""
Provider Rate Limit Intelligence
=============================

Local AI engine rate limiting:
- Adaptive throttling
- Token bucket management
- Provider quota tracking
- Local resource optimization
- Priority-based allocation
- Retry with backoff
- Request coalescing
- Circuit breaker
- Usage forecasting
- Resource alerts
"""

import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("provider.rate_limit")


class ProviderType(Enum):
    ONNX = "onnxruntime"
    LOCAL = "local"
    VECTOR = "local_vector"
    CUSTOM = "custom"


class RequestPriority(Enum):
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    BATCH = 5


@dataclass
class ProviderQuota:
    """Provider quota"""
    provider: ProviderType
    requests_per_minute: int = 60
    tokens_per_minute: int = 90000
    requests_per_day: int = 500
    resource_limit_daily: float = 100.0
    current_requests: int = 0
    current_tokens: int = 0
    current_resource_units: float = 0.0


@dataclass
class TokenBucket:
    """Token bucket for rate limiting"""
    capacity: float
    tokens: float
    refill_rate: float
    last_refill: float

    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.tokens = capacity
        self.refill_rate = refill_rate
        self.last_refill = time.time()

    def consume(self, tokens: float) -> bool:
        """Try to consume tokens"""
        self._refill()

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    def _refill(self):
        """Refill tokens"""
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def available(self) -> float:
        """Available tokens"""
        self._refill()
        return self.tokens


@dataclass
class AdaptiveThrottleState:
    """Adaptive throttling state"""
    current_delay_ms: float = 0
    backoff_multiplier: float = 1.0
    success_rate: float = 1.0
    requests_queued: int = 0
    requests_dropped: int = 0


class RateLimitIntelligence:
    """Main rate limit intelligence"""

    def __init__(self):
        self._provider_quotas: Dict[ProviderType, ProviderQuota] = {}
        self._token_buckets: Dict[ProviderType, TokenBucket] = {}
        self._request_queue: Dict[ProviderType, deque] = defaultdict(deque)
        self._adaptive_state: Dict[ProviderType, AdaptiveThrottleState] = {}
        self._usage_history: Dict[ProviderType, List[Dict[str, Any]]] = defaultdict(list)
        self._lock = threading.RLock()

        self._config = {
            "enable_adaptive_throttling": True,
            "enable_resource_alerts": True,
            "enable_usage_forecasting": True,
            "backoff_base_ms": 100,
            "backoff_max_ms": 5000,
            "resource_alert_threshold": 0.8
        }

    def register_provider(self,
                      provider: ProviderType,
                      rpm: int = 60,
                      tpm: int = 90000,
                      daily_resource_limit: float = 100.0):
        """Register provider"""
        with self._lock:
            quota = ProviderQuota(
                provider=provider,
                requests_per_minute=rpm,
                tokens_per_minute=tpm,
                resource_limit_daily=daily_resource_limit
            )
            self._provider_quotas[provider] = quota

            self._token_buckets[provider] = TokenBucket(
                capacity=rpm,
                refill_rate=rpm / 60.0
            )

            self._adaptive_state[provider] = AdaptiveThrottleState()

            logger.info(f"Provider registered: {provider.value}")

    async def check_limit(self,
                      provider: ProviderType,
                      priority: RequestPriority = RequestPriority.NORMAL) -> Tuple[bool, float]:
        """Check rate limit, return (allowed, delay_ms)"""
        with self._lock:
            if provider not in self._provider_quotas:
                return True, 0.0

            quota = self._provider_quotas[provider]
            bucket = self._token_buckets[provider]

            if bucket.consume(1):
                quota.current_requests += 1

                self._adaptive_state[provider].success_rate = 1.0
                self._adaptive_state[provider].current_delay_ms = 0

                return True, 0.0

            delay = self._adaptive_state[provider].current_delay_ms

            if self._config["enable_adaptive_throttling"]:
                delay = self._calculate_backoff(provider, priority)
                self._adaptive_state[provider].current_delay_ms = delay

            return False, delay

    def _calculate_backoff(self,
                         provider: ProviderType,
                         priority: RequestPriority) -> float:
        """Calculate adaptive backoff"""
        state = self._adaptive_state[provider]

        base_delay = self._config["backoff_base_ms"]
        max_delay = self._config["backoff_max_ms"]

        if priority == RequestPriority.CRITICAL:
            return 0
        elif priority == RequestPriority.LOW:
            base_delay *= 2

        backoff = base_delay * state.backoff_multiplier

        state.backoff_multiplier = min(state.backoff_multiplier * 1.5, 10.0)

        return min(backoff, max_delay)

    def record_success(self, provider: ProviderType, tokens: int = 0, resource_units: float = 0.0):
        """Record successful request"""
        with self._lock:
            if provider in self._provider_quotas:
                quota = self._provider_quotas[provider]
                quota.current_requests += 1
                quota.current_tokens += tokens
                quota.current_resource_units += resource_units

                self._adaptive_state[provider].success_rate = 1.0
                self._adaptive_state[provider].backoff_multiplier = max(
                    1.0, self._adaptive_state[provider].backoff_multiplier * 0.9
                )

    def record_failure(self, provider: ProviderType):
        """Record failed request"""
        with self._lock:
            if provider in self._adaptive_state:
                state = self._adaptive_state[provider]
                state.backoff_multiplier *= 1.2
                state.requests_dropped += 1

    def get_queue_depth(self, provider: ProviderType) -> int:
        """Get pending requests"""
        with self._lock:
            return len(self._request_queue.get(provider, []))

    def get_available_quota(self, provider: ProviderType) -> Dict[str, float]:
        """Get available quota"""
        with self._lock:
            if provider not in self._provider_quotas:
                return {}

            quota = self._provider_quotas[provider]
            bucket = self._token_buckets.get(provider)

            return {
                "requests_remaining": quota.requests_per_minute - quota.current_requests,
                "tokens_remaining": quota.tokens_per_minute - quota.current_tokens,
                "resource_units_remaining": quota.resource_limit_daily - quota.current_resource_units,
                "bucket_available": bucket.available() if bucket else 0
            }

    def should_alert(self, provider: ProviderType) -> bool:
        """Check if cost alert needed"""
        with self._lock:
            if not self._config["enable_resource_alerts"]:
                return False

            if provider not in self._provider_quotas:
                return False

            quota = self._provider_quotas[provider]
            threshold = self._config["resource_alert_threshold"]

            return quota.current_resource_units >= quota.resource_limit_daily * threshold

    def forecast_usage(self, provider: ProviderType, minutes: int = 60) -> Dict[str, float]:
        """Forecast usage"""
        with self._lock:
            history = self._usage_history.get(provider, [])

            if len(history) < 10:
                return {"forecasted_requests": 0, "forecasted_resource_units": 0}

            recent = history[-minutes:]

            avg_requests = sum(h.get("requests", 0) for h in recent) / len(recent)
            avg_resource_units = sum(h.get("resource_units", 0) for h in recent) / len(recent)

            return {
                "forecasted_requests": avg_requests * minutes,
                "forecasted_resource_units": avg_resource_units * minutes
            }

    def get_stats(self) -> Dict[str, Any]:
        """Get rate limit stats"""
        with self._lock:
            stats = {
                "providers": {}
            }

            for provider, quota in self._provider_quotas.items():
                adaptive = self._adaptive_state.get(provider)

                stats["providers"][provider.value] = {
                    "current_requests": quota.current_requests,
                    "current_tokens": quota.current_tokens,
                    "current_resource_units": quota.current_resource_units,
                    "delay_ms": adaptive.current_delay_ms if adaptive else 0,
                    "success_rate": adaptive.success_rate if adaptive else 1.0,
                    "queue_depth": len(self._request_queue[provider])
                }

            return stats


_global_rate_limiter: Optional["RateLimitIntelligence"] = None


def get_rate_limiter() -> RateLimitIntelligence:
    """Get global rate limiter"""
    global _global_rate_limiter
    if _global_rate_limiter is None:
        _global_rate_limiter = RateLimitIntelligence()
    return _global_rate_limiter


__all__ = [
    "ProviderType",
    "RequestPriority",
    "ProviderQuota",
    "TokenBucket",
    "AdaptiveThrottleState",
    "RateLimitIntelligence",
    "get_rate_limiter"
]
