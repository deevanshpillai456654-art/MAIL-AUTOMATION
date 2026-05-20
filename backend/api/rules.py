"""
Rule engine API endpoints.

Rules are now durable and operational: creating a rule stores JSON safely,
loads it into the runtime engine, applies it to existing local emails, creates
missing labels/folders, and attempts provider writes when credentials support it.
"""

import json
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime

from backend.auth.local_auth import require_local_auth_or_localhost

from backend.rules.engine import (
    Rule,
    RuleEngine,
    DEFAULT_RULES,
    RULE_PRESET_PACKS,
    create_rule_from_dict,
    build_rule_engine,
    normalize_actions,
    parse_condition as parse_rule_condition,
    rule_to_public_dict,
)
from backend.rules.action_executor import RuleActionExecutor
from backend.core.email_forwarding import normalize_forward_payload, UniversalEmailForwarder
from backend.db.database import Database
from backend import config

router = APIRouter(dependencies=[Depends(require_local_auth_or_localhost)])
db = Database(config.DB_PATH)
rule_engine = RuleEngine()


def ensure_local_user_id(user_id: int = 1) -> int:
    if user_id and db.fetch_one("SELECT id FROM users WHERE id = ?", (user_id,)):
        return user_id
    return db.add_user("local@aiemailorganizer.local", "local")


def reload_rule_engine() -> RuleEngine:
    global rule_engine
    rule_engine = build_rule_engine(db, include_defaults=False)
    return rule_engine


reload_rule_engine()


class RuleInput(BaseModel):
    name: str
    condition: dict
    actions: List[dict] = []
    description: Optional[str] = ""
    enabled: bool = True
    apply_existing: bool = True
    provider_write: bool = False
    mailbox_scope: str = "all"
    mailbox_id: Optional[int] = None
    scan_scope: str = "entire_email_with_attachments"
    match_mode: str = "any"
    priority: str = "Medium"
    stop_processing: bool = False
    is_sample: bool = False


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    condition: Optional[dict] = None
    actions: Optional[List[dict]] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    apply_existing: Optional[bool] = False
    provider_write: Optional[bool] = False
    mailbox_scope: Optional[str] = None
    mailbox_id: Optional[int] = None
    scan_scope: Optional[str] = None
    match_mode: Optional[str] = None
    priority: Optional[str] = None
    stop_processing: Optional[bool] = None


class EmailInput(BaseModel):
    id: Optional[int] = None
    subject: str
    sender_email: str
    sender: str = ""
    body: str = ""
    category: Optional[str] = None
    priority: Optional[str] = "Medium"
    has_attachments: bool = False
    date: Optional[str] = None


class ApplyRulesInput(BaseModel):
    email_id: Optional[int] = None
    mailbox_id: Optional[int] = None
    message_ids: Optional[List[int]] = None
    limit: int = 1000
    category: Optional[str] = None
    provider_write: bool = False


class RuleRunInput(BaseModel):
    mailbox_id: Optional[int] = None
    message_ids: Optional[List[int]] = None
    limit: int = 100
    category: Optional[str] = None
    provider_write: bool = False


class ForwardingRuleInput(BaseModel):
    name: str = "Auto forward matched emails"
    condition: dict = {"type": "subject_contains", "value": ["rfq"]}
    to: Any
    cc: Optional[Any] = None
    bcc: Optional[Any] = None
    note: Optional[str] = "Forwarded automatically by AI Email Organizer rule automation."
    subject_prefix: str = "Fwd:"
    enabled: bool = True
    apply_existing: bool = True
    provider_write: bool = False
    also_label: Optional[str] = "Forwarded"
    also_move_to_folder: Optional[str] = None


class ForwardTestInput(BaseModel):
    email_id: int
    to: Any
    cc: Optional[Any] = None
    bcc: Optional[Any] = None
    note: Optional[str] = "Forwarding test from AI Email Organizer."
    provider_write: bool = False


@router.get("/rules")
async def get_all_rules():
    engine = reload_rule_engine()
    rules_data = [rule_to_public_dict(rule) for rule in engine.rules]
    return {"rules": rules_data, "count": len(rules_data)}


@router.post("/rules")
async def create_automation_rule(rule_input: RuleInput):
    try:
        actions = normalize_actions(rule_input.actions)
        if not actions:
            raise HTTPException(status_code=400, detail="At least one valid rule action is required")

        rule = Rule(
            name=rule_input.name,
            condition=parse_rule_condition(rule_input.condition),
            actions=actions,
            enabled=rule_input.enabled,
            description=rule_input.description,
        )
        rule_engine.add_rule(rule)

        rule_id = db.add_rule(
            user_id=ensure_local_user_id(1),
            name=rule_input.name,
            condition=json.dumps(rule_input.condition, sort_keys=True),
            action=json.dumps(actions, sort_keys=True),
            description=rule_input.description or "",
            status="active" if rule_input.enabled else "paused",
            mailbox_scope=rule_input.mailbox_scope or "all",
            mailbox_id=rule_input.mailbox_id,
            scan_scope=rule_input.scan_scope or "entire_email_with_attachments",
            match_mode=rule_input.match_mode or "any",
            priority=rule_input.priority or "Medium",
            stop_processing=bool(rule_input.stop_processing),
            is_sample=bool(rule_input.is_sample),
            created_by=1,
        )
        reload_rule_engine()

        apply_summary = None
        if rule_input.apply_existing:
            apply_summary = RuleActionExecutor(db, enable_provider_write=rule_input.provider_write).apply_rules_to_existing_emails(
                limit=1000,
                mailbox_id=rule_input.mailbox_id if rule_input.mailbox_scope == "selected" else None,
            )

        return {
            "status": "success",
            "message": f"Rule '{rule_input.name}' created and existing emails checked",
            "rule": rule_input.name,
            "rule_id": rule_id,
            "apply_summary": apply_summary,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rules/apply")
async def apply_rules(payload: ApplyRulesInput = Body(default={})):
    try:
        executor = RuleActionExecutor(db, enable_provider_write=payload.provider_write)
        if payload.email_id:
            result = executor.apply_rules_to_email_id(payload.email_id)
        else:
            result = executor.apply_rules_to_existing_emails(
                limit=payload.limit,
                category=payload.category,
                mailbox_id=payload.mailbox_id,
                message_ids=payload.message_ids,
            )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/rules/all")
async def clear_all_rules():
    rule_engine.rules = []
    db.execute("UPDATE rules SET is_active = 0")
    return {"status": "success", "message": "All custom rules disabled; defaults remain available after reload"}


@router.get("/rules/stats")
async def get_rule_stats():
    engine = reload_rule_engine()
    stats = engine.get_statistics()
    stats.update({
        "labels": len(db.get_all_labels()),
        "folders": len(db.get_all_folders()),
        "audited_actions": len(db.fetch_all("SELECT id FROM rule_action_audit ORDER BY id DESC LIMIT 1000")),
    })
    return stats


@router.get("/rules/labels")
async def get_labels(account_id: Optional[int] = None):
    labels = db.get_all_labels(account_id)
    return {"labels": labels, "count": len(labels)}


@router.get("/rules/folders")
async def get_folders(account_id: Optional[int] = None):
    folders = db.get_all_folders(account_id)
    return {"folders": folders, "count": len(folders)}


class BucketCreateRequest(BaseModel):
    name: str
    account_id: Optional[int] = None


@router.post("/rules/labels")
async def create_label(body: BucketCreateRequest):
    from backend.rules.action_executor import normalize_bucket_name
    name = normalize_bucket_name(body.name)
    if not name:
        raise HTTPException(status_code=400, detail="Label name is required")
    db.ensure_mail_label(body.account_id, name)
    return {"status": "created", "label": name}


@router.post("/rules/folders")
async def create_folder(body: BucketCreateRequest):
    from backend.rules.action_executor import normalize_bucket_name
    name = normalize_bucket_name(body.name)
    if not name:
        raise HTTPException(status_code=400, detail="Folder name is required")
    db.ensure_mail_folder(body.account_id, name)
    return {"status": "created", "folder": name}


@router.get("/rules/audit")
async def get_rule_audit(limit: int = 100):
    rows = db.fetch_all("SELECT * FROM rule_action_audit ORDER BY created_at DESC, id DESC LIMIT ?", (min(limit, 1000),))
    return {"actions": rows, "count": len(rows)}


@router.post("/rules/{rule_id:int}/simulate")
async def simulate_rule_by_id(rule_id: int, payload: RuleRunInput = Body(default={})):
    result = RuleActionExecutor(db, enable_provider_write=False).simulate_rule(
        rule_id,
        limit=payload.limit,
        mailbox_id=payload.mailbox_id,
        category=payload.category,
        message_ids=payload.message_ids,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message") or "Rule not found")
    return result


@router.post("/rules/{rule_id:int}/apply")
async def apply_rule_by_id(rule_id: int, payload: RuleRunInput = Body(default={})):
    result = RuleActionExecutor(db, enable_provider_write=payload.provider_write).apply_rule(
        rule_id,
        limit=payload.limit,
        mailbox_id=payload.mailbox_id,
        category=payload.category,
        message_ids=payload.message_ids,
        provider_write=payload.provider_write,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message") or "Rule not found")
    return result


@router.get("/rules/{rule_id:int}/logs")
async def get_rule_logs_by_id(rule_id: int, limit: int = 100):
    rows = db.fetch_all(
        "SELECT * FROM rule_execution_logs WHERE rule_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (rule_id, min(max(int(limit or 100), 1), 1000)),
    )
    return {"logs": rows, "count": len(rows), "rule_id": rule_id}


@router.put("/rules/{rule_id:int}")
async def update_rule_by_id(rule_id: int, rule_update: RuleUpdate):
    existing = db.fetch_one("SELECT * FROM rules WHERE id = ?", (rule_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Rule not found")
    condition_payload = rule_update.condition if rule_update.condition is not None else json.loads(existing["condition"] or "{}")
    action_payload = normalize_actions(rule_update.actions if rule_update.actions is not None else existing["action"])
    db.execute(
        """UPDATE rules
           SET name = ?, condition = ?, action = ?, description = ?, is_active = ?, status = ?,
               mailbox_scope = ?, mailbox_id = ?, scan_scope = ?, match_mode = ?, priority = ?,
               stop_processing = ?, updated_at = ?
           WHERE id = ?""",
        (
            rule_update.name if rule_update.name is not None else existing["name"],
            json.dumps(condition_payload, sort_keys=True),
            json.dumps(action_payload, sort_keys=True),
            rule_update.description if rule_update.description is not None else existing.get("description"),
            1 if (rule_update.enabled if rule_update.enabled is not None else existing.get("is_active")) else 0,
            "active" if (rule_update.enabled if rule_update.enabled is not None else existing.get("is_active")) else "paused",
            rule_update.mailbox_scope if rule_update.mailbox_scope is not None else existing.get("mailbox_scope"),
            rule_update.mailbox_id if rule_update.mailbox_id is not None else existing.get("mailbox_id"),
            rule_update.scan_scope if rule_update.scan_scope is not None else existing.get("scan_scope"),
            rule_update.match_mode if rule_update.match_mode is not None else existing.get("match_mode"),
            rule_update.priority if rule_update.priority is not None else existing.get("priority"),
            1 if (rule_update.stop_processing if rule_update.stop_processing is not None else existing.get("stop_processing")) else 0,
            datetime.now().isoformat(),
            rule_id,
        ),
    )
    reload_rule_engine()
    return {"status": "success", "rule_id": rule_id}


@router.delete("/rules/{rule_id:int}")
async def delete_rule_by_id(rule_id: int):
    db.execute("UPDATE rules SET is_active = 0, status = 'archived', updated_at = ? WHERE id = ?", (datetime.now().isoformat(), rule_id))
    reload_rule_engine()
    return {"status": "success", "rule_id": rule_id}


@router.post("/rules/forwarding")
async def create_forwarding_rule(payload: ForwardingRuleInput):
    """Create an auto-forward rule, for example RFQ subject -> xyz@example.com."""
    try:
        forward_payload = normalize_forward_payload({
            "to": payload.to,
            "cc": payload.cc,
            "bcc": payload.bcc,
            "note": payload.note,
            "subject_prefix": payload.subject_prefix,
            "include_body": True,
            "include_metadata": True,
        })
        actions = [{"type": "forward_email", "value": forward_payload}]
        if payload.also_label:
            actions.append({"type": "add_label", "value": payload.also_label})
        if payload.also_move_to_folder:
            actions.append({"type": "move_to_folder", "value": payload.also_move_to_folder})
        rule_id = db.add_rule(
            user_id=ensure_local_user_id(1),
            name=payload.name,
            condition=json.dumps(payload.condition, sort_keys=True),
            action=json.dumps(actions, sort_keys=True),
        )
        if not payload.enabled:
            db.execute("UPDATE rules SET is_active = 0 WHERE id = ?", (rule_id,))
        reload_rule_engine()
        apply_summary = None
        if payload.enabled and payload.apply_existing:
            apply_summary = RuleActionExecutor(db, enable_provider_write=payload.provider_write).apply_rules_to_existing_emails(limit=1000)
        return {
            "status": "success",
            "rule_id": rule_id,
            "rule": payload.name,
            "forwarding": UniversalEmailForwarder.safe_payload(forward_payload),
            "actions": actions,
            "apply_summary": apply_summary,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/rules/forwarding/test")
async def test_forwarding_rule(payload: ForwardTestInput):
    email = db.fetch_one("SELECT * FROM emails WHERE id = ?", (payload.email_id,))
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    value = {"to": payload.to, "cc": payload.cc, "bcc": payload.bcc, "note": payload.note, "subject_prefix": "Fwd:"}
    result = UniversalEmailForwarder(db, enable_provider_write=payload.provider_write).forward_email(email, value, rule_name="manual forwarding test")
    return {"status": "success" if result.get("success") else "failed", "result": result}


@router.get("/rules/forwarding/audit")
async def get_forwarding_audit(limit: int = 100):
    rows = db.get_forward_audit(limit)
    return {"forwards": rows, "count": len(rows)}


@router.get("/rules/presets")
async def list_rule_presets():
    packs = []
    for key, pack in RULE_PRESET_PACKS.items():
        packs.append({
            "id": key,
            "name": pack["name"],
            "description": pack["description"],
            "rule_count": pack.get("rule_count", len(pack["rules"])),
            "folders": pack.get("folders", []),
            "tags": pack.get("tags", []),
        })
    return {"presets": packs, "count": len(packs)}


@router.post("/rules/presets/{preset_name}")
async def install_rule_preset(preset_name: str, apply_existing: bool = True):
    pack = RULE_PRESET_PACKS.get(preset_name)
    if not pack:
        raise HTTPException(status_code=404, detail=f"Preset pack '{preset_name}' not found. Available: {list(RULE_PRESET_PACKS.keys())}")

    user_id = ensure_local_user_id(1)
    installed = []
    skipped = []

    for rule_dict in pack["rules"]:
        name = rule_dict["name"]
        existing = db.fetch_one("SELECT id FROM rules WHERE name = ?", (name,))
        if existing:
            skipped.append(name)
            continue
        actions = normalize_actions(rule_dict.get("actions", []))
        rule_id = db.add_rule(
            user_id=user_id,
            name=name,
            condition=json.dumps(rule_dict.get("condition", {}), sort_keys=True),
            action=json.dumps(actions, sort_keys=True),
        )
        installed.append({"name": name, "rule_id": rule_id})

    for folder in pack.get("folders", []):
        try:
            db.ensure_mail_folder(None, folder)
            db.ensure_mail_label(None, folder)
        except Exception:
            pass

    reload_rule_engine()

    apply_summary = None
    if apply_existing and installed:
        apply_summary = RuleActionExecutor(db, enable_provider_write=False).apply_rules_to_existing_emails(limit=2000)

    return {
        "status": "success",
        "preset": pack["name"],
        "installed": installed,
        "skipped": skipped,
        "installed_count": len(installed),
        "skipped_count": len(skipped),
        "apply_summary": apply_summary,
    }


@router.get("/rules/forwarding/status")
async def get_forwarding_status():
    row = db.fetch_one("""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN provider_success = 1 THEN 1 ELSE 0 END) AS provider_success,
            SUM(CASE WHEN local_success = 1 THEN 1 ELSE 0 END) AS local_success
        FROM email_forward_audit
    """) or {}
    pending = db.fetch_one("SELECT COUNT(*) AS count FROM emails WHERE forward_status = 'queued'") or {"count": 0}
    return {
        "status": "ready",
        "total_forward_actions": row.get("total") or 0,
        "provider_success": row.get("provider_success") or 0,
        "local_success": row.get("local_success") or 0,
        "queued": pending.get("count") or 0,
        "supported_providers": ["gmail", "outlook", "microsoft365", "exchange", "smtp", "imap/smtp providers"],
    }



@router.get("/rules/templates")
async def enterprise_rule_templates():
    return {"templates": [
        {"id":"invoice-forwarding", "name":"Invoice Forwarding", "group":"Finance Rules", "condition":{"type":"or","value":[{"type":"subject_contains","value":["invoice"]},{"type":"body_contains","value":["invoice"]}]}, "actions":[{"type":"add_label","value":"Finance"},{"type":"forward_email","value":{"to":"accounts@company.com","subject_prefix":"Fwd:"}}]},
        {"id":"rfq-routing", "name":"RFQ Routing", "group":"RFQ Rules", "condition":{"type":"or","value":[{"type":"subject_contains","value":["rfq"]},{"type":"body_contains","value":["request for quote"]}]}, "actions":[{"type":"add_label","value":"RFQ"},{"type":"forward_email","value":{"to":"sales@company.com","subject_prefix":"Fwd:"}}]},
        {"id":"support-escalation", "name":"Support Escalation", "group":"Support Rules", "condition":{"type":"body_contains","value":["urgent","not working","complaint"]}, "actions":[{"type":"add_label","value":"Support"},{"type":"notify","value":"support-team"}]},
        {"id":"vip-client-handling", "name":"VIP Client Handling", "group":"VIP Client Rules", "condition":{"type":"sender_domain","value":["vipclient.com"]}, "actions":[{"type":"set_priority","value":"High"},{"type":"add_label","value":"VIP"}]},
        {"id":"logistics-workflow", "name":"Logistics Workflow", "group":"Logistics Rules", "condition":{"type":"or","value":[{"type":"body_contains","value":["shipment","customs","container"]},{"type":"subject_contains","value":["freight"]}]}, "actions":[{"type":"add_label","value":"Logistics"},{"type":"move_to_folder","value":"Operations"}]},
    ]}

@router.get("/rules/export")
async def export_rules():
    rows = db.fetch_all("SELECT * FROM rules ORDER BY created_at DESC")
    return {"format":"json", "rules": rows, "count": len(rows)}

@router.post("/rules/import")
async def import_rules(payload: dict = Body(default_factory=dict)):
    imported = 0
    for item in payload.get("rules", []):
        name = str(item.get("name") or "Imported Rule")[:100]
        condition = item.get("condition") if isinstance(item.get("condition"), str) else json.dumps(item.get("condition") or {}, sort_keys=True)
        action = item.get("action") if isinstance(item.get("action"), str) else json.dumps(item.get("actions") or item.get("action") or [], sort_keys=True)
        db.add_rule(ensure_local_user_id(1), name, condition, action)
        imported += 1
    reload_rule_engine()
    return {"status":"success", "imported": imported}

@router.post("/rules/{rule_name}/duplicate")
async def duplicate_rule(rule_name: str):
    row = db.fetch_one("SELECT * FROM rules WHERE name = ? ORDER BY id DESC LIMIT 1", (rule_name,))
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    new_name = f"{rule_name} Copy"
    rule_id = db.add_rule(ensure_local_user_id(1), new_name, row["condition"], row["action"])
    reload_rule_engine()
    return {"status":"success", "rule_id": rule_id, "name": new_name}

@router.post("/rules/{rule_name}/pause")
async def pause_rule(rule_name: str):
    db.execute("UPDATE rules SET is_active = 0 WHERE name = ?", (rule_name,))
    reload_rule_engine()
    return {"status":"paused", "rule": rule_name}

@router.post("/rules/{rule_name}/resume")
async def resume_rule(rule_name: str):
    db.execute("UPDATE rules SET is_active = 1 WHERE name = ?", (rule_name,))
    reload_rule_engine()
    return {"status":"active", "rule": rule_name}

@router.post("/rules/{rule_name}/archive")
async def archive_rule(rule_name: str):
    db.execute("UPDATE rules SET is_active = 0 WHERE name = ?", (rule_name,))
    return {"status":"archived", "rule": rule_name, "restore_available": True}

@router.post("/rules/{rule_name}/restore")
async def restore_rule(rule_name: str):
    db.execute("UPDATE rules SET is_active = 1 WHERE name = ?", (rule_name,))
    reload_rule_engine()
    return {"status":"restored", "rule": rule_name}

@router.post("/rules/simulate")
async def simulate_rule_execution(email: EmailInput):
    email_dict = {"id": email.id, "subject": email.subject, "sender_email": email.sender_email, "sender": email.sender, "body": email.body, "body_text": email.body, "category": email.category, "priority": email.priority, "has_attachments": email.has_attachments, "date": email.date or datetime.now().isoformat()}
    matches = reload_rule_engine().evaluate(email_dict)
    return {"simulation": True, "matched_rules": matches, "skipped_rules": [], "blocked_rules": [], "final_outcome": "execute" if matches else "no_action"}


@router.get("/rules/{rule_name}")
async def get_rule(rule_name: str):
    engine = reload_rule_engine()
    rule = engine.get_rule(rule_name)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    data = rule_to_public_dict(rule)
    data["condition"] = str(rule.condition)
    return data


@router.put("/rules/{rule_name}")
async def update_rule(rule_name: str, rule_update: RuleUpdate):
    existing = db.fetch_one("SELECT * FROM rules WHERE name = ? AND is_active = 1 ORDER BY id DESC LIMIT 1", (rule_name,))
    engine = reload_rule_engine()
    rule = engine.get_rule(rule_name)
    if not rule and not existing:
        raise HTTPException(status_code=404, detail="Rule not found")

    new_name = rule_update.name if rule_update.name is not None else rule_name
    condition_payload = rule_update.condition if rule_update.condition is not None else (json.loads(existing["condition"]) if existing else {})
    action_payload = normalize_actions(rule_update.actions if rule_update.actions is not None else (existing["action"] if existing else rule.actions))
    enabled = rule_update.enabled if rule_update.enabled is not None else True

    if existing:
        db.execute(
            "UPDATE rules SET name = ?, condition = ?, action = ?, is_active = ? WHERE id = ?",
            (new_name, json.dumps(condition_payload, sort_keys=True), json.dumps(action_payload, sort_keys=True), 1 if enabled else 0, existing["id"]),
        )
    else:
        db.add_rule(ensure_local_user_id(1), new_name, json.dumps(condition_payload, sort_keys=True), json.dumps(action_payload, sort_keys=True))
    reload_rule_engine()

    apply_summary = None
    if rule_update.apply_existing:
        apply_summary = RuleActionExecutor(db, enable_provider_write=bool(rule_update.provider_write)).apply_rules_to_existing_emails(limit=1000)

    return {"status": "success", "message": f"Rule '{rule_name}' updated", "apply_summary": apply_summary}


@router.delete("/rules/{rule_name}")
async def delete_rule(rule_name: str):
    rule_engine.remove_rule(rule_name)
    db.execute("UPDATE rules SET is_active = 0 WHERE name = ?", (rule_name,))
    return {"status": "success", "message": f"Rule '{rule_name}' disabled"}


@router.post("/rules/{rule_name}/toggle")
async def toggle_rule(rule_name: str):
    row = db.fetch_one("SELECT * FROM rules WHERE name = ? ORDER BY id DESC LIMIT 1", (rule_name,))
    if row:
        new_value = 0 if row.get("is_active") else 1
        db.execute("UPDATE rules SET is_active = ? WHERE id = ?", (new_value, row["id"]))
        reload_rule_engine()
        return {"status": "success", "message": f"Rule is now {'enabled' if new_value else 'disabled'}"}

    rule = rule_engine.get_rule(rule_name)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.enabled = not rule.enabled
    return {"status": "success", "message": f"Rule is now {'enabled' if rule.enabled else 'disabled'}"}


@router.post("/rules/evaluate")
async def evaluate_rules(email: EmailInput):
    email_dict = {
        "id": email.id,
        "subject": email.subject,
        "sender_email": email.sender_email,
        "sender": email.sender,
        "body": email.body,
        "body_text": email.body,
        "category": email.category,
        "priority": email.priority,
        "has_attachments": email.has_attachments,
        "date": email.date or datetime.now().isoformat(),
    }

    results = reload_rule_engine().evaluate(email_dict)
    return {"email": email_dict, "matched_rules": results, "count": len(results), "dry_run": True}


@router.post("/rules/defaults")
async def load_default_rules():
    user_id = ensure_local_user_id(1)
    count = 0
    for rule_dict in DEFAULT_RULES:
        if db.fetch_one("SELECT id FROM rules WHERE name = ? AND COALESCE(is_sample, 0) = 0", (rule_dict["name"],)):
            continue
        actions = normalize_actions(rule_dict.get("actions", []))
        db.add_rule(
            user_id=user_id,
            name=rule_dict["name"],
            condition=json.dumps(rule_dict.get("condition", {}), sort_keys=True),
            action=json.dumps(actions, sort_keys=True),
            description=rule_dict.get("description", ""),
            is_sample=False,
        )
        count += 1
    reload_rule_engine()
    return {"status": "success", "message": f"Loaded {count} sample rule(s)", "loaded_count": count}


def parse_condition(condition_data: dict):
    """Parse dashboard/API rule condition data through the shared fail-closed rule parser."""
    return parse_rule_condition(condition_data or {})
