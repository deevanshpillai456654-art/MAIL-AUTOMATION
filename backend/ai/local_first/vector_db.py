"""Vector DB compatibility wrapper for the lightweight local semantic store."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .semantic import get_semantic_store


class LocalVectorDB:
    def upsert(self, text: str, namespace: str = "emails", metadata: Optional[Dict[str, Any]] = None, record_id: Optional[str] = None) -> str:
        return get_semantic_store().upsert(text, namespace, metadata or {}, record_id)

    def search(self, query: str, namespace: Optional[str] = None, top_k: int = 10) -> list[Dict[str, Any]]:
        return get_semantic_store().search(query, namespace, top_k)

    def status(self) -> Dict[str, Any]:
        status = get_semantic_store().status()
        status["vector_db"] = "local-json-vector-with-sqlite-vector-ready-interface"
        status["allowed_backends"] = ["SQLite vector extension", "ChromaDB", "local-json-vector"]
        return status


_vector_db: LocalVectorDB | None = None


def get_vector_db() -> LocalVectorDB:
    global _vector_db
    if _vector_db is None:
        _vector_db = LocalVectorDB()
    return _vector_db
