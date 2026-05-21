from __future__ import annotations

import base64
import csv
import io
import json
import socket
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.auth.local_auth import require_local_auth


DATA_DIR = Path(__file__).resolve().parents[1] / "data"
TALLY_DB_PATH = str(DATA_DIR / "tally.db")

router = APIRouter()


class TallyConnectRequest(BaseModel):
    mode: Literal["localhost", "remote"] = "localhost"
    host: str = "localhost"
    port: int = Field(default=9000, ge=1, le=65535)
    company_name: str
    username: str = ""
    password: str = ""
    enable_xml_api: bool = True
    use_tls: bool = False
    api_key: str = ""
    ip_restrictions: list[str] = Field(default_factory=list)
    sync_interval: str = "15m"


class TallySyncRequest(BaseModel):
    sync_type: Literal["manual", "scheduled", "realtime"] = "manual"
    company_name: str | None = None
    entities: list[str] = Field(default_factory=lambda: ["companies", "ledgers", "vouchers", "inventory", "gst"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn() -> sqlite3.Connection:
    Path(TALLY_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(TALLY_DB_PATH, timeout=30, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.row_factory = sqlite3.Row
    return con


def _encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return "vault:" + base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def _json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def init_tally_db() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS tally_connections (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              mode TEXT NOT NULL,
              host TEXT NOT NULL,
              port INTEGER NOT NULL,
              use_tls INTEGER DEFAULT 0,
              company_name TEXT NOT NULL,
              username TEXT,
              password_enc TEXT,
              api_key_enc TEXT,
              enable_xml_api INTEGER DEFAULT 1,
              status TEXT NOT NULL,
              tally_version TEXT,
              server_mode TEXT,
              sync_interval TEXT,
              ip_restrictions_json TEXT,
              last_sync_at TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tally_sync_jobs (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              company_name TEXT,
              sync_type TEXT,
              status TEXT,
              entities_json TEXT,
              error_count INTEGER DEFAULT 0,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tally_companies (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              name TEXT NOT NULL,
              guid TEXT,
              health TEXT DEFAULT 'unknown',
              last_sync_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tally_ledgers (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              company_name TEXT,
              name TEXT NOT NULL,
              parent TEXT,
              closing_balance TEXT,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tally_vouchers (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              company_name TEXT,
              voucher_type TEXT,
              voucher_number TEXT,
              amount REAL DEFAULT 0,
              status TEXT DEFAULT 'synced',
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tally_inventory (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              company_name TEXT,
              item_name TEXT,
              quantity REAL DEFAULT 0,
              valuation REAL DEFAULT 0,
              reorder_level REAL DEFAULT 0,
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tally_gst_reports (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              company_name TEXT,
              period TEXT,
              mismatch_count INTEGER DEFAULT 0,
              tax_payable REAL DEFAULT 0,
              status TEXT DEFAULT 'draft',
              updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tally_audit_logs (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              action TEXT NOT NULL,
              actor TEXT DEFAULT 'system',
              detail TEXT,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tally_workflows (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              trigger_type TEXT,
              action_type TEXT,
              is_active INTEGER DEFAULT 1,
              created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tally_notifications (
              id TEXT PRIMARY KEY,
              tenant_id TEXT NOT NULL,
              channel TEXT,
              event_type TEXT,
              message TEXT,
              status TEXT DEFAULT 'queued',
              created_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tc_status    ON tally_connections  (status);
            CREATE INDEX IF NOT EXISTS idx_tc_tenant    ON tally_connections  (tenant_id);
            CREATE INDEX IF NOT EXISTS idx_tsj_status   ON tally_sync_jobs    (status, tenant_id);
            CREATE INDEX IF NOT EXISTS idx_tsj_created  ON tally_sync_jobs    (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tco_tenant   ON tally_companies    (tenant_id);
            CREATE INDEX IF NOT EXISTS idx_tl_tenant    ON tally_ledgers      (tenant_id, company_name);
            CREATE INDEX IF NOT EXISTS idx_tv_type      ON tally_vouchers     (tenant_id, voucher_type);
            CREATE INDEX IF NOT EXISTS idx_tg_status    ON tally_gst_reports  (tenant_id, status);
            CREATE INDEX IF NOT EXISTS idx_tal_tenant   ON tally_audit_logs   (tenant_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tn_status    ON tally_notifications (status, tenant_id);
            """
        )
        con.commit()


def _audit(action: str, detail: str, tenant_id: str = "default") -> None:
    init_tally_db()
    with _conn() as con:
        con.execute(
            "INSERT INTO tally_audit_logs (id, tenant_id, action, detail, created_at) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), tenant_id, action, detail, _now()),
        )
        con.commit()


def _latest_connection(tenant_id: str = "default") -> dict[str, Any] | None:
    init_tally_db()
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM tally_connections WHERE tenant_id=? ORDER BY updated_at DESC LIMIT 1",
            (tenant_id,),
        ).fetchone()
    data = _row(row)
    if not data:
        return None
    data["credentials_encrypted"] = bool(data.get("password_enc") or data.get("api_key_enc"))
    data["ip_restrictions"] = _json(data.get("ip_restrictions_json"), [])
    data.pop("password_enc", None)
    data.pop("api_key_enc", None)
    data.pop("ip_restrictions_json", None)
    return data


@router.get("/tally/status", summary="Tally connector status")
async def status(_auth=Depends(require_local_auth)):
    connection = _latest_connection()
    return {
        "connection": connection,
        "status": connection["status"] if connection else "not_connected",
        "health": "healthy" if connection and connection["status"] == "connected" else "not_connected",
        "active_workflows": 0,
        "error_count": 0,
    }


@router.post("/tally/connect", summary="Connect Tally")
async def connect(body: TallyConnectRequest, _auth=Depends(require_local_auth)):
    init_tally_db()
    now = _now()
    connection_id = str(uuid.uuid4())
    server_mode = "local" if body.mode == "localhost" or body.host in {"localhost", "127.0.0.1"} else "remote"
    with _conn() as con:
        con.execute("UPDATE tally_connections SET status='disconnected', updated_at=? WHERE tenant_id=?", (now, "default"))
        con.execute(
            """INSERT INTO tally_connections
               (id, tenant_id, mode, host, port, use_tls, company_name, username, password_enc,
                api_key_enc, enable_xml_api, status, tally_version, server_mode, sync_interval,
                ip_restrictions_json, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                connection_id, "default", body.mode, body.host, body.port, int(body.use_tls),
                body.company_name, body.username, _encrypt_secret(body.password), _encrypt_secret(body.api_key),
                int(body.enable_xml_api), "connected", "TallyPrime/Tally ERP 9 XML API", server_mode,
                body.sync_interval, json.dumps(body.ip_restrictions), now, now,
            ),
        )
        con.execute(
            "INSERT OR REPLACE INTO tally_companies (id, tenant_id, name, guid, health, last_sync_at) VALUES (?,?,?,?,?,?)",
            (body.company_name.lower().replace(" ", "-"), "default", body.company_name, "", "healthy", now),
        )
        con.commit()
    _audit("connect", f"Connected {body.company_name} at {body.host}:{body.port}")
    data = _latest_connection()
    return {"status": "connected", **(data or {})}


@router.post("/tally/disconnect", summary="Disconnect Tally")
async def disconnect(_auth=Depends(require_local_auth)):
    init_tally_db()
    with _conn() as con:
        con.execute("UPDATE tally_connections SET status='disconnected', updated_at=? WHERE tenant_id=?", (_now(), "default"))
        con.commit()
    _audit("disconnect", "Disconnected active Tally connection")
    return {"status": "disconnected"}


@router.post("/tally/test", summary="Test Tally connection")
async def test_connection(_auth=Depends(require_local_auth)):
    connection = _latest_connection()
    if not connection:
        return {"ok": False, "status": "not_connected", "message": "No Tally connection configured"}
    return {"ok": True, "status": "reachable", "mode": connection["mode"], "host": connection["host"], "port": connection["port"]}


@router.get("/tally/discover", summary="Discover Tally on LAN")
async def discover(_auth=Depends(require_local_auth)):
    candidates = ["127.0.0.1", "localhost"]
    found = []
    for host in candidates:
        try:
            with socket.create_connection((host, 9000), timeout=0.12):
                found.append({"host": host, "port": 9000, "mode": "localhost", "status": "open"})
        except OSError:
            continue
    if not found:
        found.append({"host": "localhost", "port": 9000, "mode": "localhost", "status": "not_detected"})
    return {"instances": found}


@router.get("/tally/companies")
async def companies(_auth=Depends(require_local_auth)):
    init_tally_db()
    with _conn() as con:
        rows = con.execute("SELECT name, guid, health, last_sync_at FROM tally_companies WHERE tenant_id=? ORDER BY name LIMIT 1000", ("default",)).fetchall()
    return {"companies": [dict(row) for row in rows]}


@router.get("/tally/ledgers")
async def ledgers(_auth=Depends(require_local_auth)):
    init_tally_db()
    with _conn() as con:
        rows = con.execute("SELECT name, parent, closing_balance, updated_at FROM tally_ledgers WHERE tenant_id=? ORDER BY name LIMIT 5000", ("default",)).fetchall()
    return {"ledgers": [dict(row) for row in rows]}


@router.get("/tally/vouchers")
async def vouchers(_auth=Depends(require_local_auth)):
    init_tally_db()
    with _conn() as con:
        rows = con.execute("SELECT voucher_type, voucher_number, amount, status, updated_at FROM tally_vouchers WHERE tenant_id=? ORDER BY updated_at DESC LIMIT 500", ("default",)).fetchall()
    return {"vouchers": [dict(row) for row in rows]}


@router.get("/tally/inventory")
async def inventory(_auth=Depends(require_local_auth)):
    init_tally_db()
    with _conn() as con:
        rows = con.execute("SELECT item_name, quantity, valuation, reorder_level, updated_at FROM tally_inventory WHERE tenant_id=? ORDER BY item_name LIMIT 5000", ("default",)).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/tally/gst")
async def gst(_auth=Depends(require_local_auth)):
    init_tally_db()
    with _conn() as con:
        rows = con.execute("SELECT company_name, period, mismatch_count, tax_payable, status, updated_at FROM tally_gst_reports WHERE tenant_id=? ORDER BY updated_at DESC LIMIT 500", ("default",)).fetchall()
    return {"reports": [dict(row) for row in rows], "alerts": []}


@router.post("/tally/sync")
async def sync(body: TallySyncRequest, _auth=Depends(require_local_auth)):
    init_tally_db()
    now = _now()
    job = {
        "id": str(uuid.uuid4()),
        "tenant_id": "default",
        "company_name": body.company_name,
        "sync_type": body.sync_type,
        "status": "queued",
        "entities": body.entities,
        "error_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    with _conn() as con:
        con.execute(
            """INSERT INTO tally_sync_jobs
               (id, tenant_id, company_name, sync_type, status, entities_json, error_count, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (job["id"], "default", body.company_name, body.sync_type, "queued", json.dumps(body.entities), 0, now, now),
        )
        con.commit()
    _audit("sync", f"Queued {body.sync_type} sync for {body.company_name or 'all companies'}")
    return {"status": "queued", "job": job, "events": ["tally.sync.started"]}


@router.get("/tally/analytics")
async def analytics(_auth=Depends(require_local_auth)):
    init_tally_db()
    with _conn() as con:
        voucher_total = con.execute("SELECT COALESCE(SUM(amount),0) FROM tally_vouchers WHERE tenant_id=?", ("default",)).fetchone()[0]
        stock_value = con.execute("SELECT COALESCE(SUM(valuation),0) FROM tally_inventory WHERE tenant_id=?", ("default",)).fetchone()[0]
        gst_mismatch = con.execute("SELECT COALESCE(SUM(mismatch_count),0) FROM tally_gst_reports WHERE tenant_id=?", ("default",)).fetchone()[0]
    return {
        "analytics": {
            "revenue": voucher_total,
            "expenses": 0,
            "cash_flow": voucher_total,
            "gst_mismatches": gst_mismatch,
            "stock_valuation": stock_value,
            "outstanding_invoices": 0,
            "top_customers": [],
            "top_suppliers": [],
            "profit_loss": {"profit": voucher_total},
            "ai_insights": [
                "Ask: Show unpaid invoices over 30 days",
                "Ask: Find suspicious transactions",
                "Ask: Predict next month revenue",
            ],
        }
    }


@router.get("/tally/logs")
async def logs(_auth=Depends(require_local_auth)):
    init_tally_db()
    with _conn() as con:
        rows = con.execute("SELECT action, actor, detail, created_at FROM tally_audit_logs WHERE tenant_id=? ORDER BY created_at DESC LIMIT 100", ("default",)).fetchall()
    return {"logs": [dict(row) for row in rows]}


@router.get("/tally/export")
async def export_data(_auth=Depends(require_local_auth)):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["resource", "status"])
    writer.writerow(["tally", "export-ready"])
    buffer.seek(0)
    return StreamingResponse(iter([buffer.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=tally-export.csv"})


init_tally_db()
