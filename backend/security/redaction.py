"""Security redaction helpers.

All logs, telemetry, audit events and user-facing diagnostics pass through these
helpers before persistence or display.  The goal is to prevent accidental token,
password, cookie or OAuth-code disclosure while preserving enough structure for
operations teams to debug incidents.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|pwd|secret|token|access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|authorization|cookie|set-cookie|session|oauth|code[_-]?verifier|private[_-]?key|credential)",
    re.IGNORECASE,
)

SECRET_VALUE_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"(access_token|refresh_token|id_token|client_secret|password|api_key)=([^&\s]+)", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]


def redact_text(value: str, max_length: int = 1000) -> str:
    text = str(value)
    for pattern in SECRET_VALUE_PATTERNS:
        text = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]" if m.lastindex and m.lastindex >= 1 else "[REDACTED]", text)
    if len(text) > max_length:
        text = text[:max_length] + "…[truncated]"
    return text


def redact(value: Any, *, max_depth: int = 5, max_list: int = 50) -> Any:
    if max_depth <= 0:
        return "[truncated]"
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            key_text = str(key)
            if SENSITIVE_KEY_RE.search(key_text):
                out[key_text] = "[REDACTED]"
            else:
                out[key_text] = redact(item, max_depth=max_depth - 1, max_list=max_list)
        return out
    if isinstance(value, (list, tuple, set)):
        seq = list(value)[:max_list]
        result = [redact(item, max_depth=max_depth - 1, max_list=max_list) for item in seq]
        if len(value) > max_list:
            result.append(f"…[{len(value) - max_list} more]")
        return result
    if isinstance(value, str):
        return redact_text(value)
    return value


__all__ = ["redact", "redact_text", "SENSITIVE_KEY_RE"]
