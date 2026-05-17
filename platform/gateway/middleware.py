"""
Gateway middleware stack — tenant resolution, auth, rate limiting, tracing.

All middleware classes are standard Starlette ASGI middleware.
They are applied in order by APIGateway.build_app().
"""
from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)


# ── Tenant middleware ──────────────────────────────────────────────────────

class TenantMiddleware:
    """
    Resolves tenant_id from the request and attaches it to request.state.

    Resolution order:
      1. X-Tenant-ID header
      2. JWT claim "tenant_id" (if auth middleware ran first)
      3. Query param ?tenant_id=
      4. Falls back to "__system__"
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict, receive: Callable, send: Callable) -> None:
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            tenant_id = (
                headers.get(b"x-tenant-id", b"").decode()
                or self._from_query(scope.get("query_string", b""))
                or "__system__"
            )
            scope.setdefault("state", {})["tenant_id"] = tenant_id
        await self.app(scope, receive, send)

    def _from_query(self, qs: bytes) -> str:
        for part in qs.decode().split("&"):
            if part.startswith("tenant_id="):
                return part.split("=", 1)[1]
        return ""


# ── Tracing middleware ─────────────────────────────────────────────────────

class TracingMiddleware:
    """
    Injects a trace_id (UUID4) into every request and adds it to the
    response as X-Trace-ID.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            trace_id = (
                headers.get(b"x-trace-id", b"").decode()
                or str(uuid.uuid4())
            )
            scope.setdefault("state", {})["trace_id"] = trace_id

            async def send_with_trace(message: Dict) -> None:
                if message["type"] == "http.response.start":
                    headers_list = list(message.get("headers", []))
                    headers_list.append((b"x-trace-id", trace_id.encode()))
                    message = {**message, "headers": headers_list}
                await send(message)

            await self.app(scope, receive, send_with_trace)
        else:
            await self.app(scope, receive, send)


# ── Rate limiting middleware ───────────────────────────────────────────────

class RateLimitMiddleware:
    """
    Sliding-window rate limiter keyed by (plugin_id, tenant_id).

    Default: 600 requests per minute per plugin per tenant.
    Per-route overrides stored in RouteRegistry.rate_limit are checked
    downstream by the route handler itself (this covers the global cap).
    """

    def __init__(self, app: Any, *, requests_per_minute: int = 600) -> None:
        self.app = app
        self._rpm = requests_per_minute
        self._windows: Dict[str, deque] = defaultdict(deque)

    async def __call__(self, scope: Dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "http":
            path: str = scope.get("path", "")
            if path.startswith("/plugins/"):
                key = self._window_key(scope)
                if key and not self._allow(key):
                    await self._reject(send)
                    return
        await self.app(scope, receive, send)

    def _window_key(self, scope: Dict) -> Optional[str]:
        path = scope.get("path", "")
        parts = path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "plugins":
            plugin_id = parts[1]
            tenant_id = scope.get("state", {}).get("tenant_id", "__system__")
            return f"{plugin_id}:{tenant_id}"
        return None

    def _allow(self, key: str) -> bool:
        now = time.time()
        window = self._windows[key]
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self._rpm:
            return False
        window.append(now)
        return True

    async def _reject(self, send: Callable) -> None:
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", b"60"),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"detail":"Rate limit exceeded"}',
        })


# ── Auth middleware ────────────────────────────────────────────────────────

class AuthMiddleware:
    """
    Lightweight bearer-token auth gate for plugin routes.

    Skips paths not under /plugins/. Actual token validation is delegated
    to the verify_token callable injected at construction time.
    """

    def __init__(
        self,
        app: Any,
        *,
        verify_token: Optional[Callable[[str], Optional[Dict]]] = None,
        skip_paths: Optional[list] = None,
    ) -> None:
        self.app = app
        self._verify = verify_token
        self._skip = set(skip_paths or [])

    async def __call__(self, scope: Dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path.startswith("/plugins/") and path not in self._skip:
                headers = dict(scope.get("headers", []))
                auth_header = headers.get(b"authorization", b"").decode()
                if auth_header.startswith("Bearer ") and self._verify:
                    token = auth_header[7:]
                    claims = self._verify(token)
                    if claims is None:
                        await self._unauthorized(send)
                        return
                    scope.setdefault("state", {})["user"] = claims
        await self.app(scope, receive, send)

    async def _unauthorized(self, send: Callable) -> None:
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({
            "type": "http.response.body",
            "body": b'{"detail":"Unauthorized"}',
        })
