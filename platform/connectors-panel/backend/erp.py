"""
ERP router — vendors, purchase orders, invoices, inventory, warehouses.
Prefix: /erp
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from .db import get_panel_db
from ..shared.utils import utc_now_str

router = APIRouter(prefix="/erp", tags=["erp"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _int(v: Any) -> int:
    try:
        return int(v) if v is not None else 0
    except Exception:
        return 0


def _float(v: Any) -> float:
    try:
        return float(v) if v is not None else 0.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------

@router.get("/summary", summary="ERP dashboard summary")
async def erp_summary(tenant_id: str = Query(...)):
    db = get_panel_db()

    vendors = db.fetch_one("SELECT COUNT(*) AS c FROM erp_vendors WHERE tenant_id=? AND status='active'", (tenant_id,))
    po_row = db.fetch_one(
        "SELECT COUNT(*) AS c, SUM(total_amount) AS total FROM erp_purchase_orders WHERE tenant_id=?",
        (tenant_id,),
    )
    inv_row = db.fetch_one(
        "SELECT COUNT(*) AS c, SUM(amount) AS overdue FROM erp_invoices WHERE tenant_id=? AND status='overdue'",
        (tenant_id,),
    )
    inv_total = db.fetch_one("SELECT SUM(total_amount) AS t FROM erp_invoices WHERE tenant_id=?", (tenant_id,))
    stock_low = db.fetch_one(
        "SELECT COUNT(*) AS c FROM erp_inventory WHERE tenant_id=? AND quantity <= reorder_level AND status='active'",
        (tenant_id,),
    )
    wh = db.fetch_one("SELECT COUNT(*) AS c FROM erp_warehouses WHERE tenant_id=? AND status='active'", (tenant_id,))

    return {
        "active_vendors": _int(vendors["c"] if vendors else 0),
        "purchase_orders": _int(po_row["c"] if po_row else 0),
        "po_value": _float(po_row["total"] if po_row else 0),
        "overdue_invoices": _int(inv_row["c"] if inv_row else 0),
        "overdue_amount": _float(inv_row["overdue"] if inv_row else 0),
        "total_invoice_value": _float(inv_total["t"] if inv_total else 0),
        "low_stock_items": _int(stock_low["c"] if stock_low else 0),
        "active_warehouses": _int(wh["c"] if wh else 0),
    }


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------

@router.get("/vendors", summary="List vendors")
async def list_vendors(
    tenant_id: str = Query(...),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["tenant_id = ?"]
    params: list = [tenant_id]
    if status:
        conditions.append("status = ?"); params.append(status)
    if search:
        conditions.append("(name LIKE ? OR code LIKE ? OR email LIKE ?)")
        like = f"%{search}%"; params.extend([like, like, like])
    where = " AND ".join(conditions)
    rows = db.fetch_all(f"SELECT * FROM erp_vendors WHERE {where} ORDER BY name LIMIT ? OFFSET ?", params + [limit, offset])
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM erp_vendors WHERE {where}", params)
    return {"vendors": rows, "total": _int(total["c"] if total else 0)}


@router.post("/vendors", summary="Create vendor", status_code=status.HTTP_201_CREATED)
async def create_vendor(body: dict[str, Any]):
    db = get_panel_db()
    vid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO erp_vendors (id,tenant_id,name,code,email,phone,address_json,payment_terms,currency,category,status,tags_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (vid, body.get("tenant_id","default"), body["name"], body.get("code"), body.get("email"), body.get("phone"),
         body.get("address_json","{}"), body.get("payment_terms",30), body.get("currency","USD"),
         body.get("category"), body.get("status","active"), body.get("tags_json","[]"), now, now),
    )
    return db.fetch_one("SELECT * FROM erp_vendors WHERE id=?", (vid,))


@router.get("/vendors/{vendor_id}", summary="Get vendor")
async def get_vendor(vendor_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    row = db.fetch_one("SELECT * FROM erp_vendors WHERE id=? AND tenant_id=?", (vendor_id, tenant_id))
    if not row:
        raise HTTPException(status_code=404, detail="Vendor not found")
    pos = db.fetch_all("SELECT id,po_number,status,total_amount,currency,order_date FROM erp_purchase_orders WHERE vendor_id=? ORDER BY order_date DESC LIMIT 10", (vendor_id,))
    row["recent_pos"] = pos
    return row


@router.patch("/vendors/{vendor_id}", summary="Update vendor")
async def update_vendor(vendor_id: str, body: dict[str, Any]):
    db = get_panel_db()
    now = utc_now_str()
    allowed = {"name","code","email","phone","address_json","payment_terms","currency","category","status","tags_json"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        db.execute(f"UPDATE erp_vendors SET {', '.join(f'{k}=?' for k in updates)}, updated_at=? WHERE id=?", list(updates.values()) + [now, vendor_id])
    return {"ok": True}


@router.delete("/vendors/{vendor_id}", summary="Delete vendor")
async def delete_vendor(vendor_id: str, tenant_id: str = Query(...)):
    db = get_panel_db()
    db.execute("DELETE FROM erp_vendors WHERE id=? AND tenant_id=?", (vendor_id, tenant_id))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Purchase Orders
# ---------------------------------------------------------------------------

@router.get("/purchase-orders", summary="List purchase orders")
async def list_purchase_orders(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None),
    vendor_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["p.tenant_id = ?"]
    params: list = [tenant_id]
    if status:
        conditions.append("p.status = ?"); params.append(status)
    if vendor_id:
        conditions.append("p.vendor_id = ?"); params.append(vendor_id)
    where = " AND ".join(conditions)
    rows = db.fetch_all(
        f"SELECT p.*, v.name AS vendor_name FROM erp_purchase_orders p LEFT JOIN erp_vendors v ON p.vendor_id=v.id WHERE {where} ORDER BY p.order_date DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM erp_purchase_orders p WHERE {where}", params)
    return {"purchase_orders": rows, "total": _int(total["c"] if total else 0)}


@router.post("/purchase-orders", summary="Create purchase order", status_code=status.HTTP_201_CREATED)
async def create_purchase_order(body: dict[str, Any]):
    db = get_panel_db()
    pid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO erp_purchase_orders (id,tenant_id,vendor_id,po_number,status,items_json,subtotal,tax_amount,total_amount,currency,order_date,delivery_date,delivery_addr,notes,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid, body.get("tenant_id","default"), body.get("vendor_id"), body.get("po_number","PO-"+pid[:8].upper()),
         body.get("status","draft"), body.get("items_json","[]"), body.get("subtotal",0),
         body.get("tax_amount",0), body.get("total_amount",0), body.get("currency","USD"),
         body.get("order_date", now[:10]), body.get("delivery_date"), body.get("delivery_addr"),
         body.get("notes"), now, now),
    )
    return db.fetch_one("SELECT * FROM erp_purchase_orders WHERE id=?", (pid,))


@router.patch("/purchase-orders/{po_id}", summary="Update purchase order")
async def update_purchase_order(po_id: str, body: dict[str, Any]):
    db = get_panel_db()
    now = utc_now_str()
    allowed = {"status","items_json","subtotal","tax_amount","total_amount","delivery_date","delivery_addr","notes","approved_by","approved_at"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        db.execute(f"UPDATE erp_purchase_orders SET {', '.join(f'{k}=?' for k in updates)}, updated_at=? WHERE id=?", list(updates.values()) + [now, po_id])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

@router.get("/invoices", summary="List invoices")
async def list_invoices(
    tenant_id: str = Query(...),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["i.tenant_id = ?"]
    params: list = [tenant_id]
    if status:
        conditions.append("i.status = ?"); params.append(status)
    where = " AND ".join(conditions)
    rows = db.fetch_all(
        f"SELECT i.*, v.name AS vendor_name FROM erp_invoices i LEFT JOIN erp_vendors v ON i.vendor_id=v.id WHERE {where} ORDER BY i.invoice_date DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM erp_invoices i WHERE {where}", params)
    return {"invoices": rows, "total": _int(total["c"] if total else 0)}


@router.post("/invoices", summary="Create invoice", status_code=status.HTTP_201_CREATED)
async def create_invoice(body: dict[str, Any]):
    db = get_panel_db()
    iid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO erp_invoices (id,tenant_id,vendor_id,po_id,invoice_number,status,amount,tax_amount,total_amount,currency,invoice_date,due_date,paid_at,payment_method,notes,items_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (iid, body.get("tenant_id","default"), body.get("vendor_id"), body.get("po_id"),
         body.get("invoice_number","INV-"+iid[:8].upper()), body.get("status","draft"),
         body.get("amount",0), body.get("tax_amount",0), body.get("total_amount",0),
         body.get("currency","USD"), body.get("invoice_date", now[:10]), body.get("due_date"),
         body.get("paid_at"), body.get("payment_method"), body.get("notes"),
         body.get("items_json","[]"), now, now),
    )
    return db.fetch_one("SELECT * FROM erp_invoices WHERE id=?", (iid,))


@router.patch("/invoices/{invoice_id}", summary="Update invoice status")
async def update_invoice(invoice_id: str, body: dict[str, Any]):
    db = get_panel_db()
    now = utc_now_str()
    allowed = {"status","paid_at","payment_method","due_date","notes"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        db.execute(f"UPDATE erp_invoices SET {', '.join(f'{k}=?' for k in updates)}, updated_at=? WHERE id=?", list(updates.values()) + [now, invoice_id])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

@router.get("/inventory", summary="List inventory items")
async def list_inventory(
    tenant_id: str = Query(...),
    warehouse_id: Optional[str] = Query(None),
    low_stock: bool = Query(False),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    db = get_panel_db()
    conditions = ["i.tenant_id = ?"]
    params: list = [tenant_id]
    if warehouse_id:
        conditions.append("i.warehouse_id = ?"); params.append(warehouse_id)
    if low_stock:
        conditions.append("i.quantity <= i.reorder_level")
    where = " AND ".join(conditions)
    rows = db.fetch_all(
        f"SELECT i.*, w.name AS warehouse_name FROM erp_inventory i LEFT JOIN erp_warehouses w ON i.warehouse_id=w.id WHERE {where} ORDER BY i.name LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    total = db.fetch_one(f"SELECT COUNT(*) AS c FROM erp_inventory i WHERE {where}", params)
    return {"items": rows, "total": _int(total["c"] if total else 0)}


@router.post("/inventory", summary="Add inventory item", status_code=status.HTTP_201_CREATED)
async def create_inventory_item(body: dict[str, Any]):
    db = get_panel_db()
    iid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO erp_inventory (id,tenant_id,warehouse_id,sku,name,category,quantity,reserved,unit,reorder_level,cost_price,sell_price,status,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (iid, body.get("tenant_id","default"), body.get("warehouse_id"), body.get("sku","SKU-"+iid[:8].upper()),
         body["name"], body.get("category"), body.get("quantity",0), body.get("reserved",0),
         body.get("unit","pcs"), body.get("reorder_level",0), body.get("cost_price"),
         body.get("sell_price"), body.get("status","active"), now),
    )
    return db.fetch_one("SELECT * FROM erp_inventory WHERE id=?", (iid,))


@router.patch("/inventory/{item_id}", summary="Update inventory item")
async def update_inventory_item(item_id: str, body: dict[str, Any]):
    db = get_panel_db()
    now = utc_now_str()
    allowed = {"quantity","reserved","cost_price","sell_price","reorder_level","status","warehouse_id"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        db.execute(f"UPDATE erp_inventory SET {', '.join(f'{k}=?' for k in updates)}, updated_at=? WHERE id=?", list(updates.values()) + [now, item_id])
    return {"ok": True}


# ---------------------------------------------------------------------------
# Warehouses
# ---------------------------------------------------------------------------

@router.get("/warehouses", summary="List warehouses")
async def list_warehouses(tenant_id: str = Query(...)):
    db = get_panel_db()
    rows = db.fetch_all("SELECT * FROM erp_warehouses WHERE tenant_id=? ORDER BY name", (tenant_id,))
    return {"warehouses": rows, "total": len(rows)}


@router.post("/warehouses", summary="Create warehouse", status_code=status.HTTP_201_CREATED)
async def create_warehouse(body: dict[str, Any]):
    db = get_panel_db()
    wid = str(uuid.uuid4())
    now = utc_now_str()
    db.execute(
        "INSERT INTO erp_warehouses (id,tenant_id,name,code,location,address_json,capacity,current_stock,status,manager,contact_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (wid, body.get("tenant_id","default"), body["name"], body.get("code"),
         body.get("location"), body.get("address_json","{}"), body.get("capacity"),
         0, body.get("status","active"), body.get("manager"), body.get("contact_json","{}"), now, now),
    )
    return db.fetch_one("SELECT * FROM erp_warehouses WHERE id=?", (wid,))


@router.patch("/warehouses/{warehouse_id}", summary="Update warehouse")
async def update_warehouse(warehouse_id: str, body: dict[str, Any]):
    db = get_panel_db()
    now = utc_now_str()
    allowed = {"name","code","location","address_json","capacity","current_stock","status","manager"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if updates:
        db.execute(f"UPDATE erp_warehouses SET {', '.join(f'{k}=?' for k in updates)}, updated_at=? WHERE id=?", list(updates.values()) + [now, warehouse_id])
    return {"ok": True}
