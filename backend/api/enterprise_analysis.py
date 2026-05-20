from __future__ import annotations
from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from backend.auth.local_auth import require_local_auth_or_localhost
from backend.core.enterprise_email_analysis import analyze_email_content

router = APIRouter()

_auth = Depends(require_local_auth_or_localhost)


class AnalysisPayload(BaseModel):
    subject: str = ""
    sender_email: str = ""
    body: str = ""
    html: str = ""
    headers: Dict[str, Any] = Field(default_factory=dict)
    attachments: List[Any] = Field(default_factory=list)

@router.post("/analysis/email", dependencies=[_auth])
async def analyze_email(payload: AnalysisPayload):
    return analyze_email_content(payload.model_dump())

@router.post("/analysis/simulate", dependencies=[_auth])
async def simulate_analysis(payload: Dict[str, Any] = Body(default_factory=dict)):
    return analyze_email_content(payload)

@router.get("/analysis/capabilities")
async def analysis_capabilities():
    return {
        "inputs": ["subject", "body", "html", "plain_text", "attachments", "thread_history", "sender", "headers", "signatures"],
        "detections": ["RFQ", "quotation", "invoice", "shipment", "support", "complaint", "payment", "logistics", "customs", "urgent", "lead"],
        "entities": ["invoice_numbers", "tracking_ids", "phone_numbers", "emails", "dates", "container_numbers"],
        "status": "ready",
    }
