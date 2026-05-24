"""
Playbooks (Automation Engine)
==============================
Define sequential step sequences that execute automatically in response to
platform events or incidents, or that can be triggered manually.

Trigger types:
  manual    — REST POST only
  event     — subscribes to a specific event bus event type (supports * wildcard)
  incident  — subscribes to incident.created, filters by minimum severity

Step types:
  emit_event       — publish an event to the event bus
  trigger_workflow — run a workflow by template name
  webhook_post     — HTTP POST to a URL with JSON payload
  incident_comment — add a timeline comment to the triggering incident
  notify           — emit a platform notification event
  wait             — pause execution for N seconds (max 300)

Template variables: use {{key}} in string fields; resolved from the trigger context.
  Event trigger context: event_type, severity, source, event_id + all payload fields
  Incident trigger: incident_id, title, severity, rule_id + all payload fields

Tables:
  playbooks      — definitions (steps stored as JSON text)
  playbook_runs  — execution history with per-step log (JSON)

Endpoints:
  GET    /playbooks
  POST   /playbooks
  GET    /playbooks/runs
  GET    /playbooks/runs/{run_id}
  GET    /playbooks/{playbook_id}
  PATCH  /playbooks/{playbook_id}
  DELETE /playbooks/{playbook_id}
  POST   /playbooks/{playbook_id}/run
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.auth.local_auth import require_local_auth
from backend.config import DATA_DIR
from backend.core.runtime_control import get_runtime_control
from backend.security.ssrf import validate_outbound_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/playbooks", tags=["playbooks"])

_DB_PATH = str(Path(DATA_DIR) / "playbooks.db")
_subscribed = False

_SEV_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

_PB_COLS = [
    "id", "name", "description", "trigger_type", "trigger_filter",
    "steps", "enabled", "created_at", "updated_at", "run_count",
]
_RUN_COLS = [
    "id", "playbook_id", "playbook_name", "triggered_by",
    "trigger_context", "started_at", "finished_at",
    "status", "steps_total", "steps_done", "step_log",
]


# ── DB ────────────────────────────────────────────────────────────────────────

def _init_db() -> None:
    con = sqlite3.connect(_DB_PATH, timeout=10)
    con.executescript("""
        PRAGMA journal_mode=WAL;

        CREATE TABLE IF NOT EXISTS playbooks (
            id             TEXT PRIMARY KEY,
            name           TEXT NOT NULL,
            description    TEXT NOT NULL DEFAULT '',
            trigger_type   TEXT NOT NULL DEFAULT 'manual',
            trigger_filter TEXT NOT NULL DEFAULT '',
            steps          TEXT NOT NULL DEFAULT '[]',
            enabled        INTEGER NOT NULL DEFAULT 1,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL,
            run_count      INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS playbook_runs (
            id              TEXT PRIMARY KEY,
            playbook_id     TEXT NOT NULL,
            playbook_name   TEXT NOT NULL,
            triggered_by    TEXT NOT NULL DEFAULT 'manual',
            trigger_context TEXT NOT NULL DEFAULT '{}',
            started_at      TEXT NOT NULL,
            finished_at     TEXT,
            status          TEXT NOT NULL DEFAULT 'running',
            steps_total     INTEGER NOT NULL DEFAULT 0,
            steps_done      INTEGER NOT NULL DEFAULT 0,
            step_log        TEXT NOT NULL DEFAULT '[]'
        );

        CREATE INDEX IF NOT EXISTS idx_pb_enabled
            ON playbooks (enabled, trigger_type);
        CREATE INDEX IF NOT EXISTS idx_pr_playbook
            ON playbook_runs (playbook_id, started_at DESC);
    """)
    con.commit()
    con.close()


# Ensure schema exists at import — routers can be mounted directly without
# going through ensure_playbooks_running() (e.g. test clients).
try:
    _init_db()
except Exception:  # pragma: no cover
    logger.warning("Playbooks: schema init at import failed", exc_info=True)


def _conn() -> sqlite3.Connection:
    from backend.utils.sqlite_connection_guard import connect_with_defaults
    return connect_with_defaults(_DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Template rendering ────────────────────────────────────────────────────────

def _render(template: Any, context: dict) -> str:
    def replace(m: re.Match) -> str:
        key = m.group(1).strip()
        return str(context.get(key, m.group(0)))
    return re.sub(r"\{\{([^}]+)\}\}", replace, str(template))


def _render_dict(d: dict, context: dict) -> dict:
    return {k: _render(v, context) for k, v in d.items()}


# ── Step executor ─────────────────────────────────────────────────────────────

async def _http_post(url: str, payload: dict) -> bool:
    # Reject non-http(s) schemes to prevent file:/ and gopher:/ SSRF via webhook config.
    from urllib.parse import urlparse
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise RuntimeError(f"webhook url scheme {scheme!r} not allowed")
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code < 400
    except ImportError:
        import urllib.request
        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310 — scheme already validated
            return r.status < 400
    except Exception as exc:
        raise RuntimeError(f"HTTP POST failed: {exc}") from exc


async def _execute_step(step: dict, context: dict) -> dict:
    step_type = step.get("type", "")
    result: dict[str, Any] = {
        "type":   step_type,
        "status": "ok",
        "output": None,
        "error":  None,
        "ts":     _now(),
    }
    try:
        if step_type == "emit_event":
            from backend.api.event_bus import get_event_bus
            event_type = _render(step.get("event_type", "playbook.action"), context)
            raw_payload = step.get("payload") or {}
            payload = _render_dict(raw_payload, context) if isinstance(raw_payload, dict) else {}
            await get_event_bus().publish({
                "type":       event_type,
                "severity":   step.get("severity", "info"),
                "source":     "playbook_engine",
                "id":         str(uuid.uuid4()),
                "payload":    payload,
                "created_at": _now(),
            })
            result["output"] = f"Event '{event_type}' emitted"

        elif step_type == "trigger_workflow":
            from backend.api.workflows import trigger_workflow_by_template
            template = _render(step.get("template", ""), context)
            if not template:
                raise ValueError("trigger_workflow step missing 'template'")
            await trigger_workflow_by_template(
                template,
                input_data=context,
                trigger_type="playbook",
            )
            result["output"] = f"Workflow '{template}' triggered"

        elif step_type == "webhook_post":
            url = _render(step.get("url", ""), context)
            if not url:
                raise ValueError("webhook_post step missing 'url'")
            decision = validate_outbound_url(url)
            if not decision.allowed:
                raise ValueError(f"webhook_post URL not allowed: {decision.reason}")
            raw_payload = step.get("payload") or {}
            payload = _render_dict(raw_payload, context) if isinstance(raw_payload, dict) else {}
            success = await _http_post(url, payload)
            if not success:
                raise RuntimeError(f"POST to {url} returned error status")
            result["output"] = f"Posted to {url}"

        elif step_type == "incident_comment":
            from backend.api.incidents import _add_timeline
            incident_id = _render(step.get("incident_id", ""), context)
            note        = _render(step.get("note", "Playbook action executed"), context)
            if incident_id:
                _add_timeline(incident_id, actor="playbook_engine",
                              action="commented", note=note)
                result["output"] = f"Comment added to incident {incident_id}"
            else:
                result["status"] = "skipped"
                result["output"] = "No incident_id in context — step skipped"

        elif step_type == "notify":
            from backend.api.event_bus import get_event_bus
            message = _render(step.get("message", "Playbook notification"), context)
            await get_event_bus().publish({
                "type":       "playbook.notification",
                "severity":   step.get("severity", "info"),
                "source":     "playbook_engine",
                "id":         str(uuid.uuid4()),
                "payload":    {"description": message, "message": message},
                "created_at": _now(),
            })
            result["output"] = f"Notification sent: {message}"

        elif step_type == "wait":
            secs = min(max(0, int(step.get("seconds", 0))), 300)
            await asyncio.sleep(secs)
            result["output"] = f"Waited {secs}s"

        else:
            result["status"] = "error"
            result["error"]  = f"Unknown step type: '{step_type}'"

    except Exception as exc:
        result["status"] = "error"
        result["error"]  = str(exc)

    return result


# ── Run executor ──────────────────────────────────────────────────────────────

async def _run_playbook(playbook_id: str, trigger_context: dict) -> str:
    run_id = str(uuid.uuid4())
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_PB_COLS)} FROM playbooks WHERE id=?", (playbook_id,)
        ).fetchone()
        con.close()
    except Exception as exc:
        logger.error("Playbooks: load failed for %s: %s", playbook_id, exc)
        return run_id

    if not row:
        return run_id

    playbook = dict(zip(_PB_COLS, row))
    steps: list[dict] = []
    try:
        steps = json.loads(playbook.get("steps", "[]"))
    except Exception:
        pass

    now = _now()
    triggered_by = trigger_context.pop("_trigger_type", "manual")

    try:
        con = _conn()
        con.execute(
            f"INSERT INTO playbook_runs ({','.join(_RUN_COLS)}) "
            f"VALUES ({','.join(['?']*len(_RUN_COLS))})",
            (run_id, playbook_id, playbook["name"], triggered_by,
             json.dumps(trigger_context), now, None,
             "running", len(steps), 0, "[]"),
        )
        con.execute("UPDATE playbooks SET run_count=run_count+1 WHERE id=?", (playbook_id,))
        con.commit()
        con.close()
    except Exception as exc:
        logger.error("Playbooks: failed to create run record: %s", exc)
        return run_id

    step_log: list[dict] = []
    final_status = "completed"

    for step in steps:
        step_result = await _execute_step(step, dict(trigger_context))
        step_log.append(step_result)

        if step_result["status"] == "error" and step.get("halt_on_error", False):
            final_status = "failed"
            break

    finished_at = _now()
    try:
        con = _conn()
        con.execute(
            "UPDATE playbook_runs SET status=?, finished_at=?, steps_done=?, step_log=? WHERE id=?",
            (final_status, finished_at, len(step_log), json.dumps(step_log), run_id),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.error("Playbooks: failed to finalize run %s: %s", run_id, exc)

    return run_id


# ── Event bus subscriptions ───────────────────────────────────────────────────

def _make_event_handler(playbook_id: str):
    async def handler(event: dict) -> None:
        ctx = {
            "_trigger_type": "event",
            "event_type":    event.get("type", ""),
            "severity":      event.get("severity", ""),
            "source":        event.get("source", ""),
            "event_id":      event.get("id", ""),
            **{k: str(v) for k, v in (event.get("payload") or {}).items()},
        }
        asyncio.create_task(_run_playbook(playbook_id, ctx))
    return handler


def _make_incident_handler(playbook_id: str, min_severity: str):
    async def handler(event: dict) -> None:
        sev = event.get("severity", "info")
        if _SEV_RANK.get(sev, 0) >= _SEV_RANK.get(min_severity, 0):
            payload = event.get("payload") or {}
            ctx = {
                "_trigger_type": "incident",
                "severity":      sev,
                **{k: str(v) for k, v in payload.items()},
            }
            asyncio.create_task(_run_playbook(playbook_id, ctx))
    return handler


def _subscribe_playbook(pb: dict) -> None:
    try:
        from backend.api.event_bus import get_event_bus
        bus = get_event_bus()
        if pb["trigger_type"] == "event":
            event_type = pb["trigger_filter"] or "*"
            bus.subscribe(event_type, _make_event_handler(pb["id"]))
        elif pb["trigger_type"] == "incident":
            min_sev = pb["trigger_filter"] or "high"
            bus.subscribe("incident.created", _make_incident_handler(pb["id"], min_sev))
    except Exception as exc:
        logger.warning("Playbooks: subscription failed for %s: %s", pb["id"], exc)


def ensure_playbooks_running() -> None:
    global _subscribed
    if _subscribed:
        return
    if not get_runtime_control().is_service_enabled("playbooks"):
        logger.info("Playbooks disabled by runtime policy")
        return
    _init_db()
    _subscribed = True
    try:
        con = _conn()
        rows = con.execute(
            f"SELECT {','.join(_PB_COLS)} FROM playbooks "
            "WHERE enabled=1 AND trigger_type IN ('event','incident') LIMIT 10000"
        ).fetchall()
        con.close()
        for row in rows:
            _subscribe_playbook(dict(zip(_PB_COLS, row)))
        logger.info("Playbooks: initialized (%d auto-subscriptions)", len(rows))
    except Exception as exc:
        logger.warning("Playbooks: startup subscription failed: %s", exc)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class PlaybookCreate(BaseModel):
    name:           str = Field(min_length=1, max_length=200)
    description:    str = Field(default="", max_length=10000)
    trigger_type:   str = Field(default="manual", max_length=64)
    trigger_filter: str = Field(default="", max_length=1000)
    steps:          list = []
    enabled:        bool = True


class PlaybookPatch(BaseModel):
    name:           Optional[str]  = Field(default=None, max_length=200)
    description:    Optional[str]  = Field(default=None, max_length=10000)
    trigger_type:   Optional[str]  = Field(default=None, max_length=64)
    trigger_filter: Optional[str]  = Field(default=None, max_length=1000)
    steps:          Optional[list] = None
    enabled:        Optional[bool] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", summary="List playbooks")
async def list_playbooks(
    limit:  int = Query(200, ge=1, le=1000),
    offset: int = Query(0,   ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        total = con.execute("SELECT COUNT(*) FROM playbooks").fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_PB_COLS)} FROM playbooks ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        con.close()
    except Exception:
        return {"playbooks": [], "total": 0}
    result = []
    for row in rows:
        pb = dict(zip(_PB_COLS, row))
        pb["steps"] = json.loads(pb.get("steps", "[]"))
        result.append(pb)
    return {"playbooks": result, "total": total, "limit": limit, "offset": offset}


@router.post("", status_code=201, summary="Create playbook")
async def create_playbook(body: PlaybookCreate, _auth=Depends(require_local_auth)):
    if body.trigger_type not in ("manual", "event", "incident"):
        raise HTTPException(400, "trigger_type must be manual|event|incident")
    pb_id = str(uuid.uuid4())
    now   = _now()
    try:
        con = _conn()
        con.execute(
            f"INSERT INTO playbooks ({','.join(_PB_COLS)}) VALUES ({','.join(['?']*len(_PB_COLS))})",
            (pb_id, body.name, body.description, body.trigger_type, body.trigger_filter,
             json.dumps(body.steps), 1 if body.enabled else 0, now, now, 0),
        )
        con.commit()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    if body.enabled and body.trigger_type in ("event", "incident"):
        _subscribe_playbook({
            "id": pb_id, "name": body.name,
            "trigger_type": body.trigger_type, "trigger_filter": body.trigger_filter,
        })
    return {"id": pb_id, "name": body.name}


# ── Sub-routes before /{playbook_id} ──────────────────────────────────────────

@router.get("/runs", summary="Recent playbook runs (all playbooks)")
async def list_runs(
    limit:  int = Query(50, ge=1, le=500),
    offset: int = Query(0,  ge=0),
    _auth=Depends(require_local_auth),
):
    try:
        con = _conn()
        total = con.execute("SELECT COUNT(*) FROM playbook_runs").fetchone()[0]
        rows  = con.execute(
            f"SELECT {','.join(_RUN_COLS)} FROM playbook_runs "
            "ORDER BY started_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        con.close()
    except Exception:
        return {"runs": [], "total": 0}
    runs = []
    for row in rows:
        r = dict(zip(_RUN_COLS, row))
        r.pop("step_log", None)
        r.pop("trigger_context", None)
        runs.append(r)
    return {"runs": runs, "total": total, "limit": limit, "offset": offset}


@router.get("/runs/{run_id}", summary="Run detail with step log")
async def get_run(run_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_RUN_COLS)} FROM playbook_runs WHERE id=?", (run_id,)
        ).fetchone()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    if not row:
        raise HTTPException(404, "Run not found")
    r = dict(zip(_RUN_COLS, row))
    for field in ("step_log", "trigger_context"):
        if r.get(field):
            try:
                r[field] = json.loads(r[field])
            except Exception:
                pass
    return r


# ── Playbook-specific routes ──────────────────────────────────────────────────

@router.get("/{playbook_id}", summary="Playbook detail")
async def get_playbook(playbook_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            f"SELECT {','.join(_PB_COLS)} FROM playbooks WHERE id=?", (playbook_id,)
        ).fetchone()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    if not row:
        raise HTTPException(404, "Playbook not found")
    pb = dict(zip(_PB_COLS, row))
    pb["steps"] = json.loads(pb.get("steps", "[]"))
    return pb


@router.patch("/{playbook_id}", summary="Update playbook")
async def patch_playbook(
    playbook_id: str, body: PlaybookPatch, _auth=Depends(require_local_auth)
):
    updates, params = [], []
    if body.name is not None:
        updates.append("name = ?"); params.append(body.name)
    if body.description is not None:
        updates.append("description = ?"); params.append(body.description)
    if body.trigger_type is not None:
        if body.trigger_type not in ("manual", "event", "incident"):
            raise HTTPException(400, "trigger_type must be manual|event|incident")
        updates.append("trigger_type = ?"); params.append(body.trigger_type)
    if body.trigger_filter is not None:
        updates.append("trigger_filter = ?"); params.append(body.trigger_filter)
    if body.steps is not None:
        updates.append("steps = ?"); params.append(json.dumps(body.steps))
    if body.enabled is not None:
        updates.append("enabled = ?"); params.append(1 if body.enabled else 0)
    if not updates:
        raise HTTPException(400, "No fields to update")
    updates.append("updated_at = ?"); params.append(_now())
    params.append(playbook_id)
    try:
        con = _conn()
        con.execute(f"UPDATE playbooks SET {', '.join(updates)} WHERE id=?", params)
        if con.execute("SELECT changes()").fetchone()[0] == 0:
            con.close()
            raise HTTPException(404, "Playbook not found")
        con.commit()
        con.close()
    except HTTPException:
        raise
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    return {"ok": True}


@router.delete("/{playbook_id}", status_code=204, summary="Delete playbook")
async def delete_playbook(playbook_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        con.execute("DELETE FROM playbook_runs WHERE playbook_id=?", (playbook_id,))
        con.execute("DELETE FROM playbooks WHERE id=?", (playbook_id,))
        con.commit()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")


@router.post("/{playbook_id}/run", summary="Trigger playbook manually")
async def trigger_playbook(playbook_id: str, _auth=Depends(require_local_auth)):
    try:
        con = _conn()
        row = con.execute(
            "SELECT id, name FROM playbooks WHERE id=?", (playbook_id,)
        ).fetchone()
        con.close()
    except Exception:
        logger.exception("DB operation failed")
        raise HTTPException(500, "Internal server error")
    if not row:
        raise HTTPException(404, "Playbook not found")
    ctx = {"_trigger_type": "manual"}
    run_id = await _run_playbook(playbook_id, ctx)
    return {"ok": True, "run_id": run_id}
