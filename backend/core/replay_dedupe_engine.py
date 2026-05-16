"""Replay dedupe engine with scope-aware fingerprints and TTL cleanup."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass
class DedupeRecord:
    fingerprint: str
    scope_key: str
    first_seen: float
    last_seen: float
    count: int = 1


class ReplayDedupeEngine:
    def __init__(self, ttl_seconds: float = 3600.0, max_records: int = 50000):
        self.ttl_seconds = ttl_seconds
        self.max_records = max(100, max_records)
        self._records: Dict[str, DedupeRecord] = {}
        self._lock = threading.RLock()

    def fingerprint(self, scope_key: str, event: Dict[str, Any]) -> str:
        stable = json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(f"{scope_key}:{stable}".encode("utf-8")).hexdigest()

    def seen_or_record(self, scope_key: str, event: Dict[str, Any]) -> Tuple[bool, str]:
        fp = self.fingerprint(scope_key, event)
        now = time.time()
        with self._lock:
            record = self._records.get(fp)
            if record:
                record.last_seen = now
                record.count += 1
                return True, fp
            self._records[fp] = DedupeRecord(fp, scope_key, now, now)
            if len(self._records) > self.max_records:
                self.cleanup(force=True)
            return False, fp

    def cleanup(self, force: bool = False) -> int:
        now = time.time()
        with self._lock:
            expired = [fp for fp, rec in self._records.items() if now - rec.last_seen > self.ttl_seconds]
            if force and len(self._records) - len(expired) > self.max_records:
                overflow = len(self._records) - self.max_records
                ordered = sorted(self._records.values(), key=lambda r: r.last_seen)
                expired.extend(rec.fingerprint for rec in ordered[:overflow])
            for fp in set(expired):
                self._records.pop(fp, None)
            return len(set(expired))

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return {"records": len(self._records), "duplicates": sum(max(0, r.count - 1) for r in self._records.values())}


__all__ = ["DedupeRecord", "ReplayDedupeEngine"]
