"""
Lightweight local-provider routing with circuit breaking and cooldown backoff.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("model_router")


class ProviderState(Enum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class ProviderHealth:
    name: str
    state: ProviderState = ProviderState.UP
    failures: int = 0
    cooldown_until: float = 0.0


class ModelRouter:
    def __init__(self, providers: Optional[List[str]] = None):
        self._order = providers or ["local", "onnxruntime", "local_vector"]
        self._health: Dict[str, ProviderHealth] = {p: ProviderHealth(name=p) for p in self._order}
        self._lock = threading.RLock()
        self._open_threshold = 5
        self._cooldown_sec = 30.0

    def _available(self, name: str, now: float) -> bool:
        h = self._health[name]
        if h.cooldown_until > now:
            return False
        if h.state == ProviderState.DOWN and h.cooldown_until <= now:
            h.state = ProviderState.DEGRADED
        return True

    def select_provider(self) -> Optional[str]:
        now = time.time()
        with self._lock:
            for name in self._order:
                if self._available(name, now):
                    return name
        return None

    def record_success(self, name: str) -> None:
        with self._lock:
            h = self._health.get(name)
            if h:
                h.failures = 0
                h.state = ProviderState.UP

    def record_failure(self, name: str) -> None:
        with self._lock:
            h = self._health.get(name)
            if not h:
                return
            h.failures += 1
            if h.failures >= self._open_threshold:
                h.state = ProviderState.DOWN
                h.cooldown_until = time.time() + self._cooldown_sec
                logger.warning("Provider %s entered cooldown", name)

    def route_call(self, funcs: Dict[str, Callable[[], Any]]) -> Any:
        now = time.time()
        with self._lock:
            order = [n for n in self._order if n in funcs and self._available(n, now)]
        last_exc: Optional[BaseException] = None
        for name in order:
            try:
                result = funcs[name]()
                self.record_success(name)
                return result
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                self.record_failure(name)
        if last_exc:
            raise last_exc
        raise RuntimeError("no_provider_available")


__all__ = ["ProviderState", "ProviderHealth", "ModelRouter"]
