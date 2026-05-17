"""
Threat Intelligence & Scam Panel API
======================================
All endpoints consumed by /security (scam-panel.html).

Actual emails table columns (verified against live DB):
  id, account_id, message_id, subject, sender (display name),
  sender_email (full address), body_text, body_html, category,
  confidence, priority, is_read, is_processed, processed_at,
  created_at, metadata (JSON blob), folder, labels, ...

classification_overrides columns:
  id, user_id, sender_email, sender_domain, category,
  source_email_id, created_at, updated_at
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, Generator, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Body
from pydantic import BaseModel, Field

from backend import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/threat", tags=["threat-intelligence"])


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db_now() -> str:
    """Timestamp for DB insertion — space-separated for SQLite compatibility."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _api_now() -> str:
    """ISO timestamp for API JSON responses."""
    return datetime.utcnow().isoformat() + "Z"


def _raw_conn():
    """Open a fresh direct sqlite3 connection using the runtime DB path."""
    import sqlite3 as _sq3
    c = _sq3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    c.row_factory = _sq3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


@contextmanager
def _conn() -> Generator:
    """Context manager that opens a sqlite3 connection and ensures it is closed."""
    conn = _raw_conn()
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _ensure_threat_tables() -> None:
    """Create threat tables if they do not exist. Safe to call multiple times."""
    import sqlite3 as _sq3
    conn = _sq3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS threat_blacklist (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type  TEXT NOT NULL CHECK(entry_type IN ('sender','domain')),
                value       TEXT NOT NULL COLLATE NOCASE,
                reason      TEXT,
                threat_type TEXT,
                score       INTEGER DEFAULT 0,
                auto_block  INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS threat_whitelist (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type  TEXT NOT NULL CHECK(entry_type IN ('sender','domain')),
                value       TEXT NOT NULL COLLATE NOCASE,
                reason      TEXT,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS threat_audit_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                action       TEXT NOT NULL,
                target_type  TEXT,
                target_value TEXT,
                detail       TEXT,
                performed_by TEXT DEFAULT 'system',
                created_at   TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS threat_lookalike_alerts (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                detected_domain     TEXT NOT NULL,
                impersonated_brand  TEXT,
                impersonated_domain TEXT,
                threat_type         TEXT,
                confidence_score    INTEGER DEFAULT 0,
                reasons             TEXT,
                sender_email        TEXT,
                email_subject       TEXT,
                status              TEXT DEFAULT 'active'
                                    CHECK(status IN ('active','dismissed','confirmed')),
                created_at          TEXT NOT NULL
            );
        """)
        conn.commit()
    finally:
        conn.close()


def _log_audit_direct(action: str, target_type: str,
                      target_value: str, detail: str = "",
                      performed_by: str = "user") -> None:
    import sqlite3 as _sq3
    try:
        conn = _sq3.connect(config.DB_PATH, timeout=10, check_same_thread=False)
        try:
            conn.execute(
                "INSERT INTO threat_audit_log "
                "(action, target_type, target_value, detail, performed_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (action, target_type, target_value, detail, performed_by, _db_now()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Audit log write failed: %s", exc)


def _parse_scam_reasons(metadata_json: Optional[str]) -> List[str]:
    """Extract scam_reasons list from the email metadata JSON blob."""
    if not metadata_json:
        return []
    try:
        meta = json.loads(metadata_json)
        reasons = meta.get("scam_reasons") or meta.get("reasons") or []
        return reasons if isinstance(reasons, list) else []
    except Exception:
        return []


def _set_classification_override(conn, sender_email: str, domain: str, category: str) -> None:
    """Insert/update classification_overrides — UNIQUE(user_id, sender_email)."""
    try:
        now = _db_now()
        conn.execute(
            """INSERT INTO classification_overrides
               (user_id, sender_email, sender_domain, category, created_at, updated_at)
               VALUES (0, ?, ?, ?, ?, ?)
               ON CONFLICT(user_id, sender_email) DO UPDATE SET
                 category=excluded.category,
                 updated_at=excluded.updated_at""",
            (sender_email.lower().strip(), domain.lower().strip(), category, now, now),
        )
        conn.commit()
    except Exception as exc:
        logger.debug("classification_overrides upsert skipped: %s", exc)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class BlacklistEntry(BaseModel):
    entry_type: str = Field(..., pattern="^(sender|domain)$")
    value: str
    reason: Optional[str] = None
    threat_type: Optional[str] = None
    score: int = 0
    auto_block: bool = False


class WhitelistEntry(BaseModel):
    entry_type: str = Field(..., pattern="^(sender|domain)$")
    value: str
    reason: Optional[str] = None


class DomainBulkRequest(BaseModel):
    domains: List[str] = Field(..., max_length=100)


class ConfirmScamRequest(BaseModel):
    block_sender: bool = True


class LookalikRecordRequest(BaseModel):
    detected_domain: Optional[str] = None
    suspicious_domain: Optional[str] = None   # alias accepted for backwards compat
    impersonated_brand: Optional[str] = None
    target_brand: Optional[str] = None          # alias
    impersonated_domain: Optional[str] = None
    legitimate_domain: Optional[str] = None     # alias
    threat_type: Optional[str] = None
    attack_type: Optional[str] = None           # alias
    confidence_score: int = 0
    reasons: List[str] = Field(default_factory=list)
    sender_email: Optional[str] = None
    email_subject: Optional[str] = None


# ---------------------------------------------------------------------------
# Domain analysis
# ---------------------------------------------------------------------------

@router.get("/domain/{domain:path}")
async def analyse_domain(domain: str) -> Dict:
    domain = domain.strip().lower().lstrip("@")
    if not domain or "." not in domain:
        raise HTTPException(400, "Invalid domain")
    try:
        from backend.ai.domain_intelligence import get_engine
        result = get_engine().get_threat_summary(domain)
        return {"ok": True, "result": result}
    except Exception as exc:
        logger.error("Domain analysis error: %s", exc)
        raise HTTPException(500, "Domain analysis failed")


@router.post("/domain/bulk")
async def analyse_domains_bulk(body: DomainBulkRequest) -> Dict:
    try:
        from backend.ai.domain_intelligence import get_engine
        engine = get_engine()
        results = {d: engine.get_threat_summary(d) for d in body.domains if d}
        return {"ok": True, "results": results, "count": len(results)}
    except Exception as exc:
        logger.error("Bulk domain analysis error: %s", exc)
        raise HTTPException(500, "Bulk analysis failed")


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

@router.get("/stats")
async def get_threat_stats() -> Dict:
    with _conn() as conn:
        try:
            total_emails   = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
            scam_count     = conn.execute("SELECT COUNT(*) FROM emails WHERE category='Scam'").fetchone()[0]
            pending_count  = conn.execute("SELECT COUNT(*) FROM emails WHERE category='Pending Review'").fetchone()[0]

            bl_count         = conn.execute("SELECT COUNT(*) FROM threat_blacklist").fetchone()[0]
            wl_count         = conn.execute("SELECT COUNT(*) FROM threat_whitelist").fetchone()[0]
            lookalike_active = conn.execute("SELECT COUNT(*) FROM threat_lookalike_alerts WHERE status='active'").fetchone()[0]
            lookalike_total  = conn.execute("SELECT COUNT(*) FROM threat_lookalike_alerts").fetchone()[0]

            rows = conn.execute(
                "SELECT threat_type, COUNT(*) c FROM threat_lookalike_alerts "
                "GROUP BY threat_type ORDER BY c DESC"
            ).fetchall()
            threat_breakdown = {r[0]: r[1] for r in rows if r[0]}

            rows = conn.execute(
                "SELECT impersonated_brand, COUNT(*) c FROM threat_lookalike_alerts "
                "WHERE impersonated_brand IS NOT NULL "
                "GROUP BY impersonated_brand ORDER BY c DESC LIMIT 10"
            ).fetchall()
            top_brands = [{"brand": r[0], "count": r[1]} for r in rows]

            since7 = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            recent_actions = conn.execute(
                "SELECT COUNT(*) FROM threat_audit_log WHERE created_at > ?", (since7,)
            ).fetchone()[0]

            cat_rows = conn.execute(
                "SELECT category, COUNT(*) c FROM emails GROUP BY category ORDER BY c DESC"
            ).fetchall()
            category_dist = [{"category": r[0] or "Unknown", "count": r[1]} for r in cat_rows]

            return {
                "ok": True,
                "stats": {
                    "total_emails":            total_emails,
                    "scam_blocked":            scam_count,
                    "pending_review":          pending_count,
                    "blacklisted_entries":     bl_count,
                    "trusted_entries":         wl_count,
                    "lookalike_alerts_active": lookalike_active,
                    "lookalike_alerts_total":  lookalike_total,
                    "threat_type_breakdown":   threat_breakdown,
                    "top_impersonated_brands": top_brands,
                    "recent_actions_7d":       recent_actions,
                    "category_distribution":   category_dist,
                    "generated_at":            _api_now(),
                },
            }
        except Exception as exc:
            logger.error("Threat stats error: %s", exc)
            raise HTTPException(500, f"Stats generation failed: {exc}")


# ---------------------------------------------------------------------------
# Threat feed
# ---------------------------------------------------------------------------

@router.get("/feed")
async def get_threat_feed(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
) -> Dict:
    with _conn() as conn:
        try:
            where_parts = ["1=1"]
            params: List[Any] = []
            if status:
                where_parts.append("status=?")
                params.append(status)
            if search:
                s = f"%{search}%"
                where_parts.append(
                    "(detected_domain LIKE ? OR impersonated_brand LIKE ? OR sender_email LIKE ?)"
                )
                params += [s, s, s]
            where = "WHERE " + " AND ".join(where_parts)

            rows = conn.execute(
                f"SELECT id, detected_domain, impersonated_brand, impersonated_domain, "  # nosec B608
                f"threat_type, confidence_score, reasons, sender_email, email_subject, "
                f"status, created_at FROM threat_lookalike_alerts {where} "
                f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

            feed = [{
                "id": r[0], "detected_domain": r[1], "impersonated_brand": r[2],
                "impersonated_domain": r[3], "threat_type": r[4],
                "confidence_score": r[5],
                "reasons": json.loads(r[6]) if r[6] else [],
                "sender_email": r[7], "email_subject": r[8],
                "status": r[9], "created_at": r[10],
            } for r in rows]

            total = conn.execute(
                "SELECT COUNT(*) FROM threat_lookalike_alerts"
            ).fetchone()[0]
            return {"ok": True, "feed": feed, "total": total, "limit": limit, "offset": offset}
        except Exception as exc:
            logger.error("Threat feed error: %s", exc)
            raise HTTPException(500, f"Feed retrieval failed: {exc}")


# ---------------------------------------------------------------------------
# Blacklist
# ---------------------------------------------------------------------------

@router.get("/blacklist")
async def list_blacklist(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    entry_type: Optional[str] = Query(None),
) -> Dict:
    with _conn() as conn:
        where_parts = ["1=1"]
        params: List[Any] = []
        if entry_type:
            where_parts.append("entry_type=?")
            params.append(entry_type)
        where = "WHERE " + " AND ".join(where_parts)

        rows = conn.execute(
            f"SELECT id, entry_type, value, reason, threat_type, score, auto_block, "  # nosec B608
            f"created_at, updated_at FROM threat_blacklist {where} "
            f"ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        items = [{
            "id": r[0], "entry_type": r[1], "value": r[2], "reason": r[3],
            "threat_type": r[4], "score": r[5], "auto_block": bool(r[6]),
            "created_at": r[7], "updated_at": r[8],
        } for r in rows]

        total = conn.execute("SELECT COUNT(*) FROM threat_blacklist").fetchone()[0]
        return {"ok": True, "items": items, "total": total}


@router.post("/blacklist")
async def add_to_blacklist(entry: BlacklistEntry) -> Dict:
    now = _db_now()
    value = entry.value.lower().strip()
    with _conn() as conn:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO threat_blacklist "
                "(entry_type, value, reason, threat_type, score, auto_block, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.entry_type, value, entry.reason,
                 entry.threat_type, entry.score, int(entry.auto_block), now, now),
            )
            conn.commit()

            domain = value.split("@")[-1] if "@" in value else value
            _set_classification_override(conn, value, domain, "Scam")

            _log_audit_direct("blacklist_add", entry.entry_type, value, entry.reason or "")
            return {"ok": True, "message": f"{value} added to blacklist"}
        except Exception as exc:
            logger.error("Blacklist add error: %s", exc)
            raise HTTPException(500, str(exc))


@router.delete("/blacklist/{entry_id}")
async def remove_from_blacklist(entry_id: int) -> Dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT value, entry_type FROM threat_blacklist WHERE id=?", (entry_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Blacklist entry not found")
        conn.execute("DELETE FROM threat_blacklist WHERE id=?", (entry_id,))
        conn.commit()
    _log_audit_direct("blacklist_remove", row[1], row[0])
    return {"ok": True, "message": f"{row[0]} removed from blacklist"}


# ---------------------------------------------------------------------------
# Whitelist
# ---------------------------------------------------------------------------

@router.get("/whitelist")
async def list_whitelist(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Dict:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, entry_type, value, reason, created_at, updated_at "
            "FROM threat_whitelist ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        items = [{
            "id": r[0], "entry_type": r[1], "value": r[2],
            "reason": r[3], "created_at": r[4], "updated_at": r[5],
        } for r in rows]
        total = conn.execute("SELECT COUNT(*) FROM threat_whitelist").fetchone()[0]
        return {"ok": True, "items": items, "total": total}


@router.post("/whitelist")
async def add_to_whitelist(entry: WhitelistEntry) -> Dict:
    now = _db_now()
    value = entry.value.lower().strip()
    with _conn() as conn:
        try:
            conn.execute(
                "INSERT OR REPLACE INTO threat_whitelist "
                "(entry_type, value, reason, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (entry.entry_type, value, entry.reason, now, now),
            )
            conn.commit()

            if entry.entry_type == "domain":
                try:
                    from backend.ai.domain_intelligence import get_engine
                    get_engine().add_trusted_domain(value)
                except Exception:
                    pass

            domain = value.split("@")[-1] if "@" in value else value
            _set_classification_override(conn, value, domain, "Normal")

            _log_audit_direct("whitelist_add", entry.entry_type, value, entry.reason or "")
            return {"ok": True, "message": f"{value} added to trusted list"}
        except Exception as exc:
            logger.error("Whitelist add error: %s", exc)
            raise HTTPException(500, str(exc))


@router.delete("/whitelist/{entry_id}")
async def remove_from_whitelist(entry_id: int) -> Dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT value, entry_type FROM threat_whitelist WHERE id=?", (entry_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Whitelist entry not found")
        conn.execute("DELETE FROM threat_whitelist WHERE id=?", (entry_id,))
        conn.commit()
    _log_audit_direct("whitelist_remove", row[1], row[0])
    return {"ok": True, "message": f"{row[0]} removed from trusted list"}


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@router.get("/audit")
async def get_audit_log(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
) -> Dict:
    with _conn() as conn:
        where_parts = ["1=1"]
        params: List[Any] = []
        if action:
            where_parts.append("action=?")
            params.append(action)
        if since:
            where_parts.append("created_at >= ?")
            params.append(since)
        where = "WHERE " + " AND ".join(where_parts)

        rows = conn.execute(
            f"SELECT id, action, target_type, target_value, detail, performed_by, created_at "  # nosec B608
            f"FROM threat_audit_log {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        items = [{
            "id": r[0], "action": r[1], "target_type": r[2], "target_value": r[3],
            "detail": r[4], "performed_by": r[5], "created_at": r[6],
        } for r in rows]
        total = conn.execute("SELECT COUNT(*) FROM threat_audit_log").fetchone()[0]
        return {"ok": True, "items": items, "total": total}


# ---------------------------------------------------------------------------
# Scam email management
# ---------------------------------------------------------------------------

@router.get("/emails/scam")
async def get_scam_emails(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    category: str = Query("Scam"),
) -> Dict:
    with _conn() as conn:
        try:
            rows = conn.execute(
                "SELECT id, subject, sender, sender_email, category, confidence, "
                "metadata, created_at, account_id "
                "FROM emails WHERE category=? "
                "ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (category, limit, offset),
            ).fetchall()

            items = [{
                "id": r[0],
                "subject":      r[1] or "(no subject)",
                "sender":       r[2] or "",
                "sender_email": r[3] or "",
                "category":     r[4] or "",
                "confidence":   r[5] or 0.0,
                "scam_reasons": _parse_scam_reasons(r[6]),
                "date":         r[7] or "",
                "account_id":   r[8],
            } for r in rows]

            total = conn.execute(
                "SELECT COUNT(*) FROM emails WHERE category=?", (category,)
            ).fetchone()[0]

            return {"ok": True, "emails": items, "total": total}
        except Exception as exc:
            logger.error("Scam email list error: %s", exc)
            raise HTTPException(500, f"Failed to retrieve emails: {exc}")


@router.get("/emails/all")
async def get_all_emails(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
) -> Dict:
    with _conn() as conn:
        try:
            where_parts = ["1=1"]
            params: List[Any] = []
            if search:
                where_parts.append("(subject LIKE ? OR sender_email LIKE ? OR sender LIKE ?)")
                s = f"%{search}%"
                params += [s, s, s]
            where = "WHERE " + " AND ".join(where_parts)

            rows = conn.execute(
                f"SELECT id, subject, sender, sender_email, category, confidence, "  # nosec B608
                f"metadata, created_at, account_id "
                f"FROM emails {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()

            items = [{
                "id": r[0],
                "subject":      r[1] or "(no subject)",
                "sender":       r[2] or "",
                "sender_email": r[3] or "",
                "category":     r[4] or "Unknown",
                "confidence":   r[5] or 0.0,
                "scam_reasons": _parse_scam_reasons(r[6]),
                "date":         r[7] or "",
                "account_id":   r[8],
            } for r in rows]

            total = conn.execute(
                f"SELECT COUNT(*) FROM emails {where}", params  # nosec B608
            ).fetchone()[0]

            return {"ok": True, "emails": items, "total": total}
        except Exception as exc:
            logger.error("All emails error: %s", exc)
            raise HTTPException(500, f"Failed to retrieve emails: {exc}")


def _find_email_row(conn, email_id: str):
    """Look up an email by integer id OR by message_id (Gmail/Outlook row ID)."""
    row = conn.execute(
        "SELECT id, sender_email, category FROM emails WHERE id=?", (email_id,)
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT id, sender_email, category FROM emails WHERE message_id=?", (email_id,)
        ).fetchone()
    return row


def _apply_category_update(conn, db_id: int, category: str) -> None:
    """Apply a full category update matching what the dashboard does."""
    now = _db_now()
    if category == "Scam":
        folder, priority = "Scam", "Critical"
    elif category == "Normal":
        folder, priority = "INBOX", "Medium"
    else:
        folder, priority = "INBOX", "Medium"
    conn.execute(
        "UPDATE emails SET category=?, confidence=1.0, priority=?, folder=?, "
        "is_processed=1, processed_at=? WHERE id=?",
        (category, priority, folder, now, db_id),
    )
    try:
        existing = conn.execute(
            "SELECT id FROM email_labels WHERE email_id=? AND label=?", (db_id, category)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO email_labels (email_id, label) VALUES (?, ?)", (db_id, category)
            )
    except Exception:
        pass
    conn.commit()


@router.post("/emails/{email_id}/restore")
async def restore_email(email_id: str) -> Dict:
    with _conn() as conn:
        try:
            row = _find_email_row(conn, email_id)
            if not row:
                raise HTTPException(404, "Email not found")

            db_id, sender_email, prev_category = row[0], row[1] or "", row[2]
            _apply_category_update(conn, db_id, "Normal")

            _log_audit_direct("email_restored", "email", str(db_id),
                              f"restored from {prev_category} → Normal, sender: {sender_email}")
            return {"ok": True, "message": "Email restored to Normal", "email_id": db_id}
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Restore error: %s", exc)
            raise HTTPException(500, str(exc))


@router.post("/emails/{email_id}/confirm")
async def confirm_scam(email_id: str, request: ConfirmScamRequest = Body(default=None)) -> Dict:
    """Confirm email as scam and optionally blacklist the sender."""
    block_sender = request.block_sender if request is not None else True
    with _conn() as conn:
        try:
            row = _find_email_row(conn, email_id)
            if not row:
                raise HTTPException(404, "Email not found")

            db_id, sender_email, prev_category = row[0], (row[1] or "").lower().strip(), row[2]
            _apply_category_update(conn, db_id, "Scam")

            _log_audit_direct("scam_confirmed", "email", str(db_id),
                              f"category changed to Scam, sender: {sender_email}")

            if block_sender and sender_email:
                now = _db_now()
                conn.execute(
                    "INSERT OR REPLACE INTO threat_blacklist "
                    "(entry_type, value, reason, threat_type, score, auto_block, created_at, updated_at) "
                    "VALUES ('sender', ?, 'user confirmed scam', 'user_confirmed', 100, 1, ?, ?)",
                    (sender_email, now, now),
                )
                conn.commit()
                domain = sender_email.split("@")[-1] if "@" in sender_email else sender_email
                _set_classification_override(conn, sender_email, domain, "Scam")
                _log_audit_direct("blacklist_add", "sender", sender_email,
                                  "auto-blacklisted after scam confirmation")

            return {"ok": True, "message": "Confirmed as scam", "email_id": db_id, "sender_blocked": block_sender}
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Confirm scam error: %s", exc)
            raise HTTPException(500, str(exc))


# ---------------------------------------------------------------------------
# Lookalike monitoring
# ---------------------------------------------------------------------------

@router.get("/lookalike/monitor")
async def get_lookalike_monitor(
    brand: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
) -> Dict:
    with _conn() as conn:
        where_parts = ["status='active'"]
        params: List[Any] = []
        if brand:
            where_parts.append("impersonated_brand=?")
            params.append(brand)
        where = "WHERE " + " AND ".join(where_parts)

        rows = conn.execute(
            f"SELECT id, detected_domain, impersonated_brand, impersonated_domain, "  # nosec B608
            f"threat_type, confidence_score, reasons, sender_email, email_subject, "
            f"status, created_at FROM threat_lookalike_alerts {where} "
            f"ORDER BY confidence_score DESC, created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()

        alerts = [{
            "id": r[0], "detected_domain": r[1], "impersonated_brand": r[2],
            "impersonated_domain": r[3], "threat_type": r[4],
            "confidence_score": r[5],
            "reasons": json.loads(r[6]) if r[6] else [],
            "sender_email": r[7], "email_subject": r[8],
            "status": r[9], "created_at": r[10],
        } for r in rows]

        brand_summary: Dict[str, Any] = {}
        for a in alerts:
            b = a["impersonated_brand"] or "unknown"
            if b not in brand_summary:
                brand_summary[b] = {"brand": b, "detections": 0, "max_score": 0}
            brand_summary[b]["detections"] += 1
            brand_summary[b]["max_score"] = max(brand_summary[b]["max_score"], a["confidence_score"])

        return {
            "ok": True,
            "alerts": alerts,
            "brand_summary": list(brand_summary.values()),
            "total": len(alerts),
        }


@router.post("/lookalike/record")
async def record_lookalike_alert(data: LookalikRecordRequest) -> Dict:
    """Record a new lookalike detection. Accepts both new and legacy field names."""
    # Resolve aliases — prefer explicit fields, fall back to aliases
    detected_domain     = data.detected_domain or data.suspicious_domain
    impersonated_brand  = data.impersonated_brand or data.target_brand
    impersonated_domain = data.impersonated_domain or data.legitimate_domain
    threat_type         = data.threat_type or data.attack_type

    if not detected_domain:
        raise HTTPException(400, "detected_domain (or suspicious_domain) is required")

    now = _db_now()
    with _conn() as conn:
        try:
            conn.execute(
                "INSERT INTO threat_lookalike_alerts "
                "(detected_domain, impersonated_brand, impersonated_domain, threat_type, "
                "confidence_score, reasons, sender_email, email_subject, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
                (
                    detected_domain, impersonated_brand, impersonated_domain, threat_type,
                    data.confidence_score,
                    json.dumps(data.reasons),
                    data.sender_email, data.email_subject, now,
                ),
            )
            conn.commit()
            return {"ok": True}
        except Exception as exc:
            logger.error("Record lookalike error: %s", exc)
            raise HTTPException(500, str(exc))


@router.post("/lookalike/{alert_id}/dismiss")
async def dismiss_lookalike(alert_id: int) -> Dict:
    with _conn() as conn:
        row = conn.execute(
            "SELECT id FROM threat_lookalike_alerts WHERE id=?", (alert_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Alert not found")
        conn.execute(
            "UPDATE threat_lookalike_alerts SET status='dismissed' WHERE id=?", (alert_id,)
        )
        conn.commit()
    _log_audit_direct("lookalike_dismissed", "alert", str(alert_id))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/analytics")
async def get_threat_analytics(days: int = Query(30, ge=1, le=365)) -> Dict:
    # Use space-separated format to match email created_at column format
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        try:
            scam_rows = conn.execute(
                "SELECT date(created_at) day, COUNT(*) c FROM emails "
                "WHERE category='Scam' AND created_at >= ? GROUP BY day ORDER BY day",
                (since,),
            ).fetchall()
            scam_trend = [{"date": r[0], "count": r[1]} for r in scam_rows]

            lookalike_rows = conn.execute(
                "SELECT date(created_at) day, COUNT(*) c FROM threat_lookalike_alerts "
                "WHERE created_at >= ? GROUP BY day ORDER BY day",
                (since,),
            ).fetchall()
            lookalike_trend = [{"date": r[0], "count": r[1]} for r in lookalike_rows]

            type_rows = conn.execute(
                "SELECT threat_type, COUNT(*) c FROM threat_lookalike_alerts "
                "WHERE created_at >= ? AND threat_type IS NOT NULL "
                "GROUP BY threat_type ORDER BY c DESC",
                (since,),
            ).fetchall()
            type_breakdown = [{"type": r[0], "count": r[1]} for r in type_rows]

            brand_rows = conn.execute(
                "SELECT impersonated_brand, COUNT(*) c FROM threat_lookalike_alerts "
                "WHERE created_at >= ? AND impersonated_brand IS NOT NULL "
                "GROUP BY impersonated_brand ORDER BY c DESC LIMIT 15",
                (since,),
            ).fetchall()
            brand_breakdown = [{"brand": r[0], "count": r[1]} for r in brand_rows]

            return {
                "ok": True, "period_days": days, "since": since,
                "scam_trend": scam_trend, "lookalike_trend": lookalike_trend,
                "threat_type_breakdown": type_breakdown,
                "top_attacked_brands": brand_breakdown,
            }
        except Exception as exc:
            logger.error("Analytics error: %s", exc)
            raise HTTPException(500, f"Analytics failed: {exc}")


# ---------------------------------------------------------------------------
# Live scan — run domain intelligence against ALL existing emails
# ---------------------------------------------------------------------------

def _run_scan_sync() -> Dict:
    """
    Synchronously scan every email in the DB through the domain intelligence
    engine. Uses sqlite3 directly to avoid the singleton thread-local issue.
    """
    import sqlite3 as _sqlite3
    from backend.ai.domain_intelligence import get_engine
    from backend.core.scam_filter import ScamFilter

    db_path = config.DB_PATH
    conn = _sqlite3.connect(db_path, timeout=30, check_same_thread=False)
    conn.row_factory = _sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    engine = get_engine()
    sf = ScamFilter()

    rows = conn.execute(
        "SELECT id, subject, sender, sender_email, category, confidence, metadata "
        "FROM emails ORDER BY id"
    ).fetchall()

    inserted_alerts = 0
    reclassified = 0
    now = _db_now()

    for row in rows:
        email_id, subject, sender_name, sender_email, category, confidence, metadata_raw = row
        sender_email = (sender_email or "").strip()
        subject = subject or ""

        if not sender_email or "@" not in sender_email:
            continue

        domain = sender_email.split("@")[-1]

        try:
            domain_result = engine.analyse(domain)
            if domain_result.is_lookalike:
                existing = conn.execute(
                    "SELECT id FROM threat_lookalike_alerts "
                    "WHERE detected_domain=? AND sender_email=?",
                    (domain, sender_email),
                ).fetchone()
                if not existing:
                    conn.execute(
                        "INSERT INTO threat_lookalike_alerts "
                        "(detected_domain, impersonated_brand, impersonated_domain, "
                        "threat_type, confidence_score, reasons, sender_email, "
                        "email_subject, status, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)",
                        (
                            domain,
                            domain_result.impersonated_brand,
                            domain_result.impersonated_domain,
                            domain_result.threat_type,
                            domain_result.confidence_score,
                            json.dumps(domain_result.reasons),
                            sender_email,
                            subject[:200],
                            now,
                        ),
                    )
                    inserted_alerts += 1
        except Exception as exc:
            logger.debug("Domain scan error for %s: %s", domain, exc)

        try:
            body = ""
            if metadata_raw:
                try:
                    meta = json.loads(metadata_raw)
                    body = meta.get("body_text", "") or meta.get("snippet", "") or ""
                except Exception:
                    pass

            scam_result = sf.classify(
                subject=subject,
                sender=sender_name or "",
                sender_email=sender_email,
                body=body,
            )
            if scam_result and scam_result["category"] in ("Scam", "Pending Review"):
                if category not in ("Scam", "Pending Review"):
                    conn.execute(
                        "UPDATE emails SET category=?, confidence=? WHERE id=?",
                        (scam_result["category"], scam_result["confidence"], email_id),
                    )
                    reclassified += 1

                    try:
                        meta = json.loads(metadata_raw or "{}")
                        meta["scam_reasons"] = scam_result.get("scam_reasons", [])
                        conn.execute(
                            "UPDATE emails SET metadata=? WHERE id=?",
                            (json.dumps(meta), email_id),
                        )
                    except Exception:
                        pass
        except Exception as exc:
            logger.debug("ScamFilter scan error for email %s: %s", email_id, exc)

    conn.commit()

    known_good = [
        ("no-reply@accounts.google.com", "google.com"),
        ("noreply@github.com", "github.com"),
        ("noreply@tradingview.com", "tradingview.com"),
        ("stitch-noreply@google.com", "google.com"),
        ("no-reply@youtube.com", "youtube.com"),
    ]
    for email_addr, domain_val in known_good:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO threat_whitelist "
                "(entry_type, value, reason, created_at, updated_at) "
                "VALUES ('sender', ?, 'auto-trusted: known provider', ?, ?)",
                (email_addr, now, now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO threat_whitelist "
                "(entry_type, value, reason, created_at, updated_at) "
                "VALUES ('domain', ?, 'auto-trusted: known provider', ?, ?)",
                (domain_val, now, now),
            )
        except Exception:
            pass
    conn.commit()

    total_scanned = len(rows)

    try:
        conn.execute(
            "INSERT INTO threat_audit_log "
            "(action, target_type, target_value, detail, performed_by, created_at) "
            "VALUES ('full_scan_complete', 'system', 'all_emails', ?, 'system', ?)",
            (f"scanned={total_scanned} alerts={inserted_alerts} reclassified={reclassified}", now),
        )
        conn.commit()
    except Exception:
        pass

    conn.close()

    return {
        "total_scanned": total_scanned,
        "lookalike_alerts_inserted": inserted_alerts,
        "emails_reclassified": reclassified,
    }


@router.post("/scan")
async def trigger_scan(background_tasks: BackgroundTasks) -> Dict:
    """
    Trigger a full domain-intelligence scan of all emails in the DB.
    Runs synchronously (small DB) and returns results immediately.
    """
    try:
        result = _run_scan_sync()
        return {"ok": True, "scan_result": result}
    except Exception as exc:
        logger.error("Scan error: %s", exc)
        raise HTTPException(500, f"Scan failed: {exc}")


# ---------------------------------------------------------------------------
# Ensure tables exist when module is loaded
# ---------------------------------------------------------------------------

try:
    _ensure_threat_tables()
except Exception as _e:
    logger.warning("Could not ensure threat tables on load: %s", _e)
