"""
CRM router — contacts, leads, opportunities, pipeline, activities.
Prefix: /crm
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from ..shared.utils import utc_now_str

router = APIRouter(prefix="/crm", tags=["crm"])

PIPELINE_STAGES = ["prospecting", "qualification", "proposal", "negotiation", "closed_won", "closed_lost"]


def _int(v: Any) -> int:
    try: return int(v) if v is not None else 0
    except: return 0

def _float(v: Any) -> float:
    try: return float(v) if v is not None else 0.0
    except: return 0.0


# ---------------------------------------------------------------------------
# CRM Dashboard summary
# ---------------------------------------------------------------------------

@router.get("/summary", summary="CRM dashboard summary")
async def crm_summary(tenant_id: str = Query(...)):
    db = get_panel_db()
    contacts = db.fetch_one("SELECT COUNT(*) AS c FROM crm_contacts WHERE tenant_id=? AND status='active'", (tenant_id,))
    leads = db.fetch_one("SELECT COUNT(*) AS c FROM crm_leads WHERE tenant_id=? AND status NOT IN ('closed','lost')", (tenant_id,))
    opps = db.fetch_one("SELECT COUNT(*) AS c, SUM(value) AS pipeline FROM crm_opportunities WHERE tenant_id=? AND stage NOT IN ('closed_won','closed_lost')", (tenant_id,))
    won = db.fetch_one("SELECT COUNT(*) AS c, SUM(value) AS revenue FROM crm_opportunities WHERE tenant_id=? AND stage='closed_won'", (tenant_id,))
    acts = db.fetch_one("SELECT COUNT(*) AS c FROM crm_activities WHERE tenant_id=? AND completed_at IS NULL", (tenant_id,))
    return {
        "active_contacts": _int(contacts["c"] if contacts else 0),
        "open_leads": _int(leads["c"] if leads else 0),
        "open_opportunities": _int(opps["c"] if opps else 0),
        "pipeline_value": _float(opps["pipeline"] if opps else 0),
        "won_deals": _int(won["c"] if won else 0),
        "won_revenue": _float(won["revenue"] if won else 0),
        "pending_activities": _int(acts["c"] if acts else 0),
        "pipeline_stages": PIPELINE_STAGES,
    }


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

@router.get("/contacts", summary="List contacts")
async def list_contacts(
    tenant_id: str = Query(...),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    company: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["tenant_id = ?"]
    params: list = [tenant_id]
    if status:
        conditions.append("status = ?"); params.append(status)
    if company:
        conditions.append("company LIKE ?"); params.append(f"%{company}%")
    if search:
        conditions.append("(first_name LIKE ? OR last_name LIKE ? OR email LIKE ? OR company LIKE ?)")
        like = f"%{search}%"; params.extend([like, like, like, like])
    where = " AND ".join(conditions)
    rows = db.fetch_all(f"SELECT * FROM crm_contacts WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params + [limit, offset])  # nosec B608
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM crm_contacts WHERE {where}", params)  # nosec B608
    return {"contacts": rows, "total": _int(total["c"] if total else 0)}


@router.post("/contacts", summary="Create contact", status_code=status.HTTP_201_CREATED)
async def create_contact(body: dict[str, Any], tenant_id: str = Query(...)):
    db = get_panel_db()
    cid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO crm_contacts (id,tenant_id,first_name,last_name,email,phone,company,job_title,source,status,lead_score,tags_json,custom_fields,assigned_to,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, tenant_id, body["first_name"], body.get("last_name"),
         body.get("email"), body.get("phone"), body.get("company"), body.get("job_title"),
         body.get("source"), body.get("status","active"), _int(body.get("lead_score", 0)),
         body.get("tags_json","[]"), body.get("custom_fields","{}"), body.get("assigned_to"), now, now),
    )
    return db.fetch_one("SELECT * FROM crm_contacts WHERE id=?", (cid,))


@router.get("/contacts/{contact_id}", summary="Get contact detail")
async def get_contact(contact_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    row = db.fetch_one("SELECT * FROM crm_contacts WHERE id=? AND tenant_id=?", (contact_id, tenant_id))
    if not row:
        raise HTTPException(status_code=404, detail="Contact not found")
    leads = db.fetch_all("SELECT id,title,status,score FROM crm_leads WHERE contact_id=? AND tenant_id=? LIMIT 5", (contact_id, tenant_id))
    opps = db.fetch_all("SELECT id,title,stage,value,currency FROM crm_opportunities WHERE contact_id=? AND tenant_id=? LIMIT 5", (contact_id, tenant_id))
    activities = db.fetch_all("SELECT * FROM crm_activities WHERE contact_id=? AND tenant_id=? ORDER BY created_at DESC LIMIT 10", (contact_id, tenant_id))
    row["leads"] = leads
    row["opportunities"] = opps
    row["activities"] = activities
    return row


@router.patch("/contacts/{contact_id}", summary="Update contact")
async def update_contact(contact_id: str, body: dict[str, Any], tenant_id: str = Query(...)):
    db = get_panel_db()
    now = utc_now_str()
    allowed = {"first_name","last_name","email","phone","company","job_title","source","status","lead_score","tags_json","custom_fields","assigned_to"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if "lead_score" in updates:
        updates["lead_score"] = _int(updates["lead_score"])
    if updates:
        db.execute(f"UPDATE crm_contacts SET {', '.join(f'{k}=?' for k in updates)}, updated_at=? WHERE id=? AND tenant_id=?", list(updates.values()) + [now, contact_id, tenant_id])  # nosec B608
    return {"ok": True}


@router.delete("/contacts/{contact_id}", summary="Delete contact")
async def delete_contact(contact_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    db.execute("DELETE FROM crm_contacts WHERE id=? AND tenant_id=?", (contact_id, tenant_id))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------

@router.get("/leads", summary="List leads")
async def list_leads(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["l.tenant_id = ?"]
    params: list = [tenant_id]
    if status:
        conditions.append("l.status = ?"); params.append(status)
    where = " AND ".join(conditions)
    rows = db.fetch_all(
        f"SELECT l.*, c.first_name||' '||COALESCE(c.last_name,'') AS contact_name, c.company FROM crm_leads l LEFT JOIN crm_contacts c ON l.contact_id=c.id WHERE {where} ORDER BY l.score DESC, l.created_at DESC LIMIT ? OFFSET ?",  # nosec B608
        params + [limit, offset],
    )
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM crm_leads l WHERE {where}", params)  # nosec B608
    return {"leads": rows, "total": _int(total["c"] if total else 0)}


@router.post("/leads", summary="Create lead", status_code=status.HTTP_201_CREATED)
async def create_lead(body: dict[str, Any], tenant_id: str = Query(...)):
    db = get_panel_db()
    lid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO crm_leads (id,tenant_id,contact_id,title,source,status,score,estimated_value,currency,assigned_to,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (lid, tenant_id, body.get("contact_id"), body["title"],
         body.get("source"), body.get("status","new"), _int(body.get("score", 0)),
         body.get("estimated_value"), body.get("currency","USD"), body.get("assigned_to"),
         body.get("notes"), now, now),
    )
    return db.fetch_one("SELECT * FROM crm_leads WHERE id=?", (lid,))


@router.patch("/leads/{lead_id}", summary="Update lead")
async def update_lead(lead_id: str, body: dict[str, Any], tenant_id: str = Query(...)):
    db = get_panel_db()
    now = utc_now_str()
    allowed = {"title","source","status","score","estimated_value","assigned_to","notes"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if "score" in updates:
        updates["score"] = _int(updates["score"])
    if updates:
        db.execute(f"UPDATE crm_leads SET {', '.join(f'{k}=?' for k in updates)}, updated_at=? WHERE id=? AND tenant_id=?", list(updates.values()) + [now, lead_id, tenant_id])  # nosec B608
    return {"ok": True}


# ---------------------------------------------------------------------------
# Opportunities / Pipeline
# ---------------------------------------------------------------------------

@router.get("/opportunities", summary="List opportunities")
async def list_opportunities(
    tenant_id: str = Query(...),
    stage: Optional[str] = Query(None),
    assigned_to: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["o.tenant_id = ?"]
    params: list = [tenant_id]
    if stage:
        conditions.append("o.stage = ?"); params.append(stage)
    if assigned_to:
        conditions.append("o.assigned_to = ?"); params.append(assigned_to)
    where = " AND ".join(conditions)
    rows = db.fetch_all(
        f"SELECT o.*, c.first_name||' '||COALESCE(c.last_name,'') AS contact_name, c.company FROM crm_opportunities o LEFT JOIN crm_contacts c ON o.contact_id=c.id WHERE {where} ORDER BY o.value DESC LIMIT ? OFFSET ?",  # nosec B608
        params + [limit, offset],
    )
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM crm_opportunities o WHERE {where}", params)  # nosec B608
    return {"opportunities": rows, "total": _int(total["c"] if total else 0)}


@router.get("/pipeline", summary="Pipeline board by stage")
async def get_pipeline(tenant_id: str = Query(...)):
    db = get_panel_db()
    result = {}
    for stage in PIPELINE_STAGES:
        rows = db.fetch_all(
            "SELECT o.id,o.title,o.value,o.currency,o.probability,o.close_date,o.assigned_to,c.first_name||' '||COALESCE(c.last_name,'') AS contact_name,c.company FROM crm_opportunities o LEFT JOIN crm_contacts c ON o.contact_id=c.id WHERE o.tenant_id=? AND o.stage=? ORDER BY o.value DESC",
            (tenant_id, stage),
        )
        result[stage] = {"deals": rows, "count": len(rows), "total_value": sum(_float(r["value"]) for r in rows)}
    return result


@router.post("/opportunities", summary="Create opportunity", status_code=status.HTTP_201_CREATED)
async def create_opportunity(body: dict[str, Any], tenant_id: str = Query(...)):
    db = get_panel_db()
    oid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO crm_opportunities (id,tenant_id,contact_id,lead_id,title,stage,value,currency,probability,close_date,assigned_to,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (oid, tenant_id, body.get("contact_id"), body.get("lead_id"),
         body["title"], body.get("stage","prospecting"), body.get("value",0),
         body.get("currency","USD"), body.get("probability",0), body.get("close_date"),
         body.get("assigned_to"), body.get("notes"), now, now),
    )
    return db.fetch_one("SELECT * FROM crm_opportunities WHERE id=?", (oid,))


@router.patch("/opportunities/{opp_id}", summary="Update opportunity / move stage")
async def update_opportunity(opp_id: str, body: dict[str, Any], tenant_id: str = Query(...)):
    db = get_panel_db()
    now = utc_now_str()
    allowed = {"title","stage","value","probability","close_date","assigned_to","notes","won_at","lost_at","lost_reason"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        db.execute(f"UPDATE crm_opportunities SET {', '.join(f'{k}=?' for k in updates)}, updated_at=? WHERE id=? AND tenant_id=?", list(updates.values()) + [now, opp_id, tenant_id])  # nosec B608
    return {"ok": True}


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------

@router.get("/activities", summary="List activities")
async def list_activities(
    tenant_id: str = Query(...),
    contact_id: Optional[str] = Query(None),
    opportunity_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["tenant_id = ?"]
    params: list = [tenant_id]
    if contact_id:
        conditions.append("contact_id = ?"); params.append(contact_id)
    if opportunity_id:
        conditions.append("opportunity_id = ?"); params.append(opportunity_id)
    where = " AND ".join(conditions)
    rows = db.fetch_all(f"SELECT * FROM crm_activities WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", params + [limit, offset])  # nosec B608
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM crm_activities WHERE {where}", params)  # nosec B608
    return {"activities": rows, "total": _int(total["c"] if total else 0)}


@router.post("/activities", summary="Log activity", status_code=status.HTTP_201_CREATED)
async def create_activity(body: dict[str, Any], tenant_id: str = Query(...)):
    db = get_panel_db()
    aid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO crm_activities (id,tenant_id,contact_id,opportunity_id,activity_type,subject,description,outcome,scheduled_at,completed_at,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (aid, tenant_id, body.get("contact_id"), body.get("opportunity_id"),
         body.get("activity_type","note"), body.get("subject"), body.get("description"),
         body.get("outcome"), body.get("scheduled_at"), body.get("completed_at"),
         body.get("created_by"), now),
    )
    return db.fetch_one("SELECT * FROM crm_activities WHERE id=?", (aid,))
