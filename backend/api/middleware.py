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
import time
from datetime import datetime
from typing import Callable, Dict, Deque
from collections import deque
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from backend import config
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
                request_id,
                request.method,
                request.url.path,
                process_time,
                exc_info=True,
            )
            record_security_event(
                "unhandled_exception",
                severity="error",
                request=request,
                details={"request_id": request_id, "error_type": type(e).__name__},
            )

            return JSONResponse(
                status_code=500,
                content={
                    "error": "Internal server error",
                    "message": "Request failed. Check server logs with the returned request_id.",
                    "request_id": request_id,
                    "path": request.url.path,
                    "timestamp": datetime.now().isoformat()
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
            request.method,
            request.url.path,
            response.status_code,
            process_time,
            getattr(request.state, "request_id", ""),
        )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter.

    Uses a deque per client IP to store request timestamps.  Old entries are
    pruned on each request for that IP, and a periodic sweep removes IPs that
    have been idle for more than 2× the window (preventing unbounded growth
    under churn of unique IPs).
    """

    _SWEEP_INTERVAL = 300  # seconds between full cleanup sweeps

    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: Dict[str, Deque[float]] = {}
        self._last_sweep: float = time.monotonic()

    def _sweep(self, now: float) -> None:
        """Remove idle client entries to prevent unbounded memory growth."""
        cutoff = now - self.window_seconds * 2
        idle = [ip for ip, dq in self._buckets.items() if not dq or dq[-1] < cutoff]
        for ip in idle:
            del self._buckets[ip]
        self._last_sweep = now

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        cutoff = now - self.window_seconds

        if now - self._last_sweep > self._SWEEP_INTERVAL:
            self._sweep(now)

        if client_ip not in self._buckets:
            self._buckets[client_ip] = deque()
        bucket = self._buckets[client_ip]

        # Drop timestamps outside the current window
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        path = request.url.path
        is_outlook_surface = path.startswith("/outlook") or path.endswith("taskpane.html") or path.endswith("mail-read.html") or path.endswith("mail-compose.html")
        frame_ancestors = "'self' https://*.office.com https://*.officeapps.live.com" if is_outlook_surface else "'none'"
        csp = (
            "default-src 'self'; "
            "base-uri 'none'; "
            "object-src 'none'; "
            "img-src 'self' data: blob:; "
            "font-src 'self' data:; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline' https://appsforoffice.microsoft.com; "
            "connect-src 'self' http://127.0.0.1:* http://localhost:* ws://127.0.0.1:* ws://localhost:*; "
            f"frame-ancestors {frame_ancestors}"
        )
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        if not is_outlook_surface:
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
        return [self._normalize_origin(origin) for origin in (getattr(config, "CORS_ALLOWED_ORIGINS", []) or []) if origin and origin != "*"]

    @staticmethod
    def _normalize_origin(value: str) -> str:
        value = (value or "").strip().rstrip('/')
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
            # Production must be exact allowlist based. Do not accept arbitrary
            # browser-extension origins; the deployed extension ID must be listed.
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




class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        inbound = request.headers.get("x-request-id", "")[:80]
        request_id = inbound if inbound and all(ch.isalnum() or ch in "-_." for ch in inbound) else uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int = None):
        super().__init__(app)
        configured = os.environ.get("MAX_REQUEST_BODY_BYTES", "")
        try:
            self.max_bytes = int(configured) if configured else (max_bytes or 1024 * 1024)
        except ValueError:
            self.max_bytes = max_bytes or 1024 * 1024

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > self.max_bytes:
                    record_security_event("request_body_too_large", severity="warning", request=request, details={"content_length": length, "max_bytes": self.max_bytes})
                    return JSONResponse(status_code=413, content={"error": "Payload too large", "max_bytes": self.max_bytes})
            except ValueError:
                return JSONResponse(status_code=400, content={"error": "Invalid Content-Length"})
        return await call_next(request)


class RequestSigningMiddleware(BaseHTTPMiddleware):
    EXACT_EXEMPT_PATHS = {"/", "/favicon.ico", "/taskpane.html", "/mail-read.html", "/mail-compose.html"}
    EXEMPT_PREFIXES = (
        "/dashboard", "/admin", "/setup", "/outlook", "/icons",
        "/api/v1/health", "/api/health", "/api/v1/readiness", "/api/v1/frontend/telemetry", "/api/v1/security/status", "/api/v1/security/request-signing",
        "/api/oauth/", "/api/v1/oauth/",
    )

    def __init__(self, app):
        super().__init__(app)
        self.signer = RequestSigner()
        self.enforced = str(os.environ.get("REQUIRE_REQUEST_SIGNATURES", "")).lower() in {"1", "true", "yes", "on"}

    def _is_exempt(self, path: str, method: str) -> bool:
        if method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return True
        return path in self.EXACT_EXEMPT_PATHS or any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES)

    def _browser_origin_present(self, request: Request) -> bool:
        return bool(request.headers.get("origin") or request.headers.get("referer"))

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Browser/extension requests are governed by origin validation and CSP.
        # HMAC request signing is for non-browser API clients and automation, so
        # the dashboard never needs to own a signing secret.
        if not self.enforced or self._is_exempt(request.url.path, request.method) or self._browser_origin_present(request):
            return await call_next(request)
        body = await request.body()
        headers = {k.lower(): v for k, v in request.headers.items()}
        decision = self.signer.verify(request.method, request.url.path, headers, body)
        if not decision.ok:
            record_security_event("request_signature_rejected", severity="warning", request=request, details={"reason": decision.reason})
            return JSONResponse(status_code=401, content={"error": "Invalid request signature", "reason": decision.reason})
        request._body = body
        return await call_next(request)

class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Abort requests that exceed a configurable wall-clock timeout.

    Uses asyncio.wait_for so the event loop slot is released immediately on
    timeout rather than waiting for the blocked handler to eventually return.
    WebSocket upgrade paths are exempt (they are long-lived by design).
    """

    def __init__(self, app, timeout_seconds: float = 30.0):
        super().__init__(app)
        configured = os.environ.get("REQUEST_TIMEOUT_SECONDS", "")
        try:
            self.timeout = float(configured) if configured else timeout_seconds
        except ValueError:
            self.timeout = timeout_seconds

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # WebSocket connections are exempt — they are long-lived by design
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "Request timeout (%.1fs) method=%s path=%s",
                self.timeout, request.method, request.url.path,
            )
            return JSONResponse(
                status_code=504,
                content={
                    "error": "Gateway timeout",
                    "message": f"Request exceeded the {self.timeout}s server limit.",
                },
            )


def setup_middlewares(app) -> None:
    """Apply all middlewares to the FastAPI app.

    Note: Starlette adds middleware in LIFO order, so the last add_middleware()
    call here becomes the outermost layer (first to handle a request).
    The GZipMiddleware is added separately in main.py via
    app.add_middleware(GZipMiddleware) to ensure it wraps everything.
    """
    app.add_middleware(RateLimitMiddleware, max_requests=config.RATE_LIMIT_REQUESTS, window_seconds=config.RATE_LIMIT_WINDOW)
    app.add_middleware(ErrorLoggingMiddleware)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(OriginValidationMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestSigningMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware)
    app.add_middleware(RequestTimeoutMiddleware)
    app.add_middleware(RequestIDMiddleware)