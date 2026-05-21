"""Async provider HTTP transport for high-volume sync paths.

The transport reuses the shared application HTTP pool and centralizes retry,
timeout, and JSON handling for Gmail, Outlook, and future provider sync code.
Existing synchronous sync flows can continue to operate while high-volume
deployments move provider reads onto this pooled async path.
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Optional

from backend.core.async_http import get_http_client


class ProviderTransportError(RuntimeError):
    """Raised when a provider request cannot be completed safely."""


class AsyncProviderTransport:
    RETRY_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        provider: str,
        api_base: str,
        headers: Optional[Mapping[str, str]] = None,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
    ):
        self.provider = str(provider or "provider")
        self.api_base = str(api_base or "").rstrip("/")
        self.headers = dict(headers or {})
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.max_attempts = max(1, int(max_attempts))

    async def request_json(self, method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.api_base}{endpoint}"
        last_error: str | None = None
        for attempt in range(self.max_attempts):
            try:
                client = await get_http_client()
                response = await client.request(
                    method,
                    url,
                    headers=self.headers,
                    timeout=self.timeout_seconds,
                    **kwargs,
                )
                if response.ok:
                    if not response.content:
                        return {}
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise ProviderTransportError(f"{self.provider} returned invalid JSON for {endpoint}: {exc}") from exc
                    return payload if isinstance(payload, dict) else {"value": payload}

                body = (getattr(response, "text", "") or "").strip()[:500]
                reason = getattr(response, "reason_phrase", "") or getattr(response, "reason", "")
                last_error = f"{self.provider} API {response.status_code} for {endpoint}: {body or reason}"
                if int(response.status_code) in self.RETRY_STATUS_CODES and attempt < self.max_attempts - 1:
                    await asyncio.sleep(min(2 ** attempt, 4))
                    continue
                raise ProviderTransportError(last_error)
            except ProviderTransportError:
                raise
            except Exception as exc:
                last_error = f"{self.provider} network error for {endpoint}: {exc}"
                if attempt < self.max_attempts - 1:
                    await asyncio.sleep(min(2 ** attempt, 4))
                    continue
                raise ProviderTransportError(last_error) from exc
        raise ProviderTransportError(last_error or f"{self.provider} request failed for {endpoint}")

    def capabilities(self) -> dict[str, Any]:
        return {
            "pooled_async_http": True,
            "retry_protection": True,
            "timeout_protection": True,
            "connection_reuse": True,
            "max_attempts": self.max_attempts,
            "timeout_seconds": self.timeout_seconds,
        }


__all__ = ["AsyncProviderTransport", "ProviderTransportError"]
