from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.auth.local_auth import require_local_auth_or_localhost
from backend.core.absolute_enterprise_governance import AbsoluteEnterpriseGovernanceEngine

router = APIRouter(dependencies=[Depends(require_local_auth_or_localhost)])
def engine() -> AbsoluteEnterpriseGovernanceEngine:
    return AbsoluteEnterpriseGovernanceEngine()
@router.get("/enterprise/certification")
async def enterprise_certification():
    return engine().overview()
@router.get("/enterprise/certification/runtime-audit")
async def enterprise_runtime_audit():
    return engine().runtime_audit()
@router.get("/enterprise/command-palette")
async def enterprise_command_palette():
    return {"actions": engine().command_palette_actions()}
@router.get("/enterprise/deployment-gates")
async def enterprise_deployment_gates():
    return {"gates": engine().deployment_gates()}
