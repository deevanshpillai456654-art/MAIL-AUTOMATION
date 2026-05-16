"""Guards for sync-first, reuse-first mailbox infrastructure generation."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Tuple


SYSTEM_PREFIX_RE = re.compile(r"^(?:ai|smart|auto|system|intemo)[\s_.:-]+", re.I)
NON_KEY_RE = re.compile(r"[^a-z0-9]+", re.I)
EMAIL_RE = re.compile(r"[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+")


def strip_system_prefix(value: Any) -> str:
    text = str(value or "").strip()
    previous = None
    while text and text != previous:
        previous = text
        text = SYSTEM_PREFIX_RE.sub("", text).strip()
    return text


def display_bucket_name(value: Any, fallback: str = "General") -> str:
    text = strip_system_prefix(value)
    text = re.sub(r"[\s_:-]+", " ", text).strip()
    return (text or fallback)[:80]


def canonical_bucket_key(value: Any) -> str:
    text = display_bucket_name(value, "").lower()
    key = NON_KEY_RE.sub("", text)
    aliases = {
        "lead": "leads",
        "client": "clients",
        "customer": "clients",
        "customers": "clients",
        "sale": "sales",
        "supportdesk": "support",
        "helpdesk": "support",
        "accounting": "finance",
        "invoice": "finance",
        "invoices": "finance",
    }
    return aliases.get(key, key)


def bucket_name_from_provider_item(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ""
    return (
        item.get("name")
        or item.get("displayName")
        or item.get("display_name")
        or item.get("label")
        or item.get("category")
        or ""
    )


def parse_jsonish(value: Any, default: Any = None) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value if value is not None else default


def recipient_list(value: Any) -> List[str]:
    value = parse_jsonish(value, value)
    if isinstance(value, dict):
        candidates = value.get("to") or value.get("recipients") or value.get("recipient") or value.get("email") or []
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = [value]

    output: List[str] = []
    for item in candidates:
        if isinstance(item, dict):
            item = (
                item.get("email")
                or item.get("address")
                or (item.get("emailAddress") or {}).get("address")
                or item.get("to")
                or ""
            )
        for match in EMAIL_RE.findall(str(item or "").lower()):
            if match not in output:
                output.append(match)
    return output


def recipients_signature(value: Any) -> str:
    return ",".join(sorted(recipient_list(value)))


def canonical_condition_payload(condition: Any) -> Any:
    from backend.rules.engine import normalize_condition_dict

    parsed = parse_jsonish(condition, {})
    if isinstance(parsed, str):
        return {"type": "raw", "value": parsed.strip().lower()}
    if not isinstance(parsed, dict):
        return {"type": "never", "value": []}
    normalized = normalize_condition_dict(parsed)
    value = normalized.get("value", [])
    if not isinstance(value, list):
        value = [value]
    normalized["value"] = sorted(str(item).strip().lower() for item in value if str(item).strip())
    return normalized


def canonical_actions_payload(actions: Any) -> List[Dict[str, Any]]:
    from backend.rules.engine import RuleAction, normalize_actions

    output: List[Dict[str, Any]] = []
    for action in normalize_actions(actions):
        action_type = action.get("type")
        value = action.get("value")
        if action_type in {
            RuleAction.MOVE_TO_FOLDER.value,
            RuleAction.ADD_LABEL.value,
            RuleAction.ADD_CATEGORY.value,
            RuleAction.SET_CATEGORY.value,
        }:
            value = display_bucket_name(value)
        elif action_type == RuleAction.FORWARD_EMAIL.value:
            payload = parse_jsonish(value, {})
            recipients = recipient_list(payload)
            if isinstance(payload, dict):
                value = {
                    **payload,
                    "to": recipients,
                    "cc": recipient_list(payload.get("cc")),
                    "bcc": recipient_list(payload.get("bcc")),
                }
            else:
                value = {"to": recipients, "cc": [], "bcc": []}
        output.append({"type": action_type, "value": value})
    return sorted(output, key=lambda item: json.dumps(item, sort_keys=True))


def rule_signature(condition: Any, actions: Any) -> str:
    payload = {
        "condition": canonical_condition_payload(condition),
        "actions": canonical_actions_payload(actions),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def canonical_rule_values(condition: Any, actions: Any) -> Tuple[str, str, str]:
    condition_payload = canonical_condition_payload(condition)
    action_payload = canonical_actions_payload(actions)
    return (
        json.dumps(condition_payload, sort_keys=True),
        json.dumps(action_payload, sort_keys=True),
        rule_signature(condition_payload, action_payload),
    )


def forwarding_actions(actions: Any) -> List[Dict[str, Any]]:
    from backend.rules.engine import RuleAction

    return [
        action
        for action in canonical_actions_payload(actions)
        if action.get("type") == RuleAction.FORWARD_EMAIL.value
    ]


def forwarding_condition_signature(condition: Any) -> str:
    return json.dumps(canonical_condition_payload(condition), sort_keys=True, separators=(",", ":"))
