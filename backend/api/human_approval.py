"""Human approval queue API."""
from __future__ import annotations

from typing import Any, Dict, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.ai.human_review_queue import HumanReviewQueue, ReviewItem
from backend.auth.local_auth import require_local_auth

router = APIRouter(prefix="/approvals", tags=["human-approval"])
_queue = HumanReviewQueue()


class ApprovalCreate(BaseModel):
    tenant_id: str = Field(default="default", min_length=1, max_length=160)
    reason: str = Field(..., min_length=1, max_length=240)
    payload: Dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    status: Literal["approved", "rejected"]


def _item_to_dict(item: ReviewItem) -> Dict[str, Any]:
    return {
        "id": item.item_id,
        "tenant_id": item.tenant_id,
        "reason": item.reason,
        "payload": item.payload,
        "created_at": item.created_at,
        "status": item.status,
    }


@router.post("", status_code=201)
async def create_approval(body: ApprovalCreate, _auth=Depends(require_local_auth)):
    item_id = _queue.enqueue(body.tenant_id, body.reason, body.payload)
    return {"id": item_id, "status": "pending"}


@router.get("")
async def list_approvals(
    tenant_id: str = Query("default", min_length=1, max_length=160),
    _auth=Depends(require_local_auth),
):
    items = [_item_to_dict(item) for item in _queue.pending_for_tenant(tenant_id)]
    return {"items": items, "count": len(items)}


@router.patch("/{item_id}")
async def decide_approval(item_id: str, body: ApprovalDecision, _auth=Depends(require_local_auth)):
    if not _queue.resolve(item_id, body.status):
        raise HTTPException(404, "Approval item not found")
    return {"id": item_id, "status": body.status}


def get_human_approval_queue() -> HumanReviewQueue:
    return _queue
