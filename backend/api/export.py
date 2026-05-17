"""Export and import API for AI Email Organizer."""

import csv
import io
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from backend import config
from backend.auth.local_auth import require_local_auth
from backend.db.database import Database

router = APIRouter()
db = Database(config.DB_PATH)
_log = logging.getLogger(__name__)

_AUTH = [Depends(require_local_auth)]

# ---------------------------------------------------------------------------
# Export endpoints
# ---------------------------------------------------------------------------

@router.get("/export/emails/csv", dependencies=_AUTH)
async def export_emails_csv(
    category: Optional[str] = None,
    limit: int = Query(1000, ge=1, le=10000),
):
    query = "SELECT * FROM emails "
    params: list = []
    if category:
        query += "WHERE category = ? "
        params.append(category)
    query += "ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    emails = db.fetch_all(query, tuple(params))
    output = io.StringIO()
    if emails:
        writer = csv.DictWriter(output, fieldnames=emails[0].keys())
        writer.writeheader()
        for email in emails:
            writer.writerow({k: str(v) for k, v in email.items()})
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=emails_{datetime.now().strftime('%Y%m%d')}.csv"},
    )


@router.get("/export/emails/json", dependencies=_AUTH)
async def export_emails_json(
    category: Optional[str] = None,
    limit: int = Query(1000, ge=1, le=10000),
):
    query = "SELECT * FROM emails "
    params: list = []
    if category:
        query += "WHERE category = ? "
        params.append(category)
    query += "ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    emails = db.fetch_all(query, tuple(params))
    return {"exported_at": datetime.now().isoformat(), "count": len(emails), "emails": emails}


@router.get("/export/rules/json", dependencies=_AUTH)
async def export_rules_json(user_id: int = 1):
    rules = db.get_rules_by_user(user_id)
    return {"exported_at": datetime.now().isoformat(), "count": len(rules), "rules": rules}


@router.get("/export/feedback/json", dependencies=_AUTH)
async def export_feedback_json(limit: int = Query(1000, ge=1, le=10000)):
    feedback = db.fetch_all(
        "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    return {"exported_at": datetime.now().isoformat(), "count": len(feedback), "feedback": feedback}


@router.get("/export/all", dependencies=_AUTH)
async def export_all():
    emails = db.fetch_all("SELECT * FROM emails ORDER BY created_at DESC LIMIT 1000")
    rules = db.get_rules_by_user(1)
    feedback = db.fetch_all("SELECT * FROM feedback ORDER BY created_at DESC LIMIT 500")
    categories = db.get_all_categories()
    return {
        "exported_at": datetime.now().isoformat(),
        "version": "9.7.0",
        "data": {
            "emails": {"count": len(emails), "items": emails},
            "rules": {"count": len(rules), "items": rules},
            "feedback": {"count": len(feedback), "items": feedback},
            "categories": {"count": len(categories), "items": categories},
        },
    }


# ---------------------------------------------------------------------------
# Import endpoints
# ---------------------------------------------------------------------------

@router.post("/import/emails/json", dependencies=_AUTH)
async def import_emails_json(data: dict):
    emails = data.get("emails", [])
    imported = skipped_no_account = failures = 0
    for index, email_data in enumerate(emails):
        sender_email = email_data.get("sender_email", "") or ""
        try:
            account = db.get_account_by_email(sender_email)
            if not account:
                skipped_no_account += 1
                _log.debug("import emails: skipped row %s (no account for sender_email=%s)", index, sender_email[:120] or "(empty)")
                continue
            db.add_email(
                account_id=account["id"],
                message_id=email_data.get("message_id", ""),
                subject=email_data.get("subject", ""),
                sender=email_data.get("sender", ""),
                sender_email=sender_email,
                body_text=email_data.get("body_text", ""),
                category=email_data.get("category"),
                confidence=email_data.get("confidence", 0.5),
                priority=email_data.get("priority", "Medium"),
            )
            imported += 1
        except Exception as exc:
            failures += 1
            _log.warning("import emails: failed row %s message_id=%s: %s", index, str(email_data.get("message_id", ""))[:80], exc)
    return {"status": "success", "imported": imported, "total": len(emails), "skipped_no_account": skipped_no_account, "failures": failures}


@router.post("/import/rules/json", dependencies=_AUTH)
async def import_rules_json(data: dict, user_id: int = 1):
    rules = data.get("rules", [])
    imported = failures = 0
    for index, rule in enumerate(rules):
        try:
            db.add_rule(
                user_id=user_id,
                name=rule.get("name", "Imported Rule"),
                condition=rule.get("condition", "{}"),
                action=rule.get("action", "{}"),
            )
            imported += 1
        except Exception as exc:
            failures += 1
            _log.warning("import rules: failed row %s name=%s: %s", index, str(rule.get("name", ""))[:80], exc)
    return {"status": "success", "imported": imported, "total": len(rules), "failures": failures}


@router.post("/import/all", dependencies=_AUTH)
async def import_all(data: dict):
    imported = {"emails": 0, "rules": 0, "feedback": 0}
    skipped_no_account = email_failures = rule_failures = 0
    if "data" in data:
        data = data["data"]
    if "emails" in data:
        for index, email_data in enumerate(data["emails"].get("items", [])):
            sender_email = email_data.get("sender_email", "") or ""
            try:
                account = db.get_account_by_email(sender_email)
                if not account:
                    skipped_no_account += 1
                    _log.debug("import/all emails: skipped %s no account (%s)", index, sender_email[:120] or "(empty)")
                    continue
                db.add_email(
                    account_id=account["id"],
                    message_id=email_data.get("message_id", ""),
                    subject=email_data.get("subject", ""),
                    sender=email_data.get("sender", ""),
                    sender_email=sender_email,
                    body_text=email_data.get("body_text", ""),
                    category=email_data.get("category"),
                    confidence=email_data.get("confidence", 0.5),
                    priority=email_data.get("priority", "Medium"),
                )
                imported["emails"] += 1
            except Exception as exc:
                email_failures += 1
                _log.warning("import/all emails: failed %s message_id=%s: %s", index, str(email_data.get("message_id", ""))[:80], exc)
    if "rules" in data:
        for index, rule in enumerate(data["rules"].get("items", [])):
            try:
                db.add_rule(user_id=1, name=rule.get("name", "Imported"), condition=rule.get("condition", "{}"), action=rule.get("action", "{}"))
                imported["rules"] += 1
            except Exception as exc:
                rule_failures += 1
                _log.warning("import/all rules: failed %s name=%s: %s", index, str(rule.get("name", ""))[:80], exc)
    return {"status": "success", "imported": imported, "skipped_no_account": skipped_no_account, "email_import_failures": email_failures, "rule_import_failures": rule_failures}


# ---------------------------------------------------------------------------
# Destructive operations — require auth + explicit confirmation header
# ---------------------------------------------------------------------------

def _require_confirmation(x_confirm_delete: Optional[str] = Header(None, alias="X-Confirm-Delete")) -> None:
    if (x_confirm_delete or "").lower() != "yes":
        raise HTTPException(
            status_code=428,
            detail="Destructive operation requires X-Confirm-Delete: yes header",
        )


@router.delete("/data/emails", dependencies=_AUTH)
async def clear_emails(confirmed: None = Depends(_require_confirmation)):
    snapshot = {"reason": "manual_clear", "at": datetime.now().isoformat()}
    db.execute(
        "UPDATE emails SET delete_state = 'deleted', deleted_at = ?, restore_snapshot = ? "
        "WHERE COALESCE(delete_state, 'active') != 'deleted'",
        (snapshot["at"], json.dumps(snapshot, sort_keys=True)),
    )
    return {"status": "soft_deleted", "message": "Emails moved to restore center. Use POST /emails/restore to recover."}


@router.delete("/data/feedback", dependencies=_AUTH)
async def clear_feedback(confirmed: None = Depends(_require_confirmation)):
    db.execute("DELETE FROM feedback")
    return {"status": "success", "message": "All feedback deleted"}


@router.delete("/data/rules", dependencies=_AUTH)
async def clear_rules(user_id: int = 1, confirmed: None = Depends(_require_confirmation)):
    db.execute("DELETE FROM rules WHERE user_id = ?", (user_id,))
    return {"status": "success", "message": "All rules deleted"}
