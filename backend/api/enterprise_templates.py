from __future__ import annotations
from fastapi import APIRouter, HTTPException
from backend.core.template_library import list_templates, get_template
router = APIRouter()
@router.get("/templates")
async def templates(): return {"templates": list_templates(), "count": len(list_templates())}
@router.get("/templates/{template_id}")
async def template_detail(template_id: str):
    template = get_template(template_id)
    if not template: raise HTTPException(status_code=404, detail="Template not found")
    return template
