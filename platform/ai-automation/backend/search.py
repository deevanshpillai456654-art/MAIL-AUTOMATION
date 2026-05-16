"""Semantic search API router."""
from __future__ import annotations

import time
from fastapi import APIRouter, Query
from .models import SearchRequest, SearchResponse, SearchResult

router = APIRouter(prefix="/search", tags=["search"])


@router.post("/", response_model=SearchResponse)
async def semantic_search(request: SearchRequest):
    start = time.time()
    from .db import get_db
    conn = get_db()

    results: list[SearchResult] = []
    q = f"%{request.query}%"

    # Search workflows
    rows = conn.execute(
        "SELECT id, name, description FROM workflows WHERE tenant_id=? AND (name LIKE ? OR description LIKE ?) LIMIT ?",
        (request.tenant_id, q, q, request.limit // 2),
    ).fetchall()
    for r in rows:
        results.append(SearchResult(
            id=r["id"], type="workflow", title=r["name"],
            snippet=r["description"] or "", score=0.8,
        ))

    # Search executions
    rows = conn.execute(
        "SELECT id, workflow_name FROM executions WHERE tenant_id=? AND workflow_name LIKE ? LIMIT ?",
        (request.tenant_id, q, request.limit // 2),
    ).fetchall()
    for r in rows:
        results.append(SearchResult(
            id=r["id"], type="execution", title=r["workflow_name"],
            snippet=f"Execution {r['id'][:8]}", score=0.6,
        ))

    took_ms = int((time.time() - start) * 1000)
    return SearchResponse(
        query=request.query,
        total=len(results),
        results=results[:request.limit],
        took_ms=took_ms,
    )
