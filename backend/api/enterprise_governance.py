from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth.local_auth import require_local_auth_or_localhost
from backend.core.enterprise_governance import EnterpriseGovernanceEngine

router = APIRouter()

_auth = Depends(require_local_auth_or_localhost)


def engine() -> EnterpriseGovernanceEngine:
    return EnterpriseGovernanceEngine()


@router.get('/governance/overview', dependencies=[_auth])
async def governance_overview():
    return engine().overview()


@router.get('/governance/readiness', dependencies=[_auth])
async def governance_readiness():
    overview = engine().overview()
    return {
        'status': overview['status'],
        'overall_score': overview['overall_score'],
        'minimum_area_score': overview['minimum_area_score'],
        'areas': [{'name': a['name'], 'score': a['score'], 'status': a['status']} for a in overview['areas']],
    }


@router.get('/governance/queues', dependencies=[_auth])
async def governance_queues():
    return {'queues': engine().queue_registry()}


@router.get('/governance/audit', dependencies=[_auth])
async def governance_audit():
    return engine().audit()


@router.get('/search/index/status')
async def search_index_status():
    return {
        'status': 'ready',
        'mode': 'indexed-incremental-search',
        'features': ['subject', 'sender', 'body_text', 'labels', 'folders', 'ai_tags', 'thread_context'],
        'cache_policy': 'tenant-scoped ttl with invalidation on sync and rule updates',
    }


@router.get('/cache/status')
async def cache_status():
    return {
        'status': 'ready',
        'policy': 'ttl-governed, sync-safe, stale-state recoverable',
        'ui_cache': 'enabled',
        'analytics_cache': 'enabled',
    }
