"""Production 95 readiness API endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends
from backend.auth.local_auth import require_local_auth_or_localhost

from backend.core.production_guardrails import run_local_guardrails
from backend.core.production_scorecard import assert_gate, build_scorecard
from backend.core.persistence_recovery_scorecard import assert_persistence_gate, build_persistence_recovery_scorecard
from backend.core.granular_production_scorecard import assert_granular_gate, build_granular_production_scorecard
from backend.core.analytics_engine import LocalAnalyticsEngine
from backend import config

router = APIRouter(dependencies=[Depends(require_local_auth_or_localhost)])


@router.get("/production/readiness-score")
async def readiness_score() -> Dict[str, Any]:
    scorecard = build_scorecard()
    return {**scorecard, "gate_passed": assert_gate(scorecard)}


@router.get("/production/guardrails")
async def production_guardrails() -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    return run_local_guardrails(root)

@router.get("/production/persistence-recovery-score")
async def persistence_recovery_score() -> Dict[str, Any]:
    scorecard = build_persistence_recovery_scorecard()
    return {**scorecard, "gate_passed": assert_persistence_gate(scorecard)}


@router.get("/production/granular-score")
async def granular_production_score() -> Dict[str, Any]:
    scorecard = build_granular_production_scorecard()
    return {**scorecard, "gate_passed": assert_granular_gate(scorecard)}


@router.get("/production/analytics/snapshot")
async def production_analytics_snapshot(force: bool = False) -> Dict[str, Any]:
    engine = LocalAnalyticsEngine(config.DB_PATH)
    return engine.snapshot(force=force)


@router.get("/production/analytics/validate")
async def production_analytics_validate() -> Dict[str, Any]:
    engine = LocalAnalyticsEngine(config.DB_PATH)
    return engine.validate_accuracy()

