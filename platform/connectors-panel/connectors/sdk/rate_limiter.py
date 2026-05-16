"""
In-process token-bucket rate limiter.
One instance per (connector_id, tenant_id) pair, stored in the registry.
"""
from __future__ import annotations

import asyncio
import time
from typing import Dict, Tuple


class RateLimiter:
    """
    Async token-bucket rate limiter.

    Args:
        rate: Tokens replenished per second.
        burst: Maximum token bucket capacity.
    """

    def __init__(self, rate: float = 10.0, burst: float = 20.0) -> None:
        self._rate = rate
        self._burst = burst
        self._tokens = burst
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        self._last_refill = now

    async def acquire(self, tokens: float = 1.0) -> None:
        """Wait until *tokens* are available, then consume them."""
        async with self._lock:
            while True:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                wait = (tokens - self._tokens) / self._rate
                await asyncio.sleep(wait)

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *_):
        pass


# Per-connector rate limiter registry (connector_id -> RateLimiter)
_limiters: Dict[Tuple[str, str], RateLimiter] = {}


def get_rate_limiter(connector_id: str, tenant_id: str,
                     rate: float = 10.0, burst: float = 20.0) -> RateLimiter:
    key = (connector_id, tenant_id)
    if key not in _limiters:
        _limiters[key] = RateLimiter(rate=rate, burst=burst)
    return _limiters[key]
