"""AI provider management API router."""
from __future__ import annotations

import json
import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from .db import get_db, tx
from .models import AIProvider, AIProviderConfig, AIRequest, AIResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/providers", response_model=List[AIProviderConfig])
async def list_providers(tenant_id: str = Query(...)):
    rows = get_db().execute(
        "SELECT * FROM ai_provider_configs WHERE tenant_id=?", (tenant_id,)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        result.append(AIProviderConfig(
            provider=AIProvider(d["provider"]),
            base_url=d.get("base_url"),
            default_model=d.get("default_model"),
            enabled=bool(d.get("enabled", 1)),
            rate_limit_rpm=d.get("rate_limit_rpm", 60),
            metadata=json.loads(d.get("metadata_json") or "{}"),
        ))
    return result


@router.put("/providers/{provider}", response_model=AIProviderConfig)
async def upsert_provider(
    provider: AIProvider,
    config: AIProviderConfig,
    tenant_id: str = Query(...),
):
    from ..ai.provider import get_registry
    registry = get_registry()

    # Encrypt api_key if provided
    api_key_enc = None
    if config.api_key:
        try:
            from ...shared.crypto import encrypt
            api_key_enc = encrypt(config.api_key)
        except Exception:
            api_key_enc = config.api_key  # store plain if no crypto module

    with tx() as conn:
        conn.execute(
            """INSERT INTO ai_provider_configs
               (tenant_id,provider,api_key_enc,base_url,default_model,enabled,rate_limit_rpm,metadata_json)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(tenant_id,provider) DO UPDATE SET
                 api_key_enc=excluded.api_key_enc,
                 base_url=excluded.base_url,
                 default_model=excluded.default_model,
                 enabled=excluded.enabled,
                 rate_limit_rpm=excluded.rate_limit_rpm,
                 metadata_json=excluded.metadata_json""",
            (
                tenant_id, provider.value, api_key_enc,
                config.base_url, config.default_model,
                1 if config.enabled else 0,
                config.rate_limit_rpm,
                json.dumps(config.metadata),
            ),
        )

    # Update registry
    try:
        registry.configure_provider(provider, config)
    except Exception as exc:
        log.warning("Could not configure provider %s in registry: %s", provider, exc)

    return AIProviderConfig(
        provider=provider,
        base_url=config.base_url,
        default_model=config.default_model,
        enabled=config.enabled,
        rate_limit_rpm=config.rate_limit_rpm,
        metadata=config.metadata,
    )


@router.post("/complete", response_model=AIResponse)
async def ai_complete(request: AIRequest, tenant_id: str = Query(...)):
    """Run an AI completion through the configured provider."""
    from ..ai.provider import get_registry
    registry = get_registry()

    provider_key = request.provider
    if not provider_key:
        # Pick first enabled provider
        row = get_db().execute(
            "SELECT provider FROM ai_provider_configs WHERE tenant_id=? AND enabled=1 LIMIT 1",
            (tenant_id,),
        ).fetchone()
        if row:
            provider_key = AIProvider(row["provider"])
        else:
            raise HTTPException(400, "No AI provider configured")

    try:
        response = await registry.complete(provider_key, request)
    except Exception as exc:
        log.error("AI completion failed: %s", exc)
        raise HTTPException(500, f"AI provider error: {exc}")

    # Log usage
    from datetime import datetime
    with tx() as conn:
        conn.execute(
            "INSERT INTO ai_requests_log (tenant_id,provider,model,tokens_used,cost_estimate,latency_ms,created_at) VALUES (?,?,?,?,?,?,?)",
            (tenant_id, response.provider.value, response.model, response.tokens_used,
             response.cost_estimate, response.latency_ms, datetime.utcnow().isoformat()),
        )

    return response


@router.get("/usage")
async def ai_usage(tenant_id: str = Query(...), days: int = 7):
    conn = get_db()
    rows = conn.execute(
        """SELECT provider, SUM(tokens_used) as total_tokens, SUM(cost_estimate) as total_cost,
           COUNT(*) as requests, AVG(latency_ms) as avg_latency
           FROM ai_requests_log WHERE tenant_id=?
           AND created_at >= datetime('now', ? || ' days')
           GROUP BY provider""",
        (tenant_id, f"-{days}"),
    ).fetchall()
    return [dict(r) for r in rows]
