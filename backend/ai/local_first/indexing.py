"""Semantic indexing worker for emails, workflows, and operational records."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from .semantic import get_semantic_store
from .telemetry import get_ai_telemetry


class SemanticIndexingWorker:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._indexed = 0
        self._failures = 0
        self._last_indexed_at: Optional[float] = None
        self._last_error: Optional[str] = None

    def index_record(self, text: str, namespace: str = "emails", metadata: Optional[Dict[str, Any]] = None, record_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            stored_id = get_semantic_store().upsert(text=text, namespace=namespace, metadata=metadata or {}, record_id=record_id)
            with self._lock:
                self._indexed += 1
                self._last_indexed_at = time.time()
            get_ai_telemetry().record("index", "semantic_indexing", "ok", metadata={"namespace": namespace})
            return {"status": "indexed", "id": stored_id, "namespace": namespace}
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._failures += 1
                self._last_error = str(exc)
            get_ai_telemetry().record("index", "semantic_indexing", "failed", metadata={"namespace": namespace, "error": str(exc)})
            raise

    def index_batch(self, records: List[Dict[str, Any]], namespace: str = "emails") -> Dict[str, Any]:
        results = []
        for record in records:
            text = str(record.get("text") or record.get("body") or record.get("subject") or "")
            if not text.strip():
                continue
            metadata = {key: value for key, value in record.items() if key not in {"text", "body"}}
            results.append(self.index_record(text, namespace, metadata, record.get("id")))
        return {"status": "completed", "indexed": len(results), "results": results}

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "version": "9.7.0",
                "status": "ready",
                "indexed_records": self._indexed,
                "failures": self._failures,
                "last_indexed_at": self._last_indexed_at,
                "last_error": self._last_error,
                "worker": "local-lightweight-semantic-indexer",
            }


_indexer: SemanticIndexingWorker | None = None
_indexer_lock = threading.Lock()


def get_indexing_worker() -> SemanticIndexingWorker:
    global _indexer
    with _indexer_lock:
        if _indexer is None:
            _indexer = SemanticIndexingWorker()
        return _indexer
