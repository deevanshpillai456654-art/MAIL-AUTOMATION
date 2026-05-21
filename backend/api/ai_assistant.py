"""
AI assistant API router.

Endpoints:
  GET  /assistant/issues                    — full issue index
  GET  /assistant/issues/{id}               — single issue detail + steps
  GET  /assistant/issues/search?q=…         — keyword search
  GET  /assistant/categories                — category list

  POST /assistant/session                   — create session, run auto-diagnostics
  GET  /assistant/session/{id}              — get session state
  DELETE /assistant/session/{id}            — close session
  POST /assistant/session/{id}/flow         — start or change active flow
  POST /assistant/session/{id}/advance      — advance to next step
  GET  /assistant/session/{id}/step         — get current step without advancing

  GET  /assistant/diagnostics               — full diagnostic report
  GET  /assistant/diagnostics/quick         — fast subset (DB + accounts)

  GET  /assistant/actions                   — list available actions
  GET  /assistant/actions/{id}              — action detail (impact, rollback)
  POST /assistant/actions/{id}/execute      — execute a safe action

All endpoints except /diagnostics and /actions require a session.
Admin endpoints require ?mode=admin query param or X-Assistant-Mode: admin header.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from backend.auth.local_auth import require_local_auth_or_localhost
from pydantic import BaseModel

from backend.core.assistant import (
    get_action_handler,
    get_diagnostics_engine,
    get_flow_engine,
    get_session_manager,
)

router = APIRouter(tags=["assistant"], dependencies=[Depends(require_local_auth_or_localhost)])
logger = logging.getLogger("assistant.api")


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_admin(request: Request, x_assistant_mode: Optional[str] = None) -> bool:
    mode_header = x_assistant_mode or request.headers.get("x-assistant-mode", "")
    mode_param  = request.query_params.get("mode", "")
    return (mode_header.lower() == "admin") or (mode_param.lower() == "admin")


async def _require_session(session_id: str):
    session = await get_session_manager().get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    return session


# ── request/response models ───────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    mode: str = "user"          # "user" | "admin"
    run_diagnostics: bool = True


class StartFlowRequest(BaseModel):
    issue_id: str


class AdvanceRequest(BaseModel):
    outcome: str = "ok"         # "ok" | "failed"


class ExecuteActionRequest(BaseModel):
    params: Dict[str, Any] = {}
    confirmed: bool = False     # must be True for confirm_required actions


# ── issues / knowledge base ───────────────────────────────────────────────────

@router.get("/assistant/issues")
async def list_issues():
    """Return the full issue index for the category browser."""
    return {"issues": get_flow_engine().issue_index()}


@router.get("/assistant/issues/search")
async def search_issues(q: str = Query(..., min_length=2)):
    """Keyword-search the knowledge base."""
    results = get_flow_engine().search_issues(q)
    return {"query": q, "results": results}


@router.get("/assistant/issues/{issue_id}")
async def get_issue(issue_id: str, request: Request,
                    x_assistant_mode: Optional[str] = Header(default=None)):
    """Return full issue detail including all steps and SVG visuals."""
    admin = _is_admin(request, x_assistant_mode)
    detail = get_flow_engine().get_issue_detail(issue_id, admin=admin)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Issue '{issue_id}' not found")
    return detail


@router.get("/assistant/categories")
async def list_categories():
    return {"categories": get_flow_engine().categories()}


# ── session management ────────────────────────────────────────────────────────

@router.post("/assistant/session", status_code=201)
async def create_session(body: CreateSessionRequest, request: Request,
                          x_assistant_mode: Optional[str] = Header(default=None)):
    """
    Create a new troubleshooting session.

    Optionally runs the full diagnostics scan and pre-selects the most
    relevant issue flows based on current runtime state.
    """
    # admin override from header always wins
    mode = body.mode
    if _is_admin(request, x_assistant_mode):
        mode = "admin"

    context: Dict[str, Any] = {}
    suggested = []

    if body.run_diagnostics:
        try:
            report = get_diagnostics_engine().run(admin=(mode == "admin"))
            context = {
                "overall": report.overall,
                "detected_issues": report.detected_issues,
                "signals": report.signals,
                "recommendations": report.recommendations,
            }
            suggested = get_flow_engine().suggested_issues(report.signals)
            if mode == "admin":
                context["admin_context"] = report.admin_context
        except Exception as exc:
            logger.warning("Diagnostics failed during session creation: %s", exc)
            context = {"error": str(exc)}

    session = await get_session_manager().create(mode=mode, context=context)
    session.add_history("session_created", {"mode": mode, "diagnostics_ran": body.run_diagnostics})

    return {
        "session_id": session.session_id,
        "mode": session.mode,
        "diagnostics": context,
        "suggested_issues": suggested,
    }


@router.get("/assistant/session/{session_id}")
async def get_session(session_id: str):
    session = await _require_session(session_id)
    return {
        "session": session.to_dict(),
        "current_step": get_flow_engine().current_step(session),
    }


@router.delete("/assistant/session/{session_id}")
async def close_session(session_id: str):
    await get_session_manager().delete(session_id)
    return {"closed": True}


# ── flow navigation ───────────────────────────────────────────────────────────

@router.post("/assistant/session/{session_id}/flow")
async def start_flow(session_id: str, body: StartFlowRequest):
    """Start (or restart) a guided flow for the given issue."""
    session = await _require_session(session_id)
    result = get_flow_engine().start_flow(session, body.issue_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/assistant/session/{session_id}/advance")
async def advance_step(session_id: str, body: AdvanceRequest):
    """
    Advance the session to the next step.

    - outcome='ok'     → move to next step
    - outcome='failed' → redirect to if_fails_issue (if defined) or advance anyway
    """
    session = await _require_session(session_id)
    return get_flow_engine().advance(session, outcome=body.outcome)


@router.get("/assistant/session/{session_id}/step")
async def get_current_step(session_id: str):
    """Return the current step without advancing."""
    session = await _require_session(session_id)
    step = get_flow_engine().current_step(session)
    if step is None:
        return {"message": "No active flow or flow completed"}
    return step


# ── diagnostics ───────────────────────────────────────────────────────────────

@router.get("/assistant/diagnostics")
async def full_diagnostics(request: Request,
                            x_assistant_mode: Optional[str] = Header(default=None)):
    """
    Run a full diagnostic scan.

    Returns component health, auto-detected issues, and recommendations.
    Admin mode includes additional metadata and raw probe data.
    """
    admin = _is_admin(request, x_assistant_mode)
    report = get_diagnostics_engine().run(admin=admin)
    return {
        "overall": report.overall,
        "timestamp": report.timestamp,
        "components": [
            {"name": c.name, "status": c.status, "message": c.message,
             **({"metadata": c.metadata} if admin else {})}
            for c in report.components
        ],
        "detected_issues": report.detected_issues,
        "suggested_flows": get_flow_engine().suggested_issues(report.signals),
        "recommendations": report.recommendations,
        **({"admin_context": report.admin_context} if admin else {}),
    }


@router.get("/assistant/diagnostics/quick")
async def quick_diagnostics():
    """Fast health pulse (DB + accounts). Used by the dashboard liveness bar."""
    return get_diagnostics_engine().quick_check()


# ── actions ───────────────────────────────────────────────────────────────────

@router.get("/assistant/actions")
async def list_actions(request: Request,
                        x_assistant_mode: Optional[str] = Header(default=None)):
    admin = _is_admin(request, x_assistant_mode)
    return {"actions": get_action_handler().list_actions(admin=admin)}


@router.get("/assistant/actions/{action_id}")
async def get_action_detail(action_id: str, request: Request,
                             x_assistant_mode: Optional[str] = Header(default=None)):
    admin = _is_admin(request, x_assistant_mode)
    defn = get_action_handler().get_definition(action_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found")
    if defn.admin_only and not admin:
        raise HTTPException(status_code=403, detail="Admin mode required for this action")
    import dataclasses
    return dataclasses.asdict(defn)


@router.post("/assistant/actions/{action_id}/execute")
async def execute_action(action_id: str, body: ExecuteActionRequest,
                          request: Request,
                          session_id: Optional[str] = Query(default=None),
                          x_assistant_mode: Optional[str] = Header(default=None)):
    """
    Execute a safe guided action.

    For confirm_required actions: body.confirmed must be True.
    Optionally attach to a session to log the action in session history.
    """
    admin = _is_admin(request, x_assistant_mode)
    handler = get_action_handler()

    defn = handler.get_definition(action_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"Action '{action_id}' not found")
    if defn.admin_only and not admin:
        raise HTTPException(status_code=403, detail="Admin mode required")
    if defn.confirm_required and not body.confirmed:
        return {
            "requires_confirmation": True,
            "action_id": action_id,
            "impact": defn.impact,
            "rollback": defn.rollback,
            "message": f"Please confirm: {defn.description}",
        }

    result = handler.execute(action_id, params=body.params, admin=admin)

    if session_id:
        session = await get_session_manager().get(session_id)
        if session:
            session.record_action(action_id, {
                "success": result.success,
                "message": result.message,
            })

    return {
        "action_id": action_id,
        "success": result.success,
        "message": result.message,
        "detail": result.detail,
        "data": result.data,
    }
