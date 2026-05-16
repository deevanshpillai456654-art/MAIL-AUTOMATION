"""Privacy-preserving AI telemetry and diagnostics for local-first runtime."""

from __future__ import annotations

import atexit
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_FLUSH_INTERVAL_SECONDS = 30   # background flush cadence
_FLUSH_THRESHOLD = 50          # flush immediately after this many new events

try:
    from backend import config
except Exception:  # pragma: no cover
    class _Config:
        DATA_DIR = str(Path.cwd() / "data")
    config = _Config()  # type: ignore

try:
    from backend.runtime_version import APP_VERSION
except Exception:  # pragma: no cover
    APP_VERSION = "9.7.0"


@dataclass
class AITelemetryEvent:
    event_type: str
    component: str
    status: str
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class LocalAITelemetry:
    SENSITIVE_KEYS = {"body", "text", "content", "attachment", "token", "password", "oauth", "secret"}

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path or Path(config.DATA_DIR) / "ai_telemetry_v9_1.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._events: List[AITelemetryEvent] = []
        self._lock = threading.RLock()
        self._dirty = False
        self._new_since_flush = 0
        self._load()
        self._start_flush_thread()
        atexit.register(self._flush_if_dirty)

    def _sanitize(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        clean: Dict[str, Any] = {}
        for key, value in (metadata or {}).items():
            lowered = str(key).lower()
            if any(sensitive in lowered for sensitive in self.SENSITIVE_KEYS):
                clean[key] = "[redacted]"
            elif isinstance(value, (str, int, float, bool)) or value is None:
                clean[key] = value
            else:
                clean[key] = str(type(value).__name__)
        return clean

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._events = [AITelemetryEvent(**raw) for raw in payload.get("events", [])][-1000:]
        except Exception:
            self._events = []

    def _save(self) -> None:
        payload = {
            "version": APP_VERSION,
            "privacy": {
                "email_content_uploaded": False,
                "attachments_uploaded": False,
                "oauth_tokens_uploaded": False,
                "diagnostics_only": True,
            },
            "events": [asdict(event) for event in self._events[-1000:]],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def _start_flush_thread(self) -> None:
        t = threading.Thread(target=self._flush_loop, daemon=True, name="telemetry_flush")
        t.start()

    def _flush_loop(self) -> None:
        while True:
            time.sleep(_FLUSH_INTERVAL_SECONDS)
            self._flush_if_dirty()

    def _flush_if_dirty(self) -> None:
        with self._lock:
            if self._dirty:
                self._save()
                self._dirty = False
                self._new_since_flush = 0

    def record(self, event_type: str, component: str, status: str, latency_ms: float = 0.0, metadata: Optional[Dict[str, Any]] = None) -> None:
        with self._lock:
            self._events.append(AITelemetryEvent(event_type, component, status, latency_ms, self._sanitize(metadata or {})))
            self._events = self._events[-1000:]
            self._dirty = True
            self._new_since_flush += 1
            if self._new_since_flush >= _FLUSH_THRESHOLD:
                self._save()
                self._dirty = False
                self._new_since_flush = 0

    def status(self) -> Dict[str, Any]:
        with self._lock:
            failures = sum(1 for event in self._events if event.status not in {"ok", "ready", "completed"})
            by_component: Dict[str, int] = {}
            for event in self._events:
                by_component[event.component] = by_component.get(event.component, 0) + 1
            return {
                "version": APP_VERSION,
                "status": "ready",
                "events": len(self._events),
                "failures": failures,
                "components": by_component,
                "path": str(self.path),
                "privacy": "diagnostics_only_no_email_content",
            }


_telemetry: Optional[LocalAITelemetry] = None
_telemetry_lock = threading.Lock()


def get_ai_telemetry() -> LocalAITelemetry:
    global _telemetry
    with _telemetry_lock:
        if _telemetry is None:
            _telemetry = LocalAITelemetry()
        return _telemetry
