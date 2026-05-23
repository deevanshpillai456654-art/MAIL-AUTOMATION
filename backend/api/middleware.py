"""
Middleware stack for the INTEMO FastAPI backend.

Middleware execution order (outermost → innermost, i.e. first in list = first to see request):
  GZipMiddleware (added in main.py via Starlette)
  RequestTimeoutMiddleware
  RequestIDMiddleware
  RequestSizeLimitMiddleware
  RequestSigningMiddleware
  SecurityHeadersMiddleware
  OriginValidationMiddleware
  RequestLoggingMiddleware
  RateLimitMiddleware
  ErrorLoggingMiddleware  ← innermost, closest to FastAPI app
"""

import asyncio
import logging
import os
import secrets as _secrets
import time
from collections import deque
from datetime import datetime
from typing import Callable, Dict, Deque
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend import config
from backend.auth.local_auth import request_has_valid_local_auth
from backend.security.audit import record_security_event
from backend.security.redaction import redact_text
from backend.security.request_signing import RequestSigner


logger = logging.getLogger(__name__)


class ErrorLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = datetime.now()
        request_id = getattr(request.state, "request_id", request.headers.get("x-request-id", uuid4().hex))

        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as e:
            process_time = (datetime.now() - start_time).total_seconds()
            logger.error(
                "Unhandled request error request_id=%s method=%s path=%s duration=%.3fs",
                request_id, request.method, request.url.path, process_time,
                exc_info=True,
            )
            record_security_event(
                "unhandled_exception", severity="error", request=request,
                details={"request_id": request_id, "error_type": type(e).__name__},
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error",
                    "message": "Request failed. Check server logs with the returned request_id.",
                    "request_id": request_id,
                    "path": request.url.path,
                    "timestamp": datetime.now().isoformat(),
                },
                headers={"X-Request-ID": request_id},
            )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = datetime.now()
        logger.info("Request: %s %s request_id=%s", request.method, request.url.path, getattr(request.state, "request_id", ""))
        response = await call_next(request)
        process_time = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Response: %s %s status=%s duration=%.3fs request_id=%s",
            request.method, request.url.path, response.status_code, process_time,
            getattr(request.state, "request_id", ""),
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter with trusted-proxy X-Forwarded-For support.

    When the direct connection arrives from a loopback address (127.0.0.1 / ::1),
    the request is coming through a local reverse proxy, so X-Forwarded-For and
    X-Real-IP headers are trusted for rate-limit keying. Otherwise, the raw
    socket peer address is used to prevent IP spoofing via forged headers.
    """

    _SWEEP_INTERVAL = 300
    # Hard cap on bucket dict size — guards against unbounded memory growth
    # between sweeps if a botnet hits the API from many distinct source IPs.
    _MAX_BUCKETS = 10_000

    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: Dict[str, Deque[float]] = {}
        self._last_sweep: float = time.monotonic()

    def _sweep(self, now: float) -> None:
        cutoff = now - self.window_seconds * 2
        idle = [ip for ip, dq in self._buckets.items() if not dq or dq[-1] < cutoff]
        for ip in idle:
            del self._buckets[ip]
        self._last_sweep = now

    def _evict_oldest_if_over_cap(self) -> None:
        # Force-evict the bucket whose newest sample is oldest. Cheap O(n) scan;
        # only runs in the rare case of an attack-shaped IP fan-out.
        if len(self._buckets) < self._MAX_BUCKETS:
            return
        oldest_ip = None
        oldest_ts = float("inf")
        for ip, dq in self._buckets.items():
            ts = dq[-1] if dq else 0.0
            if ts < oldest_ts:
                oldest_ts = ts
                oldest_ip = ip
        if oldest_ip is not None:
            del self._buckets[oldest_ip]

    @staticmethod
    def _resolve_client_ip(request: Request) -> str:
        direct = (request.client.host if request.client else None) or "unknown"
        # Trust forwarded headers only when the direct connection is a local proxy
        if direct in ("127.0.0.1", "::1", "localhost"):
            xff = request.headers.get("x-forwarded-for", "")
            if xff:
                return xff.split(",")[0].strip() or direct
            real_ip = request.headers.get("x-real-ip", "").strip()
            if real_ip:
                return real_ip
        return direct

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = self._resolve_client_ip(request)

        # Never rate-limit local connections — this app binds to 127.0.0.1 only
        if client_ip in ("127.0.0.1", "::1", "localhost"):
            return await call_next(request)

        now = time.monotonic()
        cutoff = now - self.window_seconds

        if now - self._last_sweep > self._SWEEP_INTERVAL:
            self._sweep(now)

        if client_ip not in self._buckets:
            self._evict_oldest_if_over_cap()
            self._buckets[client_ip] = deque()
        bucket = self._buckets[client_ip]

        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - bucket[0])) + 1
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Too many requests",
                    "message": f"Rate limit: {self.max_requests} requests per {self.window_seconds}s",
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)
        return await call_next(request)


# Paths served by static file mounts that STILL contain inline scripts — keep
# 'unsafe-inline' for these only. The main /dashboard SPA and /outlook taskpane
# were cleaned in W9 and now run under the strict nonce-based CSP.
# /icons is static images (no JS context), but harmless to keep on the list.
_STATIC_SPA_PREFIXES = ("/connectors-panel", "/icons")

# Paths that are intentionally embedded as iframes by same-origin pages.
# These must NOT receive X-Frame-Options: DENY or frame-ancestors 'none'.
_EMBEDDABLE_SPA_PREFIXES = ("/connectors-panel",)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate a per-request nonce for CSP (used by server-rendered HTML pages)
        nonce = _secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        path = request.url.path
        is_outlook_surface = (
            path.startswith("/outlook")
            or path.endswith("taskpane.html")
            or path.endswith("mail-read.html")
            or path.endswith("mail-compose.html")
        )
        is_static_spa = any(path.startswith(p) for p in _STATIC_SPA_PREFIXES)
        is_embeddable = any(path.startswith(p) for p in _EMBEDDABLE_SPA_PREFIXES)

        if is_outlook_surface:
            frame_ancestors = "'self' https://*.office.com https://*.officeapps.live.com"
        elif is_embeddable:
            frame_ancestors = "'self'"
        else:
            frame_ancestors = "'none'"

        if is_static_spa:
            # Static SPA files contain inline scripts that cannot carry nonces.
            # Keep 'unsafe-inline' only for these paths; all other responses use nonces.
            script_src = "'self' 'unsafe-inline'"
        else:
            script_src = f"'self' 'nonce-{nonce}'"

        if is_outlook_surface:
            script_src += " https://appsforoffice.microsoft.com"

        csp = (
            "default-src 'self'; "
            "base-uri 'none'; "
            "object-src 'none'; "
            f"img-src 'self' data: blob: https://www.google.com; "
            "font-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            f"script-src {script_src}; "
            "connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*; "
            f"frame-ancestors {frame_ancestors}"
        )

        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not is_outlook_surface and not is_embeddable:
            response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response


class OriginValidationMiddleware(BaseHTTPMiddleware):
    LOCAL_PREFIXES = [
        "chrome-extension://",
        "ms-office-addin://",
        "http://127.0.0.1",
        "http://localhost",
    ]

    def _configured_origins(self):
        return [
            self._normalize_origin(origin)
            for origin in (getattr(config, "CORS_ALLOWED_ORIGINS", []) or [])
            if origin and origin != "*"
        ]

    @staticmethod
    def _normalize_origin(value: str) -> str:
        value = (value or "").strip().rstrip("/")
        if not value:
            return ""
        try:
            parsed = urlparse(value)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return value
        return value

    def _is_allowed(self, value: str) -> bool:
        if not value:
            return True
        value = self._normalize_origin(value)
        configured = self._configured_origins()
        if getattr(config, "IS_PRODUCTION", False):
            return value in configured
        return any(value.startswith(prefix) for prefix in self.LOCAL_PREFIXES) or value in configured

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        origin = request.headers.get("origin", "")
        referer = request.headers.get("referer", "")
        if origin and not self._is_allowed(origin):
            record_security_event("blocked_origin", severity="warning", request=request, details={"origin": origin})
            return JSONResponse(status_code=403, content={"error": "Forbidden", "message": "Invalid origin"})
        if not origin and referer and not self._is_allowed(referer):
            record_security_event("blocked_referer", severity="warning", request=request, details={"referer": referer})
            return JSONResponse(status_code=403, content={"error": "Forbidden", "message": "Invalid referer"})
        return await call_next(request)


class LocalAPIAuthMiddleware(BaseHTTPMiddleware):
    """Require the local API credential for sensitive local-control surfaces.

    Policy is DEFAULT-DENY within ``/api/v1/`` and ``/api/connector-panel/``:
    any path under those prefixes requires the local API token unless it
    appears in ``PUBLIC_EXACT_PATHS`` or matches one of ``PUBLIC_PREFIXES``.
    Paths outside the API surface (``/dashboard``, ``/docs``, ``/setup``,
    ``/favicon.ico``, ``/`` …) are unaffected.

    Default-deny is defense in depth — individual routers ALSO use
    ``Depends(require_local_auth)`` on their endpoints. The middleware catches
    any router that forgets to add the dependency.
    """

    AUTH_SURFACE_PREFIXES = (
        "/api/v1/",
        "/api/connector-panel/",
    )

    PUBLIC_EXACT_PATHS = {
        "/api/v1/health",
        "/api/v1/session/bootstrap",
        "/api/connector-panel/session",
    }

    PUBLIC_PREFIXES = (
        "/api/v1/oauth/",
        "/api/v1/frontend/telemetry",
        "/api/connector-panel/engine/oauth/callback/",
        "/api/connector-panel/engine/webhooks/",
        "/api/connector-panel/webhooks/receive/",
    )

    def _requires_auth(self, path: str) -> bool:
        if path in self.PUBLIC_EXACT_PATHS:
            return False
        if any(path.startswith(prefix) for prefix in self.PUBLIC_PREFIXES):
            return False
        return any(path.startswith(prefix) for prefix in self.AUTH_SURFACE_PREFIXES)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self._requires_auth(request.url.path):
            return await call_next(request)
        if request_has_valid_local_auth(request):
            return await call_next(request)
        record_security_event(
            "local_api_auth_required",
            severity="warning",
            request=request,
            details={"path": request.url.path},
        )
        return JSONResponse(
            status_code=401,
            content={"error": "Authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        inbound = request.headers.get("x-request-id", "")[:80]
        request_id = inbound if inbound and all(ch.isalnum() or ch in "-_." for ch in inbound) else uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Enforce request body size limit against both Content-Length and chunked encoding.

    Chunked transfer encoding does not carry a Content-Length header, so a
    header-only check can be bypassed. This middleware wraps the ASGI receive
    callable to count actual bytes received and aborts when the limit is hit.
    """

    def __init__(self, app, max_bytes: int = None):
        super().__init__(app)
        configured = os.environ.get("MAX_REQUEST_BODY_BYTES", "")
        try:
            self.max_bytes = int(configured) if configured else (max_bytes or 1024 * 1024)
        except ValueError:
            self.max_bytes = max_bytes or 1024 * 1024

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Fast-path: reject via Content-Length header if present and over limit
        cl_header = request.headers.get("content-length")
        if cl_header:
            try:
                if int(cl_header) > self.max_bytes:
                    record_security_event(
                        "request_body_too_large", severity="warning", request=request,
                        details={"content_length": cl_header, "max_bytes": self.max_bytes},
                    )
                    return JSONResponse(status_code=413, content={"error": "Payload too large", "max_bytes": self.max_bytes})
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "Invalid Content-Length"})

        # Guard chunked / missing Content-Length by wrapping receive and counting bytes
        total_received = 0
        limit_exceeded = False
        original_receive = request._receive

        async def _bounded_receive():
            nonlocal total_received, limit_exceeded
            message = await original_receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"")
                total_received += len(chunk)
                if total_received > self.max_bytes:
                    limit_exceeded = True
                    # Truncate the chunk so the handler processes an empty/incomplete body
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        request._receive = _bounded_receive
        response = await call_next(request)

        if limit_exceeded:
            record_security_event(
                "request_body_too_large", severity="warning", request=request,
                details={"received_bytes": total_received, "max_bytes": self.max_bytes},
            )
            return JSONResponse(status_code=413, content={"error": "Payload too large", "max_bytes": self.max_bytes})

        return response


class RequestSigningMiddleware(BaseHTTPMiddleware):
    """HMAC-SHA256 request signing for non-browser API clients.

    Signing is enforced automatically when REQUEST_SIGNING_SECRET is configured.
    No separate REQUIRE_REQUEST_SIGNATURES env var is needed — the presence of
    the secret is the enable signal.

    Browser requests carrying an Origin or Referer header bypass signing because:
    1. CORS (OriginValidationMiddleware) already validates browser origins.
    2. Browsers cannot attach HMAC signatures to cross-origin requests.

    Non-browser clients (CLI tools, automation, other services) must sign all
    non-exempt POST/PUT/PATCH/DELETE requests when the secret is set.
    """

    EXACT_EXEMPT_PATHS = {"/", "/favicon.ico", "/taskpane.html", "/mail-read.html", "/mail-compose.html"}
    EXEMPT_PREFIXES = (
        "/dashboard", "/admin", "/setup", "/outlook", "/icons",
        "/api/v1/health", "/api/health", "/api/v1/readiness",
        "/api/v1/frontend/telemetry", "/api/v1/security/status",
        "/api/v1/security/request-signing",
        "/api/oauth/", "/api/v1/oauth/",
    )

    def __init__(self, app):
        super().__init__(app)
        self.signer = RequestSigner()

    def _is_exempt(self, path: str, method: str) -> bool:
        if method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return True
        return path in self.EXACT_EXEMPT_PATHS or any(path.startswith(p) for p in self.EXEMPT_PREFIXES)

    def _browser_origin_present(self, request: Request) -> bool:
        return bool(request.headers.get("origin") or request.headers.get("referer"))

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Signing is only enforced when REQUEST_SIGNING_SECRET is configured
        if not self.signer.secret:
            return await call_next(request)
        if self._is_exempt(request.url.path, request.method):
            return await call_next(request)
        # Browser/extension requests are governed by CORS — signing is for API clients only
        if self._browser_origin_present(request):
            return await call_next(request)
        body = await request.body()
        headers = {k.lower(): v for k, v in request.headers.items()}
        decision = self.signer.verify(request.method, request.url.path, headers, body)
        if not decision.ok:
            record_security_event(
                "request_signature_rejected", severity="warning", request=request,
                details={"reason": decision.reason},
            )
            return JSONResponse(status_code=401, content={"error": "Invalid request signature", "reason": decision.reason})
        request._body = body
        return await call_next(request)


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Abort requests that exceed a configurable wall-clock timeout."""

    def __init__(self, app, timeout_seconds: float = 30.0):
        super().__init__(app)
        configured = os.environ.get("REQUEST_TIMEOUT_SECONDS", "")
        try:
            self.timeout = float(configured) if configured else timeout_seconds
        except ValueError:
            self.timeout = timeout_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.warning("Request timeout (%.1fs) method=%s path=%s", self.timeout, request.method, request.url.path)
            return JSONResponse(
                status_code=504,
                content={"error": "Gateway timeout", "message": f"Request exceeded the {self.timeout}s server limit."},
            )


def setup_middlewares(app) -> None:
    """Apply all middlewares to the FastAPI app.

    Starlette adds middleware in LIFO order — the last add_middleware() call
    becomes the outermost layer (first to handle a request).
    """
    app.add_middleware(RateLimitMiddleware, max_requests=config.RATE_LIMIT_REQUESTS, window_seconds=config.RATE_LIMIT_WINDOW)
    app.add_middleware(ErrorLoggingMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(LocalAPIAuthMiddleware)
    app.add_middleware(OriginValidationMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestSigningMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(RequestTimeoutMiddleware)
    app.add_middleware(RequestIDMiddleware)
