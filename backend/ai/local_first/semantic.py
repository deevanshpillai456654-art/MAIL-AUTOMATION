"""Local semantic memory and vector search implementation."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from backend import config
except Exception:  # pragma: no cover
    class _Config:
        DATA_DIR = str(Path.cwd() / "data")
    config = _Config()  # type: ignore

from .runtime import get_runtime


@dataclass
class MemoryRecord:
    id: str
    namespace: str
    text: str
    metadata: Dict[str, Any]
    vector: List[float]
    created_at: float = field(default_factory=time.time)


class SemanticMemoryStore:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path or Path(config.DATA_DIR) / "semantic_memory_v9_1.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, MemoryRecord] = {}
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            self._records = {raw["id"]: MemoryRecord(**raw) for raw in payload.get("records", [])}
        except Exception:
            self._records = {}

    def _save(self) -> None:
        payload = {"version": "9.7.0", "backend": "json-local-vector", "records": [asdict(r) for r in self._records.values()]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def upsert(self, text: str, namespace: str = "emails", metadata: Optional[Dict[str, Any]] = None, record_id: Optional[str] = None) -> str:
        vector = get_runtime().embed(text).tolist()
        record = MemoryRecord(id=record_id or str(uuid.uuid4()), namespace=namespace, text=text, metadata=metadata or {}, vector=vector)
        with self._lock:
            self._records[record.id] = record
            self._save()
        return record.id

    def search(self, query: str, namespace: Optional[str] = None, top_k: int = 10) -> List[Dict[str, Any]]:
        q = get_runtime().embed(query)
        results: List[Dict[str, Any]] = []
        with self._lock:
            for record in self._records.values():
                if namespace and record.namespace != namespace:
                    continue
                v = np.array(record.vector, dtype=np.float32)
                denom = float(np.linalg.norm(q) * np.linalg.norm(v)) or 1.0
                score = float(np.dot(q, v) / denom)
                results.append({"id": record.id, "namespace": record.namespace, "text": record.text, "metadata": record.metadata, "score": round(score, 6)})
        return sorted(results, key=lambda item: item["score"], reverse=True)[: max(1, min(top_k, 50))]

    def status(self) -> Dict[str, Any]:
        with self._lock:
            namespaces: Dict[str, int] = {}
            for record in self._records.values():
                namespaces[record.namespace] = namespaces.get(record.namespace, 0) + 1
            return {
                "version": "9.7.0",
                "status": "ready",
                "backend": "local-json-vector",
                "supported_backends": ["SQLite vector extension", "local-json-vector"],
                "records": len(self._records),
                "namespaces": namespaces,
                "path": str(self.path),
            }


_store: Optional[SemanticMemoryStore] = None
_store_lock = threading.Lock()


def get_semantic_store() -> SemanticMemoryStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = SemanticMemoryStore()
        return _store
