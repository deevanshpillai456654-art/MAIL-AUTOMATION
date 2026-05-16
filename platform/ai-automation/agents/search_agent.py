"""Search Agent – semantic search across platform data."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseAgent


class SearchAgent(BaseAgent):
    agent_type = "search"

    async def run(self, task_name: str, input_data: Dict[str, Any],
                  tenant_id: Optional[str] = None) -> Dict[str, Any]:
        if task_name == "search":
            return await self._search(input_data, tenant_id)
        elif task_name == "index":
            return await self._index(input_data, tenant_id)
        return {"error": f"Unknown search task: {task_name}"}

    async def _search(self, data: Dict, tenant_id: Optional[str]) -> Dict:
        query = data.get("query", "")
        if not query or not tenant_id:
            return {"results": [], "total": 0}

        from ..backend.models import SearchRequest
        from ..backend.search import semantic_search
        req = SearchRequest(
            query=query,
            tenant_id=tenant_id,
            limit=data.get("limit", 10),
        )
        response = await semantic_search(req)
        return {
            "results": [r.model_dump() for r in response.results],
            "total": response.total,
            "took_ms": response.took_ms,
        }

    async def _index(self, data: Dict, tenant_id: Optional[str]) -> Dict:
        # Placeholder – real implementation would update a vector store
        return {"indexed": True, "document_id": data.get("id")}
