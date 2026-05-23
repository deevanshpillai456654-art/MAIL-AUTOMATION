"""Structured security audit buffer and optional JSONL sink.

NOTE — there are two "audit" modules in this repo with different roles:

* THIS module (``backend.security.audit``) records **security events**
  (origin-validation rejections, request-signing failures, blocked referers,
  rate-limit warnings). Bounded in-memory ring buffer (500 entries by default)
  with an optional JSONL sink for SOC/forensic consumption. Called via
  ``record_security_event(...)`` from the middleware stack.

* ``backend.api.audit_log`` is the **operational audit log** — a
  persistent SQLite store that subscribes to the event bus and serves a
  paginated/filterable router for compliance and admin views.

They are intentionally separate: security buffer is fast/local/SOC-oriented,
operational audit log is durable/queryable/compliance-oriented.
"""
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
