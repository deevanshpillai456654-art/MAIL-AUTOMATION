"""Shared async HTTP client singleton.

Use this instead of `requests` in async endpoints and background tasks.
A single httpx.AsyncClient is shared across the application to reuse
TCP connections (keep-alive pooling), reducing per-request latency and
OS socket pressure under concurrent load.

Usage
-----
    from backend.core.async_http import get_http_client

    async def my_endpoint():
        client = await get_http_client()
        resp = await client.get("http://127.0.0.1:4597/api/v1/health")

    # In lifespan shutdown:
    from backend.core.async_http import close_http_client
    await close_http_client()

Thread-safety: `get_http_client()` is safe to call concurrently from multiple
async tasks.  The underlying httpx.AsyncClient is itself concurrency-safe.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("async_http")

_client: Optional[object] = None   # httpx.AsyncClient, typed as object to avoid hard import at module load
_init_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    return _init_lock


async def get_http_client():
    """Return the shared httpx.AsyncClient, creating it on first call."""
    global _client
    if _client is not None and not _client.is_closed:
        return _client
    async with _get_lock():
        if _client is None or _client.is_closed:
            try:
                import httpx
            except ImportError as exc:
                raise RuntimeError("httpx is required — run: pip install httpx") from exc

            _client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=30.0,
                    write=10.0,
                    pool=5.0,
                ),
                limits=httpx.Limits(
                    max_connections=100,
                    max_keepalive_connections=30,
                    keepalive_expiry=30.0,
                ),
                # No automatic redirects — callers handle them explicitly
                follow_redirects=False,
            )
            logger.info("Async HTTP client pool created (max_connections=100, keepalive=30)")
    return _client


async def close_http_client() -> None:
    """Close the shared client and release all pooled connections.  Call during app shutdown."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        logger.info("Async HTTP client pool closed")
    _client = None


__all__ = ["get_http_client", "close_http_client"]
