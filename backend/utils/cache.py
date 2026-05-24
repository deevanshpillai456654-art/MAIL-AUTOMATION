"""
Cache management for AI Email Organizer
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

_log = logging.getLogger(__name__)


class Cache:
    def __init__(self, storage_path: str = None, max_age_seconds: int = 3600):
        if storage_path is None:
            base_path = Path(__file__).parent.parent / "data"
            base_path.mkdir(parents=True, exist_ok=True)
            storage_path = str(base_path / "cache.json")

        self.storage_path = storage_path
        self.max_age = max_age_seconds
        self.cache: Dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r") as f:
                    self.cache = json.load(f)
            except Exception as exc:
                self.cache = {}
                _log.warning("Could not load cache %s: %s", self.storage_path, exc)

    def _save(self):
        with open(self.storage_path, "w") as f:
            json.dump(self.cache, f, indent=2)

    def _generate_key(self, prefix: str, *args) -> str:
        key_string = f"{prefix}:{':'.join(str(a) for a in args)}"
        return hashlib.sha256(key_string.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry.get("timestamp", 0) < self.max_age:
                return entry.get("value")
            else:
                del self.cache[key]
                self._save()
        return None

    def set(self, key: str, value: Any):
        self.cache[key] = {
            "value": value,
            "timestamp": time.time()
        }
        self._save()

    def delete(self, key: str):
        if key in self.cache:
            del self.cache[key]
            self._save()

    def clear(self):
        self.cache = {}
        self._save()

    def clear_expired(self):
        current_time = time.time()
        expired = [
            k for k, v in self.cache.items()
            if current_time - v.get("timestamp", 0) >= self.max_age
        ]
        for key in expired:
            del self.cache[key]

        if expired:
            self._save()

        return len(expired)

    def get_stats(self) -> Dict:
        total_entries = len(self.cache)
        expired_entries = sum(
            1 for v in self.cache.values()
            if time.time() - v.get("timestamp", 0) >= self.max_age
        )

        return {
            "total_entries": total_entries,
            "expired_entries": expired_entries,
            "active_entries": total_entries - expired_entries,
            "max_age_seconds": self.max_age
        }


class ClassificationCache:
    def __init__(self):
        self.cache = Cache(max_age_seconds=1800)

    def get_cached_classification(self, subject: str, sender_email: str) -> Optional[Dict]:
        key = self.cache._generate_key("classify", subject, sender_email)
        return self.cache.get(key)

    def cache_classification(self, subject: str, sender_email: str, result: Dict):
        key = self.cache._generate_key("classify", subject, sender_email)
        self.cache.set(key, result)


classification_cache = ClassificationCache()


def cache_classification_result(subject: str, sender_email: str, result: Dict):
    classification_cache.cache_classification(subject, sender_email, result)


def get_cached_classification(subject: str, sender_email: str) -> Optional[Dict]:
    return classification_cache.get_cached_classification(subject, sender_email)


def clear_cache():
    classification_cache.cache.clear()


def get_cache_stats():
    return classification_cache.cache.get_stats()
