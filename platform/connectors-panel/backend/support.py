"""
Support router — ticketing, messages, SLA management.
Prefix: /support
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from ..shared.utils import utc_now_str

router = APIRouter(prefix="/support", tags=["support"])

TICKET_STATUSES = ["open", "in_progress", "pending", "resolved", "closed"]
PRIORITIES = ["low", "normal", "high", "urgent"]
CHANNELS = ["email", "whatsapp", "chat", "phone", "portal", "slack"]

SLA_HOURS = {"low": 48, "normal": 24, "high": 8, "urgent": 2}


def _int(v):
    try: return int(v) if v is not None else 0
    except: return 0


def _sla_due(priority: str, created_at: str) -> str:
    from datetime import datetime, timedelta
    hours = SLA_HOURS.get(priority, 24)
    try:
        base = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        due = base + timedelta(hours=hours)
        return due.isoformat()
    except Exception:
        return created_at


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

@router.get("/summary", summary="Support dashboard summary")
async def support_summary(tenant_id: str = Query(...)):
    db = get_panel_db()
    total = db.fetch_one("SELECT COUNT(*) AS c FROM support_tickets WHERE tenant_id=?", (tenant_id,))
    open_ = db.fetch_one("SELECT COUNT(*) AS c FROM support_tickets WHERE tenant_id=? AND status='open'", (tenant_id,))
    urgent = db.fetch_one("SELECT COUNT(*) AS c FROM support_tickets WHERE tenant_id=? AND priority='urgent' AND status NOT IN ('resolved','closed')", (tenant_id,))
    resolved = db.fetch_one("SELECT COUNT(*) AS c FROM support_tickets WHERE tenant_id=? AND status IN ('resolved','closed')", (tenant_id,))
    by_channel = db.fetch_all("SELECT channel, COUNT(*) AS c FROM support_tickets WHERE tenant_id=? GROUP BY channel", (tenant_id,))
    by_priority = db.fetch_all("SELECT priority, COUNT(*) AS c FROM support_tickets WHERE tenant_id=? AND status NOT IN ('resolved','closed') GROUP BY priority", (tenant_id,))
    return {
        "total_tickets": _int(total["c"] if total else 0),
        "open": _int(open_["c"] if open_ else 0),
        "urgent": _int(urgent["c"] if urgent else 0),
        "resolved": _int(resolved["c"] if resolved else 0),
        "by_channel": {r["channel"]: _int(r["c"]) for r in by_channel},
        "by_priority": {r["priority"]: _int(r["c"]) for r in by_priority},
    }


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------

@router.get("/tickets", summary="List tickets")
async def list_tickets(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["t.tenant_id = ?"]
    params: list = [tenant_id]
    if status:
        conditions.append("t.status = ?"); params.append(status)
    if priority:
        conditions.append("t.priority = ?"); params.append(priority)
    if channel:
        conditions.append("t.channel = ?"); params.append(channel)
    if assigned_to:
        conditions.append("t.assigned_to = ?"); params.append(assigned_to)
    if search:
        conditions.append("(t.subject LIKE ? OR t.ticket_number LIKE ?)")
        like = f"%{search}%"; params.extend([like, like])
    where = " AND ".join(conditions)
    rows = db.fetch_all(
        f"SELECT t.*, c.first_name||' '||COALESCE(c.last_name,'') AS contact_name FROM support_tickets t LEFT JOIN crm_contacts c ON t.contact_id=c.id WHERE {where} ORDER BY CASE t.priority WHEN 'urgent' THEN 1 WHEN 'high' THEN 2 WHEN 'normal' THEN 3 ELSE 4 END, t.created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM support_tickets t WHERE {where}", params)
    return {"tickets": rows, "total": _int(total["c"] if total else 0)}


@router.post("/tickets", summary="Create ticket", status_code=status.HTTP_201_CREATED)
async def create_ticket(body: dict[str, Any]):
    db = get_panel_db()
    tid = str(uuid.uuid4())
    now = utc_now_str()
    priority = body.get("priority", "normal")
    ticket_number = "TKT-" + tid[:8].upper()
    sla_due = _sla_due(priority, now)
    db.execute(
        "INSERT INTO support_tickets (id,tenant_id,contact_id,ticket_number,subject,description,status,priority,channel,assigned_to,tags_json,sla_due_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (tid, body.get("tenant_id","default"), body.get("contact_id"), ticket_number,
         body["subject"], body.get("description"), body.get("status","open"),
         priority, body.get("channel","email"), body.get("assigned_to"),
         body.get("tags_json","[]"), sla_due, now, now),
    )
    # Auto-add first message if description provided
    if body.get("description"):
        mid = str(uuid.uuid4())
        db.execute(
            "INSERT INTO support_messages (id,ticket_id,tenant_id,sender_type,sender_id,content,is_internal,attachments,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (mid, tid, body.get("tenant_id","default"), "customer", body.get("contact_id",""), body["description"], 0, "[]", now),
        )
    return db.fetch_one("SELECT * FROM support_tickets WHERE id=?", (tid,))


@router.get("/tickets/{ticket_id}", summary="Get ticket detail with messages")
async def get_ticket(ticket_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    row = db.fetch_one("SELECT * FROM support_tickets WHERE id=? AND tenant_id=?", (ticket_id, tenant_id))
    if not row:
        raise HTTPException(status_code=404, detail="Ticket not found")
    messages = db.fetch_all("SELECT * FROM support_messages WHERE ticket_id=? ORDER BY created_at ASC", (ticket_id,))
    row["messages"] = messages
    return row


@router.patch("/tickets/{ticket_id}", summary="Update ticket")
async def update_ticket(ticket_id: str, body: dict[str, Any]):
    db = get_panel_db()
    now = utc_now_str()
    allowed = {"status","priority","assigned_to","tags_json","resolved_at","first_response"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        db.execute(f"UPDATE support_tickets SET {', '.join(f'{k}=?' for k in updates)}, updated_at=? WHERE id=?", list(updates.values()) + [now, ticket_id])
    return {"ok": True}


@router.delete("/tickets/{ticket_id}", summary="Delete ticket")
async def delete_ticket(ticket_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    db.execute("DELETE FROM support_tickets WHERE id=? AND tenant_id=?", (ticket_id, tenant_id))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@router.get("/tickets/{ticket_id}/messages", summary="Get ticket messages")
async def get_messages(ticket_id: str):
    db = get_panel_db()
    rows = db.fetch_all("SELECT * FROM support_messages WHERE ticket_id=? ORDER BY created_at ASC", (ticket_id,))
    return {"messages": rows, "total": len(rows)}


@router.post("/tickets/{ticket_id}/messages", summary="Add message to ticket", status_code=status.HTTP_201_CREATED)
async def add_message(ticket_id: str, body: dict[str, Any]):
    db = get_panel_db()
    ticket = db.fetch_one("SELECT * FROM support_tickets WHERE id=?", (ticket_id,))
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    mid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO support_messages (id,ticket_id,tenant_id,sender_type,sender_id,content,is_internal,attachments,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (mid, ticket_id, ticket["tenant_id"], body.get("sender_type","agent"),
         body.get("sender_id"), body["content"], 1 if body.get("is_internal") else 0,
         body.get("attachments","[]"), now),
    )
    # If first agent response, record it
    if body.get("sender_type","agent") == "agent" and not ticket.get("first_response"):
        db.execute("UPDATE support_tickets SET first_response=?, updated_at=? WHERE id=?", (now, now, ticket_id))
    else:
        db.execute("UPDATE support_tickets SET updated_at=? WHERE id=?", (now, ticket_id))
    return {"ok": True, "message_id": mid}
