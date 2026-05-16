"""
Tracking router — unified shipment tracking engine.
Prefix: /tracking
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from ..shared.utils import utc_now_str

router = APIRouter(prefix="/tracking", tags=["tracking"])

CARRIER_LABELS = {
    "fedex": "FedEx", "ups": "UPS", "dhl": "DHL", "delhivery": "Delhivery",
    "shiprocket": "Shiprocket", "easypost": "EasyPost", "aftership": "AfterShip",
    "maersk": "Maersk", "msc": "MSC", "usps": "USPS", "aramex": "Aramex",
    "bluedart": "Blue Dart", "xpressbees": "XpressBees", "dtdc": "DTDC",
    "other": "Other",
}

DELAY_RISK_STATUSES = {"exception", "delay", "held", "customs_hold", "returned"}
DELIVERED_STATUSES = {"delivered", "out_for_delivery"}


def _row_to_shipment(row: dict) -> dict:
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "tracking_number": row["tracking_number"],
        "reference_number": row["reference_number"],
        "carrier": row["carrier"],
        "carrier_label": CARRIER_LABELS.get(row["carrier"], row["carrier"].title()),
        "tracking_type": row["tracking_type"],
        "status": row["status"],
        "origin_location": row["origin_location"],
        "destination_location": row["destination_location"],
        "shipper_name": row["shipper_name"],
        "consignee_name": row["consignee_name"],
        "estimated_delivery": row["estimated_delivery"],
        "actual_delivery": row["actual_delivery"],
        "weight_kg": row["weight_kg"],
        "pieces": row["pieces"],
        "description": row["description"],
        "order_ref": row["order_ref"],
        "invoice_ref": row["invoice_ref"],
        "vendor_ref": row["vendor_ref"],
        "ai_delay_risk": row["ai_delay_risk"],
        "ai_eta_predicted": row["ai_eta_predicted"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _assess_delay_risk(status: str, events: list[dict]) -> str:
    if status in DELAY_RISK_STATUSES:
        return "high"
    exception_count = sum(1 for e in events if "exception" in e.get("status", "").lower() or "delay" in e.get("description", "").lower())
    if exception_count >= 2:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", summary="List all shipments")
async def list_shipments(
    tenant_id: str = Query(...),
    carrier: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    tracking_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["tenant_id = ?"]
    params: list = [tenant_id]

    if carrier:
        conditions.append("carrier = ?"); params.append(carrier)
    if status:
        conditions.append("status = ?"); params.append(status)
    if tracking_type:
        conditions.append("tracking_type = ?"); params.append(tracking_type)
    if search:
        conditions.append("(tracking_number LIKE ? OR reference_number LIKE ? OR shipper_name LIKE ? OR consignee_name LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like, like])

    where = " AND ".join(conditions)
    rows = db.fetch_all(
        f"SELECT * FROM shipments WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM shipments WHERE {where}", params)
    return {
        "shipments": [_row_to_shipment(r) for r in rows],
        "total": total["c"] if total else 0,
        "limit": limit,
        "offset": offset,
    }


@router.post("", summary="Create / add shipment to track", status_code=status.HTTP_201_CREATED)
async def create_shipment(body: dict[str, Any]):
    db = get_panel_db()
    sid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        """
        INSERT INTO shipments (
            id, tenant_id, tracking_number, reference_number, carrier, tracking_type,
            status, origin_location, destination_location, shipper_name, consignee_name,
            estimated_delivery, weight_kg, pieces, description, order_ref, invoice_ref,
            vendor_ref, ai_delay_risk, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            sid, body.get("tenant_id", "default"), body.get("tracking_number", ""),
            body.get("reference_number"), body.get("carrier", "other"),
            body.get("tracking_type", "awb"), body.get("status", "pending"),
            body.get("origin_location"), body.get("destination_location"),
            body.get("shipper_name"), body.get("consignee_name"),
            body.get("estimated_delivery"), body.get("weight_kg"),
            body.get("pieces"), body.get("description"),
            body.get("order_ref"), body.get("invoice_ref"), body.get("vendor_ref"),
            "low", now, now,
        ),
    )
    row = db.fetch_one("SELECT * FROM shipments WHERE id = ?", (sid,))
    return _row_to_shipment(row)


@router.get("/stats", summary="Tracking dashboard stats")
async def tracking_stats(tenant_id: str = Query(...)):
    db = get_panel_db()
    row = db.fetch_one(
        """
        SELECT
            COUNT(*)                                                        AS total,
            SUM(CASE WHEN status='in_transit' THEN 1 ELSE 0 END)           AS in_transit,
            SUM(CASE WHEN status='delivered' THEN 1 ELSE 0 END)            AS delivered,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END)              AS pending,
            SUM(CASE WHEN status IN ('exception','delay') THEN 1 ELSE 0 END) AS exceptions,
            SUM(CASE WHEN ai_delay_risk='high' THEN 1 ELSE 0 END)          AS high_risk
        FROM shipments WHERE tenant_id = ?
        """,
        (tenant_id,),
    )
    def _i(k): return int(row.get(k) or 0) if row else 0
    return {
        "total": _i("total"), "in_transit": _i("in_transit"),
        "delivered": _i("delivered"), "pending": _i("pending"),
        "exceptions": _i("exceptions"), "high_risk": _i("high_risk"),
    }


@router.get("/{shipment_id}", summary="Get shipment detail")
async def get_shipment(shipment_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    row = db.fetch_one("SELECT * FROM shipments WHERE id = ? AND tenant_id = ?", (shipment_id, tenant_id))
    if not row:
        raise HTTPException(status_code=404, detail="Shipment not found")
    events = db.fetch_all(
        "SELECT * FROM tracking_events WHERE shipment_id = ? ORDER BY timestamp DESC",
        (shipment_id,),
    )
    result = _row_to_shipment(row)
    result["events"] = events
    return result


@router.post("/{shipment_id}/events", summary="Add tracking event")
async def add_tracking_event(shipment_id: str, body: dict[str, Any]):
    db = get_panel_db()
    shipment = db.fetch_one("SELECT * FROM shipments WHERE id = ?", (shipment_id,))
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    eid = str(uuid.uuid4())
    now = utc_now_str()
    new_status = body.get("status", shipment["status"])
    db.execute(
        "INSERT INTO tracking_events (id, shipment_id, tenant_id, status, location, description, carrier_code, timestamp, raw_json) VALUES (?,?,?,?,?,?,?,?,?)",
        (eid, shipment_id, shipment["tenant_id"], new_status, body.get("location"), body.get("description"), body.get("carrier_code"), body.get("timestamp", now), "{}"),
    )
    # Update shipment status
    events = db.fetch_all("SELECT * FROM tracking_events WHERE shipment_id = ?", (shipment_id,))
    risk = _assess_delay_risk(new_status, events)
    actual_delivery = now if new_status in DELIVERED_STATUSES else shipment.get("actual_delivery")
    db.execute(
        "UPDATE shipments SET status=?, ai_delay_risk=?, actual_delivery=?, updated_at=? WHERE id=?",
        (new_status, risk, actual_delivery, now, shipment_id),
    )
    return {"ok": True, "event_id": eid, "delay_risk": risk}


@router.patch("/{shipment_id}", summary="Update shipment")
async def update_shipment(shipment_id: str, body: dict[str, Any]):
    db = get_panel_db()
    shipment = db.fetch_one("SELECT * FROM shipments WHERE id = ?", (shipment_id,))
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    now = utc_now_str()
    allowed = {"status", "estimated_delivery", "actual_delivery", "description", "order_ref", "invoice_ref", "ai_delay_risk"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        db.execute(f"UPDATE shipments SET {set_clause}, updated_at=? WHERE id=?", list(updates.values()) + [now, shipment_id])
    return {"ok": True}


@router.delete("/{shipment_id}", summary="Delete shipment")
async def delete_shipment(shipment_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    db.execute("DELETE FROM shipments WHERE id=? AND tenant_id=?", (shipment_id, tenant_id))
    return {"ok": True}
