"""
Durable local/provider rule-action executor.

Rules are applied local-first so labels/folders are visible immediately in the
app, then a best-effort provider operation is attempted when Gmail/Outlook/IMAP
write access is available. Provider failures do not roll back local state; they
are stored in rule_action_audit and emails.provider_action_error for retry and
support diagnostics.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.rules.engine import RuleAction, build_rule_engine, normalize_actions

_log = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"[^\w\s.\-/@]+", re.UNICODE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_bucket_name(value: Any, fallback: str = "General") -> str:
    text = str(value if value is not None else fallback).strip()
    if not text:
        text = fallback
    text = _SAFE_NAME_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" ./")
    return (text or fallback)[:80]


def parse_labels(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [normalize_bucket_name(item) for item in raw if normalize_bucket_name(item)]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [normalize_bucket_name(item) for item in parsed if normalize_bucket_name(item)]
        except json.JSONDecodeError:
            pass
        return [normalize_bucket_name(part) for part in text.split(",") if normalize_bucket_name(part)]
    return []


class ProviderActionResult(dict):
    @classmethod
    def ok(cls, detail: str = "provider action applied", data: Optional[Dict] = None) -> "ProviderActionResult":
        payload = cls(success=True, detail=detail)
        if data:
            payload.update(data)
        return payload

    @classmethod
    def skipped(cls, detail: str) -> "ProviderActionResult":
        return cls(success=False, skipped=True, detail=detail)

    @classmethod
    def failed(cls, detail: str) -> "ProviderActionResult":
        return cls(success=False, skipped=False, detail=detail)


class NoProviderActionAdapter:
    def apply(self, email: Dict, action_type: str, value: Any) -> ProviderActionResult:
        return ProviderActionResult.skipped("provider write adapter not configured")


class GmailProviderActionAdapter:
    API_BASE = "https://gmail.googleapis.com/gmail/v1"

    def __init__(self, account_id: int, db: Any):
        self.account_id = account_id
        self.db = db
        self._labels: Optional[Dict[str, str]] = None
        from backend.auth.gmail_auth import GmailOAuth
        self.access_token = GmailOAuth(db=db).get_valid_token(account_id)
        self.headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"} if self.access_token else {}

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        if not self.access_token:
            raise RuntimeError("Gmail write token unavailable; reconnect account with Mail modify scope")
        import requests
        response = requests.request(method, f"{self.API_BASE}{endpoint}", headers=self.headers, timeout=30, **kwargs)
        if not response.ok:
            raise RuntimeError(f"Gmail API {response.status_code}: {(response.text or response.reason)[:300]}")
        return response.json() if response.content else {}

    def _load_labels(self) -> Dict[str, str]:
        if self._labels is None:
            result = self._request("GET", "/users/me/labels")
            self._labels = {str(item.get("name", "")).lower(): item.get("id") for item in result.get("labels", []) if item.get("id")}
        return self._labels

    def ensure_label(self, name: str) -> str:
        label_name = normalize_bucket_name(name)
        labels = self._load_labels()
        existing = labels.get(label_name.lower())
        if existing:
            return existing
        created = self._request(
            "POST",
            "/users/me/labels",
            json={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        )
        label_id = created.get("id")
        if not label_id:
            raise RuntimeError(f"Gmail did not return an id while creating label {label_name}")
        labels[label_name.lower()] = label_id
        return label_id

    def apply(self, email: Dict, action_type: str, value: Any) -> ProviderActionResult:
        message_id = email.get("message_id")
        if not message_id:
            return ProviderActionResult.skipped("email has no Gmail message id")
        try:
            if action_type in (RuleAction.ADD_LABEL.value, RuleAction.ADD_CATEGORY.value, RuleAction.SET_CATEGORY.value):
                label = normalize_bucket_name(value)
                label_id = self.ensure_label(label)
                self._request("POST", f"/users/me/messages/{message_id}/modify", json={"addLabelIds": [label_id]})
                return ProviderActionResult.ok(f"Gmail label applied: {label}", {"provider_label_id": label_id})
            if action_type == RuleAction.MOVE_TO_FOLDER.value:
                label = normalize_bucket_name(value)
                label_id = self.ensure_label(label)
                self._request("POST", f"/users/me/messages/{message_id}/modify", json={"addLabelIds": [label_id], "removeLabelIds": ["INBOX"]})
                return ProviderActionResult.ok(f"Gmail moved to label: {label}", {"provider_label_id": label_id})
            if action_type == RuleAction.MARK_READ.value:
                self._request("POST", f"/users/me/messages/{message_id}/modify", json={"removeLabelIds": ["UNREAD"]})
                return ProviderActionResult.ok("Gmail marked read")
            if action_type == RuleAction.MARK_UNREAD.value:
                self._request("POST", f"/users/me/messages/{message_id}/modify", json={"addLabelIds": ["UNREAD"]})
                return ProviderActionResult.ok("Gmail marked unread")
            if action_type == RuleAction.ARCHIVE.value:
                self._request("POST", f"/users/me/messages/{message_id}/modify", json={"removeLabelIds": ["INBOX"]})
                return ProviderActionResult.ok("Gmail archived")
            if action_type == RuleAction.FLAG.value:
                self._request("POST", f"/users/me/messages/{message_id}/modify", json={"addLabelIds": ["STARRED"]})
                return ProviderActionResult.ok("Gmail starred")
            return ProviderActionResult.skipped(f"Gmail action not supported: {action_type}")
        except Exception as exc:
            return ProviderActionResult.failed(str(exc))


class OutlookProviderActionAdapter:
    API_BASE = "https://graph.microsoft.com/v1.0"

    def __init__(self, account_id: int, db: Any):
        self.account_id = account_id
        self.db = db
        self._folders: Optional[Dict[str, str]] = None
        self._categories: Optional[Dict[str, str]] = None
        from backend.auth.outlook_auth import OutlookOAuth
        self.access_token = OutlookOAuth(db=db).get_valid_token(account_id)
        self.headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"} if self.access_token else {}

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict:
        if not self.access_token:
            raise RuntimeError("Microsoft Graph write token unavailable; reconnect account with Mail.ReadWrite scope")
        import requests
        response = requests.request(method, f"{self.API_BASE}{endpoint}", headers=self.headers, timeout=30, **kwargs)
        if not response.ok:
            raise RuntimeError(f"Microsoft Graph {response.status_code}: {(response.text or response.reason)[:300]}")
        return response.json() if response.content else {}

    def _load_folders(self) -> Dict[str, str]:
        if self._folders is None:
            result = self._request("GET", "/me/mailFolders?$top=100")
            self._folders = {str(item.get("displayName", "")).lower(): item.get("id") for item in result.get("value", []) if item.get("id")}
        return self._folders

    def _load_categories(self) -> Dict[str, str]:
        if self._categories is None:
            result = self._request("GET", "/me/outlook/masterCategories")
            self._categories = {str(item.get("displayName", "")).lower(): item.get("id") or item.get("displayName") for item in result.get("value", [])}
        return self._categories

    def ensure_folder(self, name: str) -> str:
        folder_name = normalize_bucket_name(name)
        folders = self._load_folders()
        existing = folders.get(folder_name.lower())
        if existing:
            return existing
        created = self._request("POST", "/me/mailFolders", json={"displayName": folder_name})
        folder_id = created.get("id")
        if not folder_id:
            raise RuntimeError(f"Outlook did not return an id while creating folder {folder_name}")
        folders[folder_name.lower()] = folder_id
        return folder_id

    def ensure_category(self, name: str) -> str:
        category_name = normalize_bucket_name(name)
        categories = self._load_categories()
        existing = categories.get(category_name.lower())
        if existing:
            return existing
        created = self._request("POST", "/me/outlook/masterCategories", json={"displayName": category_name, "color": "preset0"})
        category_id = created.get("id") or created.get("displayName") or category_name
        categories[category_name.lower()] = category_id
        return category_id

    def apply(self, email: Dict, action_type: str, value: Any) -> ProviderActionResult:
        message_id = email.get("message_id")
        if not message_id:
            return ProviderActionResult.skipped("email has no Outlook message id")
        try:
            if action_type in (RuleAction.ADD_LABEL.value, RuleAction.ADD_CATEGORY.value, RuleAction.SET_CATEGORY.value):
                category = normalize_bucket_name(value)
                self.ensure_category(category)
                current = parse_labels(email.get("labels"))
                if category not in current:
                    current.append(category)
                self._request("PATCH", f"/me/messages/{message_id}", json={"categories": current})
                return ProviderActionResult.ok(f"Outlook category applied: {category}")
            if action_type == RuleAction.MOVE_TO_FOLDER.value:
                folder = normalize_bucket_name(value)
                folder_id = self.ensure_folder(folder)
                self._request("POST", f"/me/messages/{message_id}/move", json={"destinationId": folder_id})
                return ProviderActionResult.ok(f"Outlook moved to folder: {folder}", {"provider_folder_id": folder_id})
            if action_type == RuleAction.MARK_READ.value:
                self._request("PATCH", f"/me/messages/{message_id}", json={"isRead": True})
                return ProviderActionResult.ok("Outlook marked read")
            if action_type == RuleAction.MARK_UNREAD.value:
                self._request("PATCH", f"/me/messages/{message_id}", json={"isRead": False})
                return ProviderActionResult.ok("Outlook marked unread")
            if action_type == RuleAction.FLAG.value:
                self._request("PATCH", f"/me/messages/{message_id}", json={"flag": {"flagStatus": "flagged"}})
                return ProviderActionResult.ok("Outlook flagged")
            return ProviderActionResult.skipped(f"Outlook action not supported: {action_type}")
        except Exception as exc:
            return ProviderActionResult.failed(str(exc))


class IMAPProviderActionAdapter:
    def __init__(self, account_id: int, db: Any):
        self.account_id = account_id
        self.db = db

    def apply(self, email: Dict, action_type: str, value: Any) -> ProviderActionResult:
        # IMAP message movement requires provider UID mapping.  The app stores the
        # local folder immediately and exposes this as pending provider sync when
        # no UID is available.  UID-aware movement can be added later without
        # changing rule semantics.
        if action_type in (RuleAction.MOVE_TO_FOLDER.value, RuleAction.ADD_LABEL.value, RuleAction.ADD_CATEGORY.value, RuleAction.SET_CATEGORY.value):
            return ProviderActionResult.skipped("IMAP provider movement queued locally; UID mapping unavailable for remote write")
        return ProviderActionResult.skipped(f"IMAP action not supported: {action_type}")


def get_provider_adapter(account: Optional[Dict], db: Any, enable_provider_write: bool = True):
    if not enable_provider_write or not account:
        return NoProviderActionAdapter()
    provider = str(account.get("provider") or "").lower()
    try:
        if provider == "gmail":
            return GmailProviderActionAdapter(account["id"], db)
        if provider in {"outlook", "microsoft", "office365", "exchange"}:
            return OutlookProviderActionAdapter(account["id"], db)
        if provider in {"imap", "yahoo", "zoho", "rediffmail"}:
            return IMAPProviderActionAdapter(account["id"], db)
    except Exception as exc:
        _log.debug("Provider action adapter unavailable for account %s: %s", account.get("id") if account else None, exc)
    return NoProviderActionAdapter()


class RuleActionExecutor:
    def __init__(self, db: Any, enable_provider_write: bool = True):
        self.db = db
        self.enable_provider_write = enable_provider_write

    def _email_account(self, email: Dict) -> Optional[Dict]:
        account_id = email.get("account_id")
        if not account_id:
            return None
        try:
            return self.db.get_account_by_id(account_id)
        except Exception:
            return None

    def _log(self, email_id: int, rule_name: str, action_type: str, value: Any, local_success: bool, provider_result: Dict):
        try:
            self.db.log_rule_action(
                email_id=email_id,
                rule_name=rule_name,
                action_type=action_type,
                action_value=value,
                local_success=local_success,
                provider_success=bool(provider_result.get("success")),
                provider_status=provider_result.get("detail"),
            )
        except Exception as exc:
            _log.debug("Unable to log rule action: %s", exc)

    def apply_action(self, email: Dict, rule_name: str, action: Dict, provider_adapter: Any) -> Dict:
        action_type = action.get("type")
        value = action.get("value")
        email_id = email.get("id")
        local_success = False
        local_detail = ""
        provider_result = None

        if not email_id:
            return {"action": action_type, "value": value, "success": False, "details": "email id missing"}

        try:
            if action_type in (RuleAction.ADD_LABEL.value, RuleAction.ADD_CATEGORY.value):
                label = self.db.resolve_mail_label_name(email.get("account_id"), value) if hasattr(self.db, "resolve_mail_label_name") else normalize_bucket_name(value)
                self.db.ensure_mail_label(email.get("account_id"), label)
                self.db.add_email_label(email_id, label)
                email["labels"] = json.dumps(sorted(set(parse_labels(email.get("labels")) + [label])))
                local_success = True
                local_detail = f"label created/applied locally: {label}"
            elif action_type == RuleAction.MOVE_TO_FOLDER.value:
                folder = self.db.resolve_mail_folder_name(email.get("account_id"), value) if hasattr(self.db, "resolve_mail_folder_name") else normalize_bucket_name(value)
                self.db.ensure_mail_folder(email.get("account_id"), folder)
                self.db.set_email_folder(email_id, folder)
                # Moving also applies the same named label/category for easy UI filtering.
                self.db.ensure_mail_label(email.get("account_id"), folder)
                self.db.add_email_label(email_id, folder)
                email["folder"] = folder
                email["labels"] = json.dumps(sorted(set(parse_labels(email.get("labels")) + [folder])))
                local_success = True
                local_detail = f"folder created and email moved locally: {folder}"
            elif action_type == RuleAction.SET_CATEGORY.value:
                category = self.db.resolve_mail_label_name(email.get("account_id"), value) if hasattr(self.db, "resolve_mail_label_name") else normalize_bucket_name(value)
                self.db.update_email_category(email_id, category, 0.98)
                self.db.ensure_mail_label(email.get("account_id"), category)
                self.db.add_email_label(email_id, category)
                self.db.ensure_mail_folder(email.get("account_id"), category)
                email["category"] = category
                email["labels"] = json.dumps(sorted(set(parse_labels(email.get("labels")) + [category])))
                local_success = True
                local_detail = f"category/label/folder ensured locally: {category}"
            elif action_type == RuleAction.MARK_READ.value:
                self.db.execute("UPDATE emails SET is_read = 1 WHERE id = ?", (email_id,))
                email["is_read"] = 1
                local_success = True
                local_detail = "email marked read locally"
            elif action_type == RuleAction.MARK_UNREAD.value:
                self.db.execute("UPDATE emails SET is_read = 0 WHERE id = ?", (email_id,))
                email["is_read"] = 0
                local_success = True
                local_detail = "email marked unread locally"
            elif action_type == RuleAction.SET_PRIORITY.value:
                priority = normalize_bucket_name(value, "Medium")
                self.db.execute("UPDATE emails SET priority = ? WHERE id = ?", (priority, email_id))
                email["priority"] = priority
                local_success = True
                local_detail = f"priority set locally: {priority}"
            elif action_type == RuleAction.ARCHIVE.value:
                self.db.set_email_folder(email_id, "Archive")
                email["folder"] = "Archive"
                local_success = True
                local_detail = "email archived locally"
            elif action_type == RuleAction.DELETE.value:
                self.db.set_email_folder(email_id, "Trash")
                email["folder"] = "Trash"
                local_success = True
                local_detail = "email moved to Trash locally"
            elif action_type == RuleAction.FLAG.value:
                self.db.add_email_label(email_id, "Flagged")
                email["labels"] = json.dumps(sorted(set(parse_labels(email.get("labels")) + ["Flagged"])))
                local_success = True
                local_detail = "email flagged locally"
            elif action_type == RuleAction.FORWARD_EMAIL.value:
                from backend.core.email_forwarding import UniversalEmailForwarder
                forward_result = UniversalEmailForwarder(self.db, enable_provider_write=self.enable_provider_write).forward_email(email, value, rule_name=rule_name)
                local_success = bool(forward_result.get("local_success"))
                local_detail = forward_result.get("detail") or "email forward action recorded"
                provider_payload = forward_result.get("provider") or {}
                provider_result = ProviderActionResult(
                    success=bool(provider_payload.get("success")),
                    skipped=bool(provider_payload.get("skipped")),
                    detail=provider_payload.get("detail") or local_detail,
                )
                provider_result.update({k: v for k, v in provider_payload.items() if k not in provider_result})
            elif action_type == RuleAction.NOTIFY.value:
                local_success = True
                local_detail = "notification action recorded"
            else:
                local_detail = f"unsupported action: {action_type}"
        except Exception as exc:
            local_detail = f"local action failed: {exc}"

        if provider_result is None:
            provider_result = ProviderActionResult.skipped("provider not attempted")
            if local_success and self.enable_provider_write:
                provider_result = provider_adapter.apply(email, action_type, value)

        try:
            status = "synced" if provider_result.get("success") else ("local_only" if provider_result.get("skipped") else "provider_failed")
            self.db.execute(
                "UPDATE emails SET rule_status = ?, rule_applied_at = ?, provider_action_error = ? WHERE id = ?",
                (status, utc_now(), None if provider_result.get("success") or provider_result.get("skipped") else provider_result.get("detail"), email_id),
            )
        except Exception:
            pass

        self._log(email_id, rule_name, action_type, value, local_success, provider_result)
        return {
            "action": action_type,
            "value": value,
            "success": local_success,
            "details": local_detail,
            "provider": dict(provider_result),
        }

    def apply_rules_to_email(self, email: Dict, provider_adapter: Any = None) -> Dict:
        account = self._email_account(email)
        adapter = provider_adapter or get_provider_adapter(account, self.db, self.enable_provider_write)
        engine = build_rule_engine(self.db, include_defaults=True)
        matched: List[Dict] = []

        for rule in engine.rules:
            if not rule.match(email):
                continue
            actions = normalize_actions(rule.actions)
            action_results = [self.apply_action(email, rule.name, action, adapter) for action in actions]
            rule.execution_count += 1
            rule.last_executed = datetime.now()
            matched.append({
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "matched": True,
                "actions": action_results,
                "email_id": email.get("id"),
                "timestamp": utc_now(),
            })

        return {"email_id": email.get("id"), "matched_rules": matched, "count": len(matched)}

    def apply_rules_to_email_id(self, email_id: int, provider_adapter: Any = None) -> Dict:
        email = self.db.fetch_one("SELECT * FROM emails WHERE id = ?", (email_id,))
        if not email:
            return {"email_id": email_id, "matched_rules": [], "count": 0, "error": "email not found"}
        return self.apply_rules_to_email(email, provider_adapter=provider_adapter)

    def apply_rules_to_existing_emails(self, limit: int = 1000, category: str = None, provider_write: Optional[bool] = None) -> Dict:
        if provider_write is not None:
            old = self.enable_provider_write
            self.enable_provider_write = provider_write
        else:
            old = self.enable_provider_write
        try:
            if category:
                emails = self.db.fetch_all("SELECT * FROM emails WHERE category = ? ORDER BY created_at DESC LIMIT ?", (category, limit))
            else:
                emails = self.db.fetch_all("SELECT * FROM emails ORDER BY created_at DESC LIMIT ?", (limit,))
            results = [self.apply_rules_to_email(email) for email in emails]
            matched = sum(item.get("count", 0) for item in results)
            return {"status": "success", "emails_checked": len(emails), "matched_rules": matched, "results": results[-25:]}
        finally:
            self.enable_provider_write = old
