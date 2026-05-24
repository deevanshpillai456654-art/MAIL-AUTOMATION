"""
Enterprise Hybrid Search Engine
================================

Hybrid BM25 + Vector search:
- BM25 indexing
- Vector indexing  
- Result fusion
- Tenant isolation
- Relevance tuning
"""

import logging
import math
import threading
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("hybrid_search")


class SearchType(Enum):
    BM25 = "bm25"
    VECTOR = "vector"
    HYBRID = "hybrid"


@dataclass
class SearchResult:
    """Search result"""
    result_id: str
    document_id: str
    score: float
    search_type: SearchType
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BM25Index:
    """BM25 inverted index"""
    term_doc_freq: Dict[str, Dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    doc_count: int = 0
    avg_dl: float = 0.0
    k1: float = 1.5
    b: float = 0.75

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.term_doc_freq = defaultdict(lambda: defaultdict(int))
        self.doc_count = 0
        self.avg_dl = 0.0
        self.k1 = k1
        self.b = b

    def add_document(self, doc_id: str, text: str):
        """Add document to index"""
        terms = text.lower().split()
        doc_len = len(terms)

        for term in terms:
            self.term_doc_freq[term][doc_id] += 1

        self.doc_count += 1
        self.avg_dl = ((self.avg_dl * (self.doc_count - 1)) + doc_len) / self.doc_count

    def score(self, doc_id: str, query: str) -> float:
        """Calculate BM25 score"""
        query_terms = query.lower().split()
        score = 0.0

        for term in query_terms:
            if term not in self.term_doc_freq:
                continue

            tf = self.term_doc_freq[term].get(doc_id, 0)
            if tf == 0:
                continue

            df = len(self.term_doc_freq[term])
            idf = math.log((self.doc_count - df + 0.5) / (df + 0.5) + 1)

            tf_score = (tf * (self.k1 + 1)) / (tf + self.k1 * (1 - self.b + self.b * (1)))

            score += idf * tf_score

        return score


class HybridSearchEngine:
    """Hybrid BM25 + Vector search"""

    def __init__(self):
        self._bm25_index = BM25Index()
        self._search_cache: Dict[str, List[SearchResult]] = {}
        self._document_vectors: Dict[str, List[float]] = {}
        self._lock = threading.RLock()

        self._config = {
            "bm25_weight": 0.5,
            "vector_weight": 0.5,
            "min_score": 0.1,
            "max_results": 100,
            "cache_ttl": 300
        }

        self._indexed_docs: Set[str] = set()

        logger.info("Hybrid search engine initialized")

    def index_document(self,
                       doc_id: str,
                       text: str,
                       vector: Optional[List[float]] = None,
                       metadata: Optional[Dict[str, Any]] = None):
        """Index document for search"""
        with self._lock:
            self._bm25_index.add_document(doc_id, text)

            if vector:
                self._document_vectors[doc_id] = vector

            self._indexed_docs.add(doc_id)

            self._search_cache.clear()

            logger.info(f"Document indexed: {doc_id}")

    def search(self,
             query: str,
             query_vector: Optional[List[float]] = None,
             search_type: SearchType = SearchType.HYBRID,
             tenant_filter: Optional[str] = None,
             limit: int = 10) -> List[SearchResult]:
        """Search documents"""
        results = []

        with self._lock:
            if search_type == SearchType.BM25:
                results = self._bm25_search(query, limit)
            elif search_type == SearchType.VECTOR:
                results = self._vector_search(query_vector, limit)
            else:
                bm25_results = self._bm25_search(query, limit * 2)
                vector_results = self._vector_search(query_vector, limit * 2)

                results = self._fusion(bm25_results, vector_results, limit)

        if tenant_filter:
            results = [r for r in results if r.metadata.get("tenant_id") == tenant_filter]

        return results[:limit]

    def _bm25_search(self, query: str, limit: int) -> List[SearchResult]:
        """BM25 search"""
        results = []

        for doc_id in self._indexed_docs:
            score = self._bm25_index.score(doc_id, query)

            if score > self._config["min_score"]:
                results.append(SearchResult(
                    result_id=str(uuid.uuid4()),
                    document_id=doc_id,
                    score=score,
                    search_type=SearchType.BM25,
                    metadata={"text": "indexed"}
                ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    def _vector_search(self,
                      query_vector: Optional[List[float]],
                      limit: int) -> List[SearchResult]:
        """Vector search"""
        if not query_vector:
            return []

        results = []

        for doc_id, vector in self._document_vectors.items():
            score = self._cosine_similarity(query_vector, vector)

            if score > self._config["min_score"]:
                results.append(SearchResult(
                    result_id=str(uuid.uuid4()),
                    document_id=doc_id,
                    score=score,
                    search_type=SearchType.VECTOR
                ))

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Calculate cosine similarity"""
        if len(v1) != len(v2):
            return 0.0

        dot = sum(a * b for a, b in zip(v1, v2))
        mag1 = math.sqrt(sum(a * a for a in v1))
        mag2 = math.sqrt(sum(b * b for b in v2))

        if mag1 == 0 or mag2 == 0:
            return 0.0

        return dot / (mag1 * mag2)

    def _fusion(self,
              bm25_results: List[SearchResult],
              vector_results: List[SearchResult],
              limit: int) -> List[SearchResult]:
        """Fuse BM25 and vector results"""
        scores: Dict[str, float] = {}

        bm25_weight = self._config["bm25_weight"]
        vector_weight = self._config["vector_weight"]

        for r in bm25_results:
            if r.document_id not in scores:
                scores[r.document_id] = 0.0
            scores[r.document_id] += r.score * bm25_weight

        for r in vector_results:
            if r.document_id not in scores:
                scores[r.document_id] = 0.0
            scores[r.document_id] += r.score * vector_weight

        fused = [
            SearchResult(
                result_id=str(uuid.uuid4()),
                document_id=doc_id,
                score=score,
                search_type=SearchType.HYBRID,
                metadata={"text": "fused"}
            )
            for doc_id, score in scores.items()
        ]

        fused.sort(key=lambda x: x.score, reverse=True)
        return fused[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get search statistics"""
        with self._lock:
            return {
                "indexed_documents": len(self._indexed_docs),
                "vectors": len(self._document_vectors),
                "cache_entries": len(self._search_cache)
            }


_global_search: Optional[HybridSearchEngine] = None


def get_search_engine() -> HybridSearchEngine:
    """Get global search engine"""
    global _global_search
    if _global_search is None:
        _global_search = HybridSearchEngine()
    return _global_search


__all__ = [
    "SearchType",
    "SearchResult",
    "BM25Index",
    "HybridSearchEngine",
    "get_search_engine"
]
