"""
Track secret age and emit rotation recommendations (operational, not cloud KMS).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class SecretRecord:
    name: str
    last_rotated_unix: float
    max_age_seconds: float

    def needs_rotation(self, now: Optional[float] = None) -> bool:
        now = now or time.time()
        return (now - self.last_rotated_unix) > self.max_age_seconds


class SecretsRotationRegistry:
    def __init__(self):
        self._secrets: Dict[str, SecretRecord] = {}
        self._lock = threading.RLock()

    def register(self, name: str, max_age_seconds: float, last_rotated_unix: Optional[float] = None) -> None:
        with self._lock:
            self._secrets[name] = SecretRecord(
                name=name,
                last_rotated_unix=last_rotated_unix or time.time(),
                max_age_seconds=max_age_seconds,
            )

    def mark_rotated(self, name: str) -> None:
        with self._lock:
            if name in self._secrets:
                self._secrets[name].last_rotated_unix = time.time()

    def due_for_rotation(self) -> List[str]:
        now = time.time()
        with self._lock:
            return [s.name for s in self._secrets.values() if s.needs_rotation(now)]


__all__ = ["SecretRecord", "SecretsRotationRegistry"]
