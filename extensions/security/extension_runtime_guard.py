"""Zero-trust browser-extension runtime validation helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Set
import json
import re

_SECRET_PATTERN = re.compile(r"(access[_-]?token|refresh[_-]?token|password|client[_-]?secret|api[_-]?key|authorization|cookie)", re.I)

@dataclass(frozen=True)
class RuntimeDecision:
    allowed: bool
    reason: str = "allowed"

class ExtensionRuntimeGuard:
    """Validates extension messages before they reach privileged backend paths.

    The extension is treated as an untrusted renderer. This guard checks message
    type, size, origin, and plaintext secret leakage. It is intentionally small
    and deterministic so it can be reused by packaging and regression tests.
    """

    def __init__(self, allowed_types: Iterable[str] | None = None, max_payload_bytes: int = 65536):
        self.allowed_types: Set[str] = set(allowed_types or {
            "AIO_CLASSIFY_EMAIL", "AIO_SEND_FEEDBACK", "AIO_GET_STATUS",
            "AIO_GET_PROVIDERS", "AIO_RUNTIME_TELEMETRY",
        })
        self.max_payload_bytes = int(max_payload_bytes)

    def validate(self, message: Dict[str, Any]) -> RuntimeDecision:
        if not isinstance(message, dict):
            return RuntimeDecision(False, "message_not_object")
        if message.get("type") not in self.allowed_types:
            return RuntimeDecision(False, "unsupported_message_type")
        payload = message.get("payload", {})
        try:
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        except TypeError:
            return RuntimeDecision(False, "payload_not_json")
        if len(encoded) > self.max_payload_bytes:
            return RuntimeDecision(False, "payload_too_large")
        if _SECRET_PATTERN.search(json.dumps(payload, default=str)):
            return RuntimeDecision(False, "plaintext_secret_blocked")
        if not str(message.get("nonce", "")):
            return RuntimeDecision(False, "nonce_required")
        return RuntimeDecision(True)
