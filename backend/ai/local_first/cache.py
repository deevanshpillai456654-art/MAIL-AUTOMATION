"""Lightweight local AI cache with TTL and privacy-safe metadata.

The cache is intentionally local-only. It stores derived AI outputs, never OAuth
secrets or raw attachment payloads, and is safe for offline/air-gapped installs.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from backend import config
except Exception:  # pragma: no cover
    class _Config:
        CACHE_DIR = str(Path.cwd() / "cache")
    config = _Config()  # type: ignore

try:
    from backend.runtime_version import APP_VERSION
except Exception:  # pragma: no cover
    APP_VERSION = "9.7.0"


@dataclass
class AICacheEntry:
    key: str
    task: str
    payload_hash: str
    value: Dict[str, Any]
    created_at: float = field(default_factory=time.time)
    ttl_seconds: int = 86400

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds


class LocalAICache:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path or Path(config.CACHE_DIR) / "ai_cache_v9_1.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: Dict[str, AICacheEntry] = {}
        self._lock = threading.RLock()
        self._load()

    @staticmethod
    def fingerprint(task: str, payload: Dict[str, Any]) -> tuple[str, str]:
        normalized = json.dumps(payload, sort_keys=True, default=str)
        digest = hashlib.sha256(f"{task}:{normalized}".encode("utf-8")).hexdigest()
        return f"{task}:{digest}", digest

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._entries = {
                raw["key"]: AICacheEntry(**raw)
                for raw in payload.get("entries", [])
                if not AICacheEntry(**raw).expired
            }
        except Exception:
            self._entries = {}

    def _save(self) -> None:
        payload = {
            "version": APP_VERSION,
            "privacy": "derived_outputs_only",
            "entries": [asdict(entry) for entry in self._entries.values() if not entry.expired],
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, task: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key, _ = self.fingerprint(task, payload)
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            if entry.expired:
                self._entries.pop(key, None)
                self._save()
                return None
            return dict(entry.value)

    def set(self, task: str, payload: Dict[str, Any], value: Dict[str, Any], ttl_seconds: int = 86400) -> str:
        key, payload_hash = self.fingerprint(task, payload)
        with self._lock:
            self._entries[key] = AICacheEntry(
                key=key,
                task=task,
                payload_hash=payload_hash,
                value=value,
                ttl_seconds=ttl_seconds,
            )
            self._save()
        return key

    def status(self) -> Dict[str, Any]:
        with self._lock:
            active = [entry for entry in self._entries.values() if not entry.expired]
            return {
                "version": APP_VERSION,
                "status": "ready",
                "entries": len(active),
                "path": str(self.path),
                "stores_sensitive_content": False,
            }


_cache: Optional[LocalAICache] = None
_cache_lock = threading.Lock()


def get_ai_cache() -> LocalAICache:
    global _cache
    with _cache_lock:
        if _cache is None:
            _cache = LocalAICache()
        return _cache
