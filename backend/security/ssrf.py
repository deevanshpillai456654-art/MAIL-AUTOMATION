"""Outbound URL validation for webhooks and update callbacks.

This blocks common SSRF targets by default: loopback/private/link-local ranges,
cloud metadata addresses, localhost aliases, unsupported schemes, and plaintext
HTTP in production unless explicitly opted in for local testing.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from dataclasses import dataclass
from typing import List
from urllib.parse import urlparse


@dataclass(frozen=True)
class OutboundURLDecision:
    allowed: bool
    reason: str
    resolved_ips: List[str]


_METADATA_HOSTS = {"metadata.google.internal", "169.254.169.254"}
# Denylist entries, not bind targets.
_LOCAL_HOSTS = {"localhost", "localhost.localdomain", "0.0.0.0", "::1"}  # nosec B104


def _is_blocked_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return any([
        ip.is_private,
        ip.is_loopback,
        ip.is_link_local,
        ip.is_multicast,
        ip.is_reserved,
        ip.is_unspecified,
        ip_text == "169.254.169.254",
    ])


def validate_outbound_url(url: str, *, require_https: bool | None = None) -> OutboundURLDecision:
    if not url or not isinstance(url, str):
        return OutboundURLDecision(False, "missing_url", [])
    try:
        parsed = urlparse(url)
    except Exception:
        return OutboundURLDecision(False, "invalid_url", [])

    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").strip().lower().rstrip('.')
    if scheme not in {"https", "http"}:
        return OutboundURLDecision(False, "unsupported_scheme", [])
    if not host:
        return OutboundURLDecision(False, "missing_host", [])
    if host in _LOCAL_HOSTS or host in _METADATA_HOSTS:
        return OutboundURLDecision(False, "blocked_host", [])

    if require_https is None:
        env = os.environ.get("APP_ENV", os.environ.get("ENVIRONMENT", "local")).lower()
        require_https = env == "production" and os.environ.get("ALLOW_INSECURE_WEBHOOKS", "").lower() not in {"1", "true", "yes", "on"}
    if require_https and scheme != "https":
        return OutboundURLDecision(False, "https_required", [])

    resolved: List[str] = []
    try:
        # Numeric IP addresses do not need DNS.
        resolved = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if scheme == "https" else 80), type=socket.SOCK_STREAM)
            resolved = sorted({info[4][0] for info in infos})
        except socket.gaierror:
            return OutboundURLDecision(False, "dns_resolution_failed", [])

    allow_private = os.environ.get("ALLOW_PRIVATE_WEBHOOKS", "").lower() in {"1", "true", "yes", "on"}
    if not allow_private:
        for ip in resolved:
            try:
                if _is_blocked_ip(ip):
                    return OutboundURLDecision(False, "blocked_private_or_metadata_ip", resolved)
            except ValueError:
                return OutboundURLDecision(False, "invalid_resolved_ip", resolved)

    return OutboundURLDecision(True, "allowed", resolved)


__all__ = ["OutboundURLDecision", "validate_outbound_url"]
