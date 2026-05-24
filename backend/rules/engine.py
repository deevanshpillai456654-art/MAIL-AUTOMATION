"""
Durable rule engine for email automation.

The previous engine only returned "Would move/add label" messages.  This
version keeps the lightweight matcher, but also normalizes rule definitions so
API, dashboard, sync and replay paths can all run the same real actions through
rules.action_executor.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from backend.rules.scanner import build_search_document


class RuleAction(str, Enum):
    MOVE_TO_FOLDER = "move_to_folder"
    ADD_LABEL = "add_label"
    SET_CATEGORY = "set_category"
    MARK_READ = "mark_read"
    MARK_UNREAD = "mark_unread"
    SET_PRIORITY = "set_priority"
    ADD_CATEGORY = "add_category"
    NOTIFY = "notify"
    ARCHIVE = "archive"
    DELETE = "delete"
    FLAG = "flag"
    FORWARD_EMAIL = "forward_email"


ACTION_ALIASES = {
    "move": RuleAction.MOVE_TO_FOLDER.value,
    "move_to": RuleAction.MOVE_TO_FOLDER.value,
    "move_to_label": RuleAction.MOVE_TO_FOLDER.value,
    "move_to_folder": RuleAction.MOVE_TO_FOLDER.value,
    "folder": RuleAction.MOVE_TO_FOLDER.value,
    "create_folder": RuleAction.MOVE_TO_FOLDER.value,
    "label": RuleAction.ADD_LABEL.value,
    "add_label": RuleAction.ADD_LABEL.value,
    "auto_label": RuleAction.ADD_LABEL.value,
    "create_label": RuleAction.ADD_LABEL.value,
    "category": RuleAction.SET_CATEGORY.value,
    "set_category": RuleAction.SET_CATEGORY.value,
    "add_category": RuleAction.ADD_CATEGORY.value,
    "mark_read": RuleAction.MARK_READ.value,
    "read": RuleAction.MARK_READ.value,
    "mark_unread": RuleAction.MARK_UNREAD.value,
    "unread": RuleAction.MARK_UNREAD.value,
    "priority": RuleAction.SET_PRIORITY.value,
    "set_priority": RuleAction.SET_PRIORITY.value,
    "archive": RuleAction.ARCHIVE.value,
    "delete": RuleAction.DELETE.value,
    "flag": RuleAction.FLAG.value,
    "star": RuleAction.FLAG.value,
    "notify": RuleAction.NOTIFY.value,
    "forward": RuleAction.FORWARD_EMAIL.value,
    "forward_email": RuleAction.FORWARD_EMAIL.value,
    "auto_forward": RuleAction.FORWARD_EMAIL.value,
    "auto_forward_email": RuleAction.FORWARD_EMAIL.value,
    "forward_to": RuleAction.FORWARD_EMAIL.value,
    "send_to": RuleAction.FORWARD_EMAIL.value,
    "rfq_forward": RuleAction.FORWARD_EMAIL.value,
}


class RuleCondition:
    """Base condition class with fail-closed default matching."""

    def match(self, email: Dict) -> bool:
        return False


class NeverMatch(RuleCondition):
    """Condition used for invalid or unsupported rule definitions."""

    def match(self, email: Dict) -> bool:
        return False


class AlwaysMatch(RuleCondition):
    """Explicit condition for intentionally unconditional rules."""

    def match(self, email: Dict) -> bool:
        return True


class SubjectContains(RuleCondition):
    def __init__(self, keywords: List[str]):
        self.keywords = [str(k).lower() for k in keywords if str(k).strip()]

    def match(self, email: Dict) -> bool:
        subject = str(email.get("subject") or "").lower()
        return any(kw in subject for kw in self.keywords)


class SenderContains(RuleCondition):
    def __init__(self, patterns: List[str]):
        self.patterns = [str(p).lower() for p in patterns if str(p).strip()]

    def match(self, email: Dict) -> bool:
        sender = " ".join([
            str(email.get("sender_email") or ""),
            str(email.get("sender") or ""),
            str(email.get("from") or ""),
        ]).lower()
        return any(p in sender for p in self.patterns)


class BodyContains(RuleCondition):
    def __init__(self, keywords: List[str]):
        self.keywords = [str(k).lower() for k in keywords if str(k).strip()]

    def match(self, email: Dict) -> bool:
        body = " ".join([
            str(email.get("body") or ""),
            str(email.get("body_text") or ""),
            str(email.get("snippet") or ""),
        ]).lower()
        return any(kw in body for kw in self.keywords)


class SearchTextContains(RuleCondition):
    def __init__(self, keywords: List[str], source: str = "full_text"):
        self.keywords = [str(k).lower() for k in keywords if str(k).strip()]
        self.source = source

    def match(self, email: Dict) -> bool:
        document = build_search_document(email)
        if self.source == "full_text":
            text = document["full_text"]
        else:
            text = document["sources"].get(self.source, "")
        text = str(text or "").lower()
        return any(kw in text for kw in self.keywords)


class FieldOperatorCondition(RuleCondition):
    def __init__(self, field: str, operator: str, value: Any,
                 case_sensitive: bool = False, use_regex: bool = False):
        self.field = str(field or "entire_email").lower()
        self.operator = str(operator or "contains").lower()
        self.values = [str(v) for v in _as_list(value) if str(v).strip()]
        self.case_sensitive = case_sensitive
        self.use_regex = use_regex

    def _source_text(self, email: Dict) -> str:
        source_map = {
            "subject": "subject",
            "sender": "sender",
            "from": "sender",
            "sender_email": "sender",
            "body": "body",
            "snippet": "snippet",
            "attachment_name": "attachment_filename",
            "attachment_filename": "attachment_filename",
            "attachment_content": "attachment_content",
            "attachment_text": "attachment_content",
            "attachment_type": "attachment_type",
            "ocr_text": "ocr_text",
            "headers": "headers",
            "entire_email": "full_text",
        }
        document = build_search_document(email)
        source_key = source_map.get(self.field, "full_text")
        return document["full_text"] if source_key == "full_text" else document["sources"].get(source_key, "")

    def match(self, email: Dict) -> bool:
        text = self._source_text(email)
        source = text if self.case_sensitive else text.lower()
        values = self.values if self.case_sensitive else [value.lower() for value in self.values]
        if self.use_regex or self.operator in {"regex", "regex_match"}:
            for pattern in self.values:
                try:
                    if len(pattern) <= 200 and re.search(pattern, text[:50000], 0 if self.case_sensitive else re.IGNORECASE):
                        return True
                except re.error:
                    continue
            return False
        if self.operator in {"has_attachment", "attachment_exists"}:
            return bool(email.get("attachments") or email.get("has_attachments") or build_search_document(email)["attachments"])
        if self.operator in {"does_not_contain", "not_contains"}:
            return all(value not in source for value in values if value)
        if self.operator in {"equals", "is", "="}:
            return any(source.strip() == value.strip() for value in values)
        if self.operator == "starts_with":
            return any(source.startswith(value) for value in values)
        if self.operator == "ends_with":
            return any(source.endswith(value) for value in values)
        if self.operator in {"all_keywords", "all"}:
            return all(value in source for value in values if value)
        return any(value in source for value in values if value)


class CategoryIs(RuleCondition):
    def __init__(self, categories: List[str]):
        self.categories = [str(c).lower() for c in categories if str(c).strip()]

    def match(self, email: Dict) -> bool:
        cat = str(email.get("category") or "").lower()
        return cat in self.categories


class PriorityIs(RuleCondition):
    def __init__(self, priorities: List[str]):
        self.priorities = [str(p).lower() for p in priorities if str(p).strip()]

    def match(self, email: Dict) -> bool:
        pri = str(email.get("priority") or "").lower()
        return pri in self.priorities


class HasAttachment(RuleCondition):
    def __init__(self, has_attachments: bool = True):
        self.has_attachments = bool(has_attachments)

    def match(self, email: Dict) -> bool:
        has_attach = bool(email.get("attachments") or email.get("has_attachments"))
        return has_attach == self.has_attachments


class AgeGreaterThan(RuleCondition):
    def __init__(self, days: int):
        self.days = int(days)

    def match(self, email: Dict) -> bool:
        try:
            date_str = email.get("date") or email.get("created_at") or ""
            if not date_str:
                return False
            email_date = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
            age = datetime.now() - email_date.replace(tzinfo=None)
            return age.days > self.days
        except Exception:
            return False


class DomainIs(RuleCondition):
    def __init__(self, domains: List[str]):
        self.domains = [str(d).lower().lstrip("@") for d in domains if str(d).strip()]

    def match(self, email: Dict) -> bool:
        sender = str(email.get("sender_email") or "")
        match = re.search(r"@([a-zA-Z0-9.-]+)", sender)
        if match:
            domain = match.group(1).lower()
            return domain in self.domains
        return False


class ConditionGroup(RuleCondition):
    """Group of conditions with AND/OR logic."""

    def __init__(self, conditions: List[RuleCondition], match_all: bool = True):
        self.conditions = conditions
        self.match_all = match_all

    def match(self, email: Dict) -> bool:
        if not self.conditions:
            return False
        return all(c.match(email) for c in self.conditions) if self.match_all else any(c.match(email) for c in self.conditions)


def parse_stored_value(raw: Any, fallback: Any = None) -> Any:
    """Parse JSON or legacy Python-literal rule payloads safely."""
    if raw is None:
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return fallback
    text = raw.strip()
    if not text:
        return fallback
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return fallback


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def normalize_condition_dict(condition_json: Dict) -> Dict:
    """Support both modern {type,value} and older dashboard shapes."""
    if not isinstance(condition_json, dict):
        return {"type": "never", "value": []}

    if "type" in condition_json:
        ctype = str(condition_json.get("type") or "").strip().lower()
        value = condition_json.get("value", [])
        if ctype in {"from_contains", "sender", "sender_email_contains"}:
            ctype = "sender_contains"
        elif ctype in {"subject", "subject_has", "subject_keywords"}:
            ctype = "subject_contains"
        elif ctype in {"body", "body_has", "body_keywords"}:
            ctype = "body_contains"
        elif ctype in {"entire_email", "full_email", "entire_email_contains", "message_search_text"}:
            ctype = "entire_email_contains"
        elif ctype in {"attachment_name", "attachment_filename", "attachment_name_contains"}:
            ctype = "attachment_name_contains"
        elif ctype in {"attachment_content", "attachment_text", "attachment_content_contains"}:
            ctype = "attachment_content_contains"
        elif ctype in {"attachment_type", "attachment_type_is"}:
            ctype = "attachment_type_match"
        elif ctype in {"category", "category_equals", "ai_intent"}:
            ctype = "category_is"
        elif ctype in {"priority", "priority_equals"}:
            ctype = "priority_is"
        elif ctype in {"domain", "sender_domain"}:
            ctype = "domain_is"
        normalized = dict(condition_json)
        normalized["type"] = ctype
        normalized["value"] = value
        return normalized

    # Legacy one-key forms used by early UI/extension paths.
    legacy_map = [
        ("subject_contains", "subject_contains"),
        ("subject_keywords", "subject_contains"),
        ("subject", "subject_contains"),
        ("sender_contains", "sender_contains"),
        ("from_contains", "sender_contains"),
        ("sender", "sender_contains"),
        ("body_contains", "body_contains"),
        ("body_keywords", "body_contains"),
        ("body", "body_contains"),
        ("category", "category_is"),
        ("category_is", "category_is"),
        ("ai_intent", "category_is"),
        ("priority", "priority_is"),
        ("priority_is", "priority_is"),
        ("domain", "domain_is"),
        ("domain_is", "domain_is"),
    ]
    for key, ctype in legacy_map:
        if key in condition_json:
            return {"type": ctype, "value": condition_json.get(key)}

    if all(k in condition_json for k in ("field", "operator", "value")):
        field = str(condition_json.get("field") or "").lower()
        op = str(condition_json.get("operator") or "").lower()
        value = condition_json.get("value")
        if field == "subject" and op in {"contains", "includes"}:
            return {"type": "subject_contains", "value": value}
        if field in {"sender", "from", "sender_email"} and op in {"contains", "includes"}:
            return {"type": "sender_contains", "value": value}
        if field == "body" and op in {"contains", "includes"}:
            return {"type": "body_contains", "value": value}
        if field == "category" and op in {"is", "equals", "="}:
            return {"type": "category_is", "value": value}
        return {
            "type": "field_operator",
            "field": field,
            "operator": op,
            "value": value,
            "case_sensitive": condition_json.get("case_sensitive"),
            "use_regex": condition_json.get("use_regex"),
        }

    return {"type": "never", "value": []}


def parse_condition(condition_json: Dict) -> RuleCondition:
    """Parse condition from JSON and fail closed when unsupported."""
    normalized = normalize_condition_dict(condition_json or {})
    condition_type = normalized.get("type")
    value = _as_list(normalized.get("value", []))

    if condition_type in {"always", "all"}:
        return AlwaysMatch()
    if condition_type == "subject_contains":
        return SubjectContains(value)
    if condition_type == "sender_contains":
        return SenderContains(value)
    if condition_type == "body_contains":
        return BodyContains(value)
    if condition_type == "entire_email_contains":
        return SearchTextContains(value, "full_text")
    if condition_type == "attachment_name_contains":
        return SearchTextContains(value, "attachment_filename")
    if condition_type == "attachment_content_contains":
        return SearchTextContains(value, "attachment_content")
    if condition_type == "attachment_type_match":
        return SearchTextContains(value, "attachment_type")
    if condition_type in {"field_operator", "contains", "does_not_contain", "equals", "starts_with", "ends_with", "regex_match", "any_keyword", "all_keywords"}:
        return FieldOperatorCondition(
            normalized.get("field") or "entire_email",
            normalized.get("operator") or condition_type,
            normalized.get("value"),
            case_sensitive=bool(normalized.get("case_sensitive")),
            use_regex=bool(normalized.get("use_regex")),
        )
    if condition_type == "category_is":
        return CategoryIs(value)
    if condition_type == "priority_is":
        return PriorityIs(value)
    if condition_type == "has_attachment":
        return HasAttachment(bool(value[0]) if value else True)
    if condition_type == "age_greater_than":
        return AgeGreaterThan(int(value[0]) if value else 7)
    if condition_type == "domain_is":
        return DomainIs(value)
    if condition_type == "and":
        return ConditionGroup([parse_condition(c) for c in value], match_all=True)
    if condition_type == "or":
        return ConditionGroup([parse_condition(c) for c in value], match_all=False)

    return NeverMatch()


def normalize_action(action: Any) -> Optional[Dict[str, Any]]:
    """Normalize action payloads into {type, value}."""
    if isinstance(action, str):
        parsed = parse_stored_value(action)
        if parsed is not None:
            return normalize_action(parsed)
        return None
    if not isinstance(action, dict):
        return None

    raw_type = action.get("type") or action.get("action")
    raw_value = action.get("value")

    # Legacy one-key action payloads: {"move_to": "Finance"}.
    if not raw_type:
        for key, value in action.items():
            alias = ACTION_ALIASES.get(str(key).strip().lower())
            if alias:
                raw_type = alias
                raw_value = value
                break

    normalized_type = ACTION_ALIASES.get(str(raw_type or "").strip().lower())
    if not normalized_type:
        return None

    if raw_value is None:
        for key in ("label", "folder", "category", "name", "target", "priority", "to", "recipient", "recipients", "cc", "bcc"):
            if key in action:
                raw_value = action[key]
                break

    return {"type": normalized_type, "value": raw_value}


def normalize_actions(actions: Any) -> List[Dict[str, Any]]:
    parsed = parse_stored_value(actions, actions)
    if isinstance(parsed, dict):
        # Explicit action dictionaries are single actions.  Plain maps such as
        # {"move_to": "Finance", "label": "Important"} represent multiple
        # actions from legacy dashboard/extension payloads.
        if "type" in parsed or "action" in parsed:
            maybe_single = normalize_action(parsed)
            return [maybe_single] if maybe_single else []
        normalized: List[Dict[str, Any]] = []
        for key, value in parsed.items():
            item = normalize_action({key: value})
            if item:
                normalized.append(item)
        return normalized
    if isinstance(parsed, list):
        return [a for a in (normalize_action(item) for item in parsed) if a]
    return []


class Rule:
    def __init__(
        self,
        name: str,
        condition: RuleCondition,
        actions: List[Dict],
        enabled: bool = True,
        description: str = "",
        rule_id: Optional[int] = None,
        mailbox_scope: str = "all",
        mailbox_id: Optional[int] = None,
        scan_scope: str = "entire_email_with_attachments",
        match_mode: str = "any",
        priority: str = "Medium",
        stop_processing: bool = False,
        is_sample: bool = False,
        condition_payload: Optional[Dict] = None,
    ):
        self.rule_id = rule_id
        self.name = name
        self.condition = condition
        self.actions = normalize_actions(actions)
        self.enabled = enabled
        self.description = description
        self.mailbox_scope = mailbox_scope or "all"
        self.mailbox_id = mailbox_id
        self.scan_scope = scan_scope or "entire_email_with_attachments"
        self.match_mode = match_mode or "any"
        self.priority = priority or "Medium"
        self.stop_processing = bool(stop_processing)
        self.is_sample = bool(is_sample)
        self.condition_payload = condition_payload or {}
        self.execution_count = 0
        self.last_executed = None

    def match(self, email: Dict) -> bool:
        if not self.enabled:
            return False
        if self.mailbox_scope == "selected" and self.mailbox_id:
            email_mailbox = email.get("mailbox_id") or email.get("account_id")
            if str(email_mailbox) != str(self.mailbox_id):
                return False
        return self.condition.match(email)

    def execute(self, email: Dict, context: Dict) -> Dict:
        """Return an action plan. Actual mutations are done by action_executor."""
        results = []
        for action in self.actions:
            action_type = action.get("type")
            action_value = action.get("value")
            result = {"action": action_type, "value": action_value, "success": True, "details": "planned"}
            if action_type == RuleAction.SET_CATEGORY.value:
                context["new_category"] = action_value
            results.append(result)

        self.execution_count += 1
        self.last_executed = datetime.now()
        return {
            "rule_id": self.rule_id,
            "rule_name": self.name,
            "matched": True,
            "actions": results,
            "email_id": email.get("id"),
            "timestamp": datetime.now().isoformat(),
        }


class RuleEngine:
    def __init__(self):
        self.rules: List[Rule] = []
        self.execution_log: List[Dict] = []

    def add_rule(self, rule: Rule):
        self.remove_rule(rule.name)
        self.rules.append(rule)

    def remove_rule(self, name: str):
        self.rules = [r for r in self.rules if r.name != name]

    def get_rule(self, name: str) -> Optional[Rule]:
        for rule in self.rules:
            if rule.name == name:
                return rule
        return None

    def enable_rule(self, name: str):
        rule = self.get_rule(name)
        if rule:
            rule.enabled = True

    def disable_rule(self, name: str):
        rule = self.get_rule(name)
        if rule:
            rule.enabled = False

    def evaluate(self, email: Dict) -> List[Dict]:
        """Evaluate all rules against an email and return action plans."""
        results = []
        for rule in self.rules:
            if rule.match(email):
                context = {}
                result = rule.execute(email, context)
                results.append(result)
                self.execution_log.append(result)
        return results

    def get_statistics(self) -> Dict:
        return {
            "total_rules": len(self.rules),
            "enabled_rules": sum(1 for r in self.rules if r.enabled),
            "total_executions": sum(r.execution_count for r in self.rules),
            "recent_executions": len(self.execution_log[-100:]),
        }


def create_rule_from_dict(rule_dict: Dict) -> Rule:
    """Create a Rule from dictionary."""
    condition = parse_condition(rule_dict.get("condition", {}))
    actions = normalize_actions(rule_dict.get("actions", []))
    if not actions and "action" in rule_dict:
        actions = normalize_actions(rule_dict.get("action"))

    return Rule(
        rule_id=rule_dict.get("id"),
        name=rule_dict.get("name", "Unnamed Rule"),
        condition=condition,
        actions=actions,
        enabled=bool(rule_dict.get("enabled", rule_dict.get("is_active", True))),
        description=rule_dict.get("description", ""),
        mailbox_scope=rule_dict.get("mailbox_scope", "all"),
        mailbox_id=rule_dict.get("mailbox_id"),
        scan_scope=rule_dict.get("scan_scope", "entire_email_with_attachments"),
        match_mode=rule_dict.get("match_mode", "any"),
        priority=rule_dict.get("priority", "Medium"),
        stop_processing=bool(rule_dict.get("stop_processing", False)),
        is_sample=bool(rule_dict.get("is_sample", False)),
        condition_payload=rule_dict.get("condition", {}),
    )


def rule_to_public_dict(rule: Rule) -> Dict[str, Any]:
    return {
        "id": rule.rule_id,
        "name": rule.name,
        "description": rule.description,
        "enabled": rule.enabled,
        "actions": rule.actions,
        "condition": rule.condition_payload,
        "status": "Active" if rule.enabled else "Paused",
        "mailbox_scope": rule.mailbox_scope,
        "mailbox_id": rule.mailbox_id,
        "scan_scope": rule.scan_scope,
        "match_mode": rule.match_mode,
        "priority": rule.priority,
        "stop_processing": rule.stop_processing,
        "is_sample": rule.is_sample,
        "execution_count": rule.execution_count,
        "last_executed": rule.last_executed.isoformat() if rule.last_executed else None,
    }


def load_persisted_rules(db: Any) -> List[Rule]:
    """Load enabled DB rules into executable Rule objects."""
    try:
        rows = db.fetch_all("SELECT * FROM rules WHERE is_active = 1 AND COALESCE(is_sample, 0) = 0 ORDER BY created_at ASC, id ASC")
    except Exception:
        return []

    rules: List[Rule] = []
    for row in rows:
        condition = parse_stored_value(row.get("condition"), {})
        action_payload = parse_stored_value(row.get("action"), [])
        rule = create_rule_from_dict({
            "id": row.get("id"),
            "name": row.get("name") or f"Rule {row.get('id')}",
            "condition": condition,
            "actions": action_payload,
            "enabled": bool(row.get("is_active", 1)),
            "description": row.get("description") or "",
            "mailbox_scope": row.get("mailbox_scope") or "all",
            "mailbox_id": row.get("mailbox_id"),
            "scan_scope": row.get("scan_scope") or "entire_email_with_attachments",
            "match_mode": row.get("match_mode") or "any",
            "priority": row.get("priority") or "Medium",
            "stop_processing": bool(row.get("stop_processing")),
            "is_sample": bool(row.get("is_sample")),
        })
        if rule.actions:
            rules.append(rule)
    return rules


def build_rule_engine(db: Any = None, include_defaults: bool = False) -> RuleEngine:
    engine = RuleEngine()
    if include_defaults:
        for rule_dict in DEFAULT_RULES:
            engine.add_rule(create_rule_from_dict(rule_dict))
    if db is not None:
        for rule in load_persisted_rules(db):
            engine.add_rule(rule)
    return engine


IMPORT_EXPORT_PRESET_RULES = [
    # ── Shipments & Logistics ─────────────────────────────────────────────────
    {
        "name": "IE: Incoming Shipment Alerts",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["shipped", "shipment dispatched", "consignment sent", "goods dispatched"]},
            {"type": "body_contains", "value": ["your shipment has been dispatched", "goods have been shipped"]},
        ]},
        "actions": [
            {"type": "add_label", "value": "Shipments"},
            {"type": "move_to_folder", "value": "Shipments"},
            {"type": "set_priority", "value": "Medium"},
            {"type": "flag", "value": True},
        ],
        "enabled": True,
        "description": "Catch incoming shipment dispatch notifications and route to Shipments folder",
    },
    {
        "name": "IE: Tracking Updates",
        "condition": {"type": "subject_contains", "value": ["tracking", "track your shipment", "delivery update", "in transit", "out for delivery", "package update"]},
        "actions": [
            {"type": "add_label", "value": "Shipments"},
            {"type": "mark_read", "value": True},
        ],
        "enabled": True,
        "description": "Label routine tracking update emails and mark as read",
    },
    {
        "name": "IE: Freight & Cargo Updates",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["freight", "air freight", "sea freight", "container loading", "cargo booking"]},
            {"type": "body_contains", "value": ["cargo booking confirmation", "container loaded", "freight booking"]},
        ]},
        "actions": [
            {"type": "add_label", "value": "Freight"},
            {"type": "move_to_folder", "value": "Freight"},
        ],
        "enabled": True,
        "description": "Route freight forwarder and cargo booking emails to Freight folder",
    },
    {
        "name": "IE: Port & Terminal Notices",
        "condition": {"type": "subject_contains", "value": ["port congestion", "terminal notice", "vessel arrival", "berth delay", "port update", "terminal advisory"]},
        "actions": [
            {"type": "add_label", "value": "Freight"},
            {"type": "move_to_folder", "value": "Freight"},
            {"type": "flag", "value": True},
        ],
        "enabled": True,
        "description": "Flag port and terminal advisory notices",
    },
    {
        "name": "IE: Delivery Confirmations",
        "condition": {"type": "subject_contains", "value": ["delivery confirmed", "goods received", "proof of delivery", "POD received", "warehouse receipt"]},
        "actions": [
            {"type": "add_label", "value": "Shipments"},
            {"type": "move_to_folder", "value": "Shipments"},
            {"type": "mark_read", "value": True},
        ],
        "enabled": True,
        "description": "File delivery confirmation and proof of delivery emails",
    },
    # ── Customs & Trade Compliance ────────────────────────────────────────────
    {
        "name": "IE: Customs Clearance Notices",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["customs clearance", "customs hold", "customs release", "duty assessment", "tariff", "import duty"]},
            {"type": "body_contains", "value": ["cleared through customs", "held at customs", "duty payment required"]},
        ]},
        "actions": [
            {"type": "add_label", "value": "Customs"},
            {"type": "move_to_folder", "value": "Customs"},
            {"type": "flag", "value": True},
            {"type": "set_priority", "value": "High"},
        ],
        "enabled": True,
        "description": "Flag customs holds and duty assessment emails with high priority",
    },
    {
        "name": "IE: Import Declarations & Entry Filing",
        "condition": {"type": "subject_contains", "value": ["import declaration", "entry filing", "bill of entry", "customs entry", "CBP entry", "ISF filing"]},
        "actions": [
            {"type": "add_label", "value": "Customs"},
            {"type": "move_to_folder", "value": "Customs"},
            {"type": "flag", "value": True},
        ],
        "enabled": True,
        "description": "File import declaration and entry submission emails in Customs folder",
    },
    {
        "name": "IE: Export Compliance & Licensing",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["export license", "export permit", "EAR", "ITAR", "denied party", "sanctions check", "embargo"]},
            {"type": "body_contains", "value": ["export license required", "subject to export controls", "restricted party screening"]},
        ]},
        "actions": [
            {"type": "add_label", "value": "Compliance"},
            {"type": "move_to_folder", "value": "Compliance"},
            {"type": "flag", "value": True},
            {"type": "set_priority", "value": "High"},
        ],
        "enabled": True,
        "description": "High-priority flag for export compliance, ITAR, EAR and sanctions emails",
    },
    {
        "name": "IE: Regulatory Inspections",
        "condition": {"type": "subject_contains", "value": ["FDA hold", "USDA inspection", "quarantine notice", "phytosanitary inspection", "fumigation required", "regulatory hold"]},
        "actions": [
            {"type": "add_label", "value": "Compliance"},
            {"type": "move_to_folder", "value": "Compliance"},
            {"type": "flag", "value": True},
            {"type": "set_priority", "value": "High"},
        ],
        "enabled": True,
        "description": "Flag FDA, USDA and regulatory inspection hold notices",
    },
    # ── Orders & Procurement ──────────────────────────────────────────────────
    {
        "name": "IE: Purchase Orders",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["purchase order", "PO #", "PO number", "order confirmation", "new order received"]},
            {"type": "body_contains", "value": ["please find attached purchase order", "we hereby place the following order"]},
        ]},
        "actions": [
            {"type": "add_label", "value": "Purchase-Orders"},
            {"type": "move_to_folder", "value": "Purchase-Orders"},
            {"type": "flag", "value": True},
        ],
        "enabled": True,
        "description": "Route incoming and outgoing purchase orders to Purchase-Orders folder",
    },
    {
        "name": "IE: RFQ & Price Requests",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["RFQ", "request for quotation", "request for quote", "price request", "quote request", "tender inquiry"]},
            {"type": "body_contains", "value": ["we would like to request a quotation", "kindly send your best price", "request for quotation"]},
        ]},
        "actions": [
            {"type": "add_label", "value": "RFQ"},
            {"type": "move_to_folder", "value": "RFQ"},
            {"type": "flag", "value": True},
            {"type": "set_priority", "value": "High"},
        ],
        "enabled": True,
        "description": "Flag all RFQ and price inquiry emails with high priority",
    },
    {
        "name": "IE: Supplier Price Lists & Quotes",
        "condition": {"type": "subject_contains", "value": ["price list", "price update", "revised pricing", "new price sheet", "rate card", "quotation valid", "our offer"]},
        "actions": [
            {"type": "add_label", "value": "Suppliers"},
            {"type": "move_to_folder", "value": "Suppliers"},
        ],
        "enabled": True,
        "description": "File incoming supplier price lists and quotations in Suppliers folder",
    },
    # ── Finance & Trade Documents ─────────────────────────────────────────────
    {
        "name": "IE: Commercial Invoices",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["commercial invoice", "proforma invoice", "final invoice", "invoice no", "invoice #"]},
            {"type": "body_contains", "value": ["please find attached invoice", "invoice is attached for your review", "proforma invoice attached"]},
        ]},
        "actions": [
            {"type": "add_label", "value": "Finance"},
            {"type": "move_to_folder", "value": "Finance"},
            {"type": "set_priority", "value": "High"},
        ],
        "enabled": True,
        "description": "Route all invoice emails to Finance folder with high priority",
    },
    {
        "name": "IE: Bill of Lading",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["bill of lading", "original BL", "BL copy", "telex release", "seaway bill", "express release"]},
            {"type": "body_contains", "value": ["bill of lading attached", "please find the B/L", "original bill of lading"]},
        ]},
        "actions": [
            {"type": "add_label", "value": "Documents"},
            {"type": "move_to_folder", "value": "Documents"},
            {"type": "flag", "value": True},
        ],
        "enabled": True,
        "description": "File all bill of lading and seaway bill documents",
    },
    {
        "name": "IE: Letter of Credit",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["letter of credit", "LC issued", "L/C issued", "documentary credit", "LC amendment", "LC discrepancy"]},
            {"type": "body_contains", "value": ["letter of credit has been opened", "documentary credit issued", "LC discrepancy noted"]},
        ]},
        "actions": [
            {"type": "add_label", "value": "Finance"},
            {"type": "move_to_folder", "value": "Finance"},
            {"type": "flag", "value": True},
            {"type": "set_priority", "value": "High"},
        ],
        "enabled": True,
        "description": "High-priority flag for all letter of credit and trade finance emails",
    },
    {
        "name": "IE: Payment Remittance",
        "condition": {"type": "subject_contains", "value": ["remittance advice", "wire transfer", "payment received", "TT payment", "SWIFT confirmation", "funds transferred"]},
        "actions": [
            {"type": "add_label", "value": "Finance"},
            {"type": "move_to_folder", "value": "Finance"},
            {"type": "mark_read", "value": True},
        ],
        "enabled": True,
        "description": "File payment remittance and wire transfer confirmations in Finance",
    },
    {
        "name": "IE: Shipping & Trade Documents",
        "condition": {"type": "subject_contains", "value": ["packing list", "certificate of origin", "fumigation certificate", "phytosanitary certificate", "health certificate", "inspection certificate", "COO"]},
        "actions": [
            {"type": "add_label", "value": "Documents"},
            {"type": "move_to_folder", "value": "Documents"},
        ],
        "enabled": True,
        "description": "File packing lists, certificates of origin and compliance certificates",
    },
    {
        "name": "IE: Marine Insurance",
        "condition": {"type": "subject_contains", "value": ["insurance certificate", "marine insurance", "cargo insurance", "insurance policy", "insurance declaration", "open cover"]},
        "actions": [
            {"type": "add_label", "value": "Documents"},
            {"type": "move_to_folder", "value": "Documents"},
        ],
        "enabled": True,
        "description": "File marine and cargo insurance documents",
    },
    # ── Alerts & Urgent Matters ───────────────────────────────────────────────
    {
        "name": "IE: Shipment Delays",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["delay", "delayed shipment", "vessel delay", "flight delay", "rescheduled departure", "ETA change", "revised ETA"]},
            {"type": "body_contains", "value": ["shipment has been delayed", "delay in delivery", "new estimated arrival"]},
        ]},
        "actions": [
            {"type": "flag", "value": True},
            {"type": "set_priority", "value": "High"},
            {"type": "add_label", "value": "Urgent"},
        ],
        "enabled": True,
        "description": "Flag all shipment delay notifications with high priority",
    },
    {
        "name": "IE: Demurrage & Detention",
        "condition": {"type": "subject_contains", "value": ["demurrage", "detention charges", "storage charges", "free time expired", "container detention", "laytime exceeded"]},
        "actions": [
            {"type": "flag", "value": True},
            {"type": "set_priority", "value": "High"},
            {"type": "add_label", "value": "Urgent"},
            {"type": "move_to_folder", "value": "Customs"},
        ],
        "enabled": True,
        "description": "Urgent flag for demurrage and detention charge notices — time-sensitive costs",
    },
    {
        "name": "IE: Document Discrepancies",
        "condition": {"type": "or", "value": [
            {"type": "subject_contains", "value": ["missing documents", "document discrepancy", "rejected documents", "document correction", "amendment required", "documents not in order"]},
            {"type": "body_contains", "value": ["documents are not in order", "discrepancy found in", "documents rejected by bank"]},
        ]},
        "actions": [
            {"type": "flag", "value": True},
            {"type": "set_priority", "value": "High"},
            {"type": "add_label", "value": "Urgent"},
        ],
        "enabled": True,
        "description": "Flag missing or rejected document alerts requiring immediate action",
    },
    # ── Customer Relations ────────────────────────────────────────────────────
    {
        "name": "IE: Customer Order Inquiries",
        "condition": {"type": "subject_contains", "value": ["order status", "where is my order", "delivery status", "shipment status update", "order inquiry", "order tracking"]},
        "actions": [
            {"type": "add_label", "value": "Customers"},
            {"type": "move_to_folder", "value": "Customers"},
            {"type": "set_priority", "value": "Medium"},
        ],
        "enabled": True,
        "description": "Route customer order status and shipment inquiry emails",
    },
]

BUSINESS_PRESET_PACKS = {
    "marketing": {
        "name": "Marketing Rules Pack",
        "description": "Pre-built rules for campaign, launch, webinar, content and brand-marketing emails.",
        "folders": ["Marketing"],
        "tags": ["marketing", "campaigns", "brand"],
        "rules": [
            {
                "name": "Marketing: Campaign and launch updates",
                "condition": {"type": "or", "value": [
                    {"type": "subject_contains", "value": ["campaign", "product launch", "webinar", "case study", "press release"]},
                    {"type": "body_contains", "value": ["marketing campaign", "content calendar", "brand campaign"]},
                ]},
                "actions": [
                    {"type": "set_category", "value": "Marketing"},
                    {"type": "add_label", "value": "Marketing"},
                    {"type": "move_to_folder", "value": "Marketing"},
                    {"type": "set_priority", "value": "Medium"},
                ],
                "enabled": True,
                "description": "Route campaign and launch communications into Marketing.",
            }
        ],
    },
    "sales": {
        "name": "Sales Rules Pack",
        "description": "Pre-built rules for demos, pricing, proposals, quotes and purchase-intent emails.",
        "folders": ["Sales"],
        "tags": ["sales", "pipeline", "deals"],
        "rules": [
            {
                "name": "Sales: Demo pricing and proposal requests",
                "condition": {"type": "or", "value": [
                    {"type": "subject_contains", "value": ["demo request", "pricing request", "quote request", "sales proposal", "purchase intent"]},
                    {"type": "body_contains", "value": ["book a demo", "send pricing", "request for proposal", "interested in your product"]},
                ]},
                "actions": [
                    {"type": "set_category", "value": "Sales"},
                    {"type": "add_label", "value": "Sales"},
                    {"type": "move_to_folder", "value": "Sales"},
                    {"type": "set_priority", "value": "High"},
                    {"type": "flag", "value": True},
                ],
                "enabled": True,
                "description": "Keep sales opportunities visible and high priority.",
            }
        ],
    },
    "social-media": {
        "name": "Social Media Rules Pack",
        "description": "Pre-built rules for mentions, comments, followers and social-platform notifications.",
        "folders": ["Social Media"],
        "tags": ["social-media", "social", "community"],
        "rules": [
            {
                "name": "Social Media: Mentions comments and followers",
                "condition": {"type": "or", "value": [
                    {"type": "subject_contains", "value": ["new follower", "mentioned you", "new comment", "direct message"]},
                    {"type": "body_contains", "value": ["linkedin", "instagram", "facebook", "twitter", "youtube"]},
                ]},
                "actions": [
                    {"type": "set_category", "value": "Social Media"},
                    {"type": "add_label", "value": "Social Media"},
                    {"type": "move_to_folder", "value": "Social Media"},
                    {"type": "set_priority", "value": "Low"},
                ],
                "enabled": True,
                "description": "Collect social media activity outside the main inbox.",
            }
        ],
    },
    "investor": {
        "name": "Investor Rules Pack",
        "description": "Pre-built rules for investor updates, term sheets, pitch decks and diligence requests.",
        "folders": ["Investor"],
        "tags": ["investor", "funding", "finance"],
        "rules": [
            {
                "name": "Investor: Funding and diligence workflow",
                "condition": {"type": "or", "value": [
                    {"type": "subject_contains", "value": ["investor update", "funding round", "term sheet", "pitch deck", "cap table"]},
                    {"type": "body_contains", "value": ["due diligence", "investment committee", "fundraising update"]},
                ]},
                "actions": [
                    {"type": "set_category", "value": "Investor"},
                    {"type": "add_label", "value": "Investor"},
                    {"type": "move_to_folder", "value": "Investor"},
                    {"type": "set_priority", "value": "High"},
                    {"type": "flag", "value": True},
                ],
                "enabled": True,
                "description": "Escalate investor and funding communications.",
            }
        ],
    },
    "support": {
        "name": "Support Rules Pack",
        "description": "Pre-built rules for tickets, support requests, issues, complaints and escalations.",
        "folders": ["Support"],
        "tags": ["support", "tickets", "customers"],
        "rules": [
            {
                "name": "Support: Tickets issues and complaints",
                "condition": {"type": "or", "value": [
                    {"type": "subject_contains", "value": ["support request", "ticket", "not working", "complaint", "issue"]},
                    {"type": "body_contains", "value": ["need help", "technical issue", "customer complaint", "please assist"]},
                ]},
                "actions": [
                    {"type": "set_category", "value": "Support"},
                    {"type": "add_label", "value": "Support"},
                    {"type": "move_to_folder", "value": "Support"},
                    {"type": "set_priority", "value": "High"},
                    {"type": "flag", "value": True},
                ],
                "enabled": True,
                "description": "Route customer problems to Support with high priority.",
            }
        ],
    },
    "leads": {
        "name": "Leads Rules Pack",
        "description": "Pre-built rules for contact forms, inbound leads, website inquiries and demo interest.",
        "folders": ["Leads"],
        "tags": ["leads", "inbound", "crm"],
        "rules": [
            {
                "name": "Leads: Contact forms and inbound interest",
                "condition": {"type": "or", "value": [
                    {"type": "subject_contains", "value": ["new lead", "inbound lead", "contact form", "website inquiry"]},
                    {"type": "body_contains", "value": ["request demo", "interested in", "please contact me", "learn more about"]},
                ]},
                "actions": [
                    {"type": "set_category", "value": "Leads"},
                    {"type": "add_label", "value": "Leads"},
                    {"type": "move_to_folder", "value": "Leads"},
                    {"type": "set_priority", "value": "High"},
                    {"type": "flag", "value": True},
                ],
                "enabled": True,
                "description": "Capture and prioritize inbound leads.",
            }
        ],
    },
}

for _pack in BUSINESS_PRESET_PACKS.values():
    _pack["rule_count"] = len(_pack["rules"])

RULE_PRESET_PACKS = {
    "import-export": {
        "name": "Import & Export Business Pack",
        "description": "22 pre-built rules covering shipments, customs clearance, trade finance, compliance, RFQs, and document management for import/export companies.",
        "rule_count": len(IMPORT_EXPORT_PRESET_RULES),
        "rules": IMPORT_EXPORT_PRESET_RULES,
        "folders": ["Shipments", "Freight", "Customs", "Compliance", "Purchase-Orders", "RFQ", "Suppliers", "Finance", "Documents", "Customers", "Urgent"],
        "tags": ["import", "export", "trade", "logistics", "customs", "freight"],
    },
    **BUSINESS_PRESET_PACKS,
}

DEFAULT_RULES = [
    {
        "name": "Quarantine suspected scams",
        "condition": {"type": "category_is", "value": ["Scam"]},
        "actions": [
            {"type": "set_category", "value": "Scam"},
            {"type": "add_label", "value": "Scam"},
            {"type": "move_to_folder", "value": "Scam"},
            {"type": "set_priority", "value": "Critical"},
            {"type": "flag", "value": True},
        ],
        "enabled": True,
        "description": "Quarantine emails classified or manually marked as scams",
    },
    {
        "name": "Move invoices to Finance",
        "condition": {"type": "subject_contains", "value": ["invoice", "bill", "payment"]},
        "actions": [
            {"type": "set_category", "value": "Finance"},
            {"type": "add_label", "value": "Finance"},
            {"type": "move_to_folder", "value": "Finance"},
            {"type": "mark_read", "value": True},
        ],
        "enabled": True,
        "description": "Automatically categorize invoice emails into Finance",
    },
    {
        "name": "Move OTPs to security",
        "condition": {"type": "subject_contains", "value": ["verification code", "otp", "security code"]},
        "actions": [
            {"type": "set_category", "value": "OTP"},
            {"type": "add_label", "value": "Security"},
            {"type": "move_to_folder", "value": "Security"},
            {"type": "mark_read", "value": True},
        ],
        "enabled": True,
        "description": "Automatically categorize OTP/security emails",
    },
    {
        "name": "Archive old newsletters",
        "condition": {
            "type": "and",
            "value": [
                {"type": "category_is", "value": ["Newsletters"]},
                {"type": "age_greater_than", "value": ["30"]},
            ],
        },
        "actions": [{"type": "archive", "value": True}],
        "enabled": False,
        "description": "Archive newsletters older than 30 days",
    },
    {
        "name": "Flag urgent emails",
        "condition": {"type": "subject_contains", "value": ["urgent", "asap", "critical", "emergency"]},
        "actions": [
            {"type": "set_priority", "value": "High"},
            {"type": "add_label", "value": "Urgent"},
            {"type": "flag", "value": True},
        ],
        "enabled": True,
        "description": "Flag urgent emails",
    },
]
