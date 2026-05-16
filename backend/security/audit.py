"""Structured security audit buffer and optional JSONL sink."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

from backend.security.redaction import redact

_MAX_EVENTS = int(os.environ.get("SECURITY_AUDIT_BUFFER", "500") or 500)
_EVENTS: Deque[Dict[str, Any]] = deque(maxlen=max(50, _MAX_EVENTS))
_LOCK = threading.RLock()


def _audit_path() -> Optional[Path]:
    raw = os.environ.get("SECURITY_AUDIT_LOG", "")
    if not raw:
        return None
    path = Path(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record_security_event(kind: str, *, severity: str = "info", details: Optional[Dict[str, Any]] = None, request: Any = None) -> Dict[str, Any]:
    event = {
        "id": f"sec_{uuid.uuid4().hex[:16]}",
        "ts": time.time(),
        "kind": str(kind)[:120],
        "severity": severity if severity in {"debug", "info", "warning", "error", "critical"} else "info",
        "details": redact(details or {}),
    }
    if request is not None:
        event["request"] = redact({
            "method": getattr(request, "method", ""),
            "path": getattr(getattr(request, "url", None), "path", ""),
            "client": getattr(getattr(request, "client", None), "host", "unknown"),
            "origin": getattr(request, "headers", {}).get("origin", "") if hasattr(request, "headers") else "",
        })
    with _LOCK:
        _EVENTS.append(event)
    sink = _audit_path()
    if sink:
        try:
            with sink.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, sort_keys=True) + "\n")
        except Exception:
            pass
    return event


def recent_security_events(limit: int = 100) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 100), _MAX_EVENTS))
    with _LOCK:
        return list(_EVENTS)[-limit:]


__all__ = ["record_security_event", "recent_security_events"]
