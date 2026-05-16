"""
Exponential backoff retry helper for async connector calls.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, Optional, Tuple, Type

log = logging.getLogger(__name__)


async def retry_async(
    fn: Callable,
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
    **kwargs,
) -> Any:
    """
    Call fn(*args, **kwargs) with exponential backoff.

    Args:
        fn: Async callable to retry.
        max_attempts: Maximum number of attempts (1 = no retry).
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay cap.
        jitter: Add random jitter to avoid thundering herd.
        retryable_exceptions: Only retry on these exception types.
        on_retry: Optional callback(attempt, exc) called before each retry.
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(*args, **kwargs)
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt == max_attempts:
                raise
            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            if jitter:
                delay *= (0.5 + random.random())
            log.warning("retry_async: attempt %d/%d failed (%s), retrying in %.1fs",
                        attempt, max_attempts, exc, delay)
            if on_retry:
                try:
                    await on_retry(attempt, exc)
                except Exception:
                    pass
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore


def is_rate_limit_error(exc: Exception) -> bool:
    """Detect HTTP 429 / rate-limit responses from httpx or requests."""
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg


def is_transient_error(exc: Exception) -> bool:
    """Detect network / server errors worth retrying."""
    msg = str(exc).lower()
    transient_codes = {"500", "502", "503", "504"}
    return any(c in msg for c in transient_codes) or "timeout" in msg or "connection" in msg
