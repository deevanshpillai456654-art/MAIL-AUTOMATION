"""
Export and import API for AI Email Organizer
"""

import sys
from pathlib import Path

import json
import csv
import io
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import datetime

from backend.db.database import Database
from backend import config

router = APIRouter()
db = Database(config.DB_PATH)
_log = logging.getLogger(__name__)


@router.get("/export/emails/csv")
async def export_emails_csv(category: Optional[str] = None, limit: int = 1000):
    emails = db.fetch_all(
        f"SELECT * FROM emails {'WHERE category = ?' if category else ''} ORDER BY created_at DESC LIMIT ?",
        (category, limit) if category else (limit,)
    )

    output = io.StringIO()
    if emails:
        headers = emails[0].keys()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        for email in emails:
            writer.writerow({k: str(v) for k, v in email.items()})

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=emails_{datetime.now().strftime('%Y%m%d')}.csv"}
    )


@router.get("/export/emails/json")
async def export_emails_json(category: Optional[str] = None, limit: int = 1000):
    emails = db.fetch_all(
        f"SELECT * FROM emails {'WHERE category = ?' if category else ''} ORDER BY created_at DESC LIMIT ?",
        (category, limit) if category else (limit,)
    )

    return {
        "exported_at": datetime.now().isoformat(),
        "count": len(emails),
        "emails": emails
    }


@router.get("/export/rules/json")
async def export_rules_json(user_id: int = 1):
    rules = db.get_rules_by_user(user_id)

    return {
        "exported_at": datetime.now().isoformat(),
        "count": len(rules),
        "rules": rules
    }


@router.get("/export/feedback/json")
async def export_feedback_json(limit: int = 1000):
    feedback = db.fetch_all(
        "SELECT * FROM feedback ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )

    return {
        "exported_at": datetime.now().isoformat(),
        "count": len(feedback),
        "feedback": feedback
    }


@router.post("/import/emails/json")
async def import_emails_json(data: dict):
    emails = data.get("emails", [])
    imported = 0
    skipped_no_account = 0
    failures = 0

    for index, email_data in enumerate(emails):
        sender_email = email_data.get("sender_email", "") or ""
        try:
            account = db.get_account_by_email(sender_email)
            if not account:
                skipped_no_account += 1
                _log.debug(
                    "import emails: skipped row %s (no account for sender_email=%s)",
                    index,
                    sender_email[:120] if sender_email else "(empty)",
                )
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
            _log.warning(
                "import emails: failed row %s message_id=%s: %s",
                index,
                str(email_data.get("message_id", ""))[:80],
                exc,
            )

    return {
        "status": "success",
        "imported": imported,
        "total": len(emails),
        "skipped_no_account": skipped_no_account,
        "failures": failures,
    }


@router.post("/import/rules/json")
async def import_rules_json(data: dict, user_id: int = 1):
    rules = data.get("rules", [])
    imported = 0
    failures = 0

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
            _log.warning(
                "from backend import rules: failed row %s name=%s: %s",
                index,
                str(rule.get("name", ""))[:80],
                exc,
            )

    return {
        "status": "success",
        "imported": imported,
        "total": len(rules),
        "failures": failures,
    }


@router.get("/export/all")
async def export_all():
    emails = db.fetch_all("SELECT * FROM emails ORDER BY created_at DESC LIMIT 1000")
    rules = db.get_rules_by_user(1)
    feedback = db.fetch_all("SELECT * FROM feedback ORDER BY created_at DESC LIMIT 500")
    categories = db.get_all_categories()

    return {
        "exported_at": datetime.now().isoformat(),
        "version": "9.7.0",
        "data": {
            "emails": {
                "count": len(emails),
                "items": emails
            },
            "rules": {
                "count": len(rules),
                "items": rules
            },
            "feedback": {
                "count": len(feedback),
                "items": feedback
            },
            "categories": {
                "count": len(categories),
                "items": categories
            }
        }
    }


@router.post("/import/all")
async def import_all(data: dict):
    imported = {"emails": 0, "rules": 0, "feedback": 0}
    skipped_no_account = 0
    rule_failures = 0
    email_failures = 0

    if "data" in data:
        data = data["data"]

    if "emails" in data:
        emails = data["emails"].get("items", [])
        for index, email_data in enumerate(emails):
            sender_email = email_data.get("sender_email", "") or ""
            try:
                account = db.get_account_by_email(sender_email)
                if not account:
                    skipped_no_account += 1
                    _log.debug(
                        "import/all emails: skipped %s no account (%s)",
                        index,
                        sender_email[:120] if sender_email else "(empty)",
                    )
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
                _log.warning(
                    "import/all emails: failed %s message_id=%s: %s",
                    index,
                    str(email_data.get("message_id", ""))[:80],
                    exc,
                )

    if "rules" in data:
        rules = data["rules"].get("items", [])
        for index, rule in enumerate(rules):
            try:
                db.add_rule(
                    user_id=1,
                    name=rule.get("name", "Imported"),
                    condition=rule.get("condition", "{}"),
                    action=rule.get("action", "{}"),
                )
                imported["rules"] += 1
            except Exception as exc:
                rule_failures += 1
                _log.warning(
                    "import/all rules: failed %s name=%s: %s",
                    index,
                    str(rule.get("name", ""))[:80],
                    exc,
                )

    result = {
        "status": "success",
        "imported": imported,
        "skipped_no_account": skipped_no_account,
        "email_import_failures": email_failures,
        "rule_import_failures": rule_failures,
    }
    return result


@router.delete("/data/emails")
async def clear_emails():
    db.execute("DELETE FROM emails")
    db.execute("DELETE FROM predictions")
    db.execute("DELETE FROM embeddings")

    return {"status": "success", "message": "All emails deleted"}


@router.delete("/data/feedback")
async def clear_feedback():
    db.execute("DELETE FROM feedback")
    return {"status": "success", "message": "All feedback deleted"}


@router.delete("/data/rules")
async def clear_rules(user_id: int = 1):
    db.execute("DELETE FROM rules WHERE user_id = ?", (user_id,))
    return {"status": "success", "message": "All rules deleted"}