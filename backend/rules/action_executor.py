"""
Durable local/provider rule-action executor.

Rules are applied local-first so labels/folders are visible immediately in the
app, then a best-effort provider operation is attempted when Gmail/Outlook/IMAP
write access is available. Provider failures do not roll back local state; they
are stored in rule_action_audit and emails.provider_action_error for retry and
support diagnostics.
"""

from __future__ import annotations

import imaplib
import json
import logging
import re
import socket
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.rules.engine import (
    RuleAction,
    build_rule_engine,
    create_rule_from_dict,
    normalize_actions,
    parse_stored_value,
)
from backend.rules.scanner import enrich_email_for_rules, match_condition_payload

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
        account = db.get_account_by_id(account_id) if hasattr(db, "get_account_by_id") else None
        self.access_token = GmailOAuth(db=db, email_address=(account or {}).get("email")).get_valid_token(account_id)
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
        account = db.get_account_by_id(account_id) if hasattr(db, "get_account_by_id") else None
        self.access_token = OutlookOAuth(db=db, email_address=(account or {}).get("email")).get_valid_token(account_id)
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

    def _connect(self):
        from backend.auth.imap_auth import IMAPAccountManager
        account = self.db.get_account_by_id(self.account_id)
        if not account:
            raise RuntimeError("IMAP mailbox not found")
        try:
            metadata = json.loads(account.get("metadata") or "{}")
        except Exception:
            metadata = {}
        host = metadata.get("host") or metadata.get("imap_host")
        port = int(metadata.get("port") or metadata.get("imap_port") or 993)
        security = str(metadata.get("security") or "ssl").lower()
        password = IMAPAccountManager(self.db).get_password(account)
        if not host or not password:
            raise RuntimeError("IMAP host or credentials are missing for this mailbox")
        socket.setdefaulttimeout(20)
        if security == "ssl":
            client = imaplib.IMAP4_SSL(host, port)
        else:
            client = imaplib.IMAP4(host, port)
            if security == "starttls":
                client.starttls()
        client.login(account["email"], password)
        password = None
        return client

    @staticmethod
    def _message_uid(email: Dict) -> Optional[str]:
        for key in ("imap_uid", "uid", "provider_message_id", "message_id"):
            value = str(email.get(key) or "").strip()
            if value.isdigit():
                return value
        return None

    def _copy_to_folder(self, email: Dict, folder: str, delete_source: bool = False) -> ProviderActionResult:
        uid = self._message_uid(email)
        if not uid:
            return ProviderActionResult.skipped("IMAP provider write queued locally; UID mapping unavailable for remote write")
        target = normalize_bucket_name(folder, "INBOX")
        source = normalize_bucket_name(email.get("folder") or "INBOX", "INBOX")
        client = None
        try:
            client = self._connect()
            client.create(target)
            status, _ = client.select(source)
            if status != "OK":
                client.select("INBOX")
            status, _ = client.uid("COPY", uid, target)
            if status != "OK":
                return ProviderActionResult.failed(f"IMAP copy returned {status}")
            if delete_source:
                client.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
                client.expunge()
                return ProviderActionResult.ok(f"IMAP moved to folder: {target}", {"provider_folder_id": target})
            return ProviderActionResult.ok(
                f"IMAP folder-backed label applied: {target}",
                {"provider_label_id": f"imap-folder:{target}", "provider_folder_id": target, "folder_backed": True},
            )
        except Exception as exc:
            return ProviderActionResult.failed(f"IMAP {'move' if delete_source else 'label'} failed: {exc}")
        finally:
            if client:
                try:
                    client.logout()
                except Exception:
                    pass

    def apply(self, email: Dict, action_type: str, value: Any) -> ProviderActionResult:
        if action_type == RuleAction.MOVE_TO_FOLDER.value:
            folder = normalize_bucket_name(value, "INBOX")
            return self._copy_to_folder(email, folder, delete_source=True)
        if action_type in (RuleAction.ADD_LABEL.value, RuleAction.ADD_CATEGORY.value, RuleAction.SET_CATEGORY.value):
            label = normalize_bucket_name(value)
            return self._copy_to_folder(email, label, delete_source=False)
        return ProviderActionResult.skipped(f"IMAP action not supported: {action_type}")


def get_provider_adapter(account: Optional[Dict], db: Any, enable_provider_write: bool = True):
    if not enable_provider_write or not account:
        return NoProviderActionAdapter()
    provider = str(account.get("provider") or "").lower()
    try:
        if provider == "gmail":
            return GmailProviderActionAdapter(account["id"], db)
        if provider in {"outlook", "microsoft", "microsoft365", "office365", "exchange", "exchange_online"}:
            return OutlookProviderActionAdapter(account["id"], db)
        if provider in {"imap", "yahoo", "zoho", "yandex", "custom", "enterprise", "rediffmail", "fastmail", "aol", "icloud", "proton"}:
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

    def _rule_from_row(self, row: Dict):
        condition = parse_stored_value(row.get("condition"), {})
        actions = parse_stored_value(row.get("action"), [])
        return create_rule_from_dict({
            "id": row.get("id"),
            "name": row.get("name") or f"Rule {row.get('id')}",
            "condition": condition,
            "actions": actions,
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

    def _load_rule_row(self, rule_id: int) -> Optional[Dict]:
        return self.db.fetch_one(
            "SELECT * FROM rules WHERE id = ? AND is_active = 1 AND COALESCE(is_sample, 0) = 0",
            (int(rule_id),),
        )

    def _candidate_emails(self, limit: int = 1000, mailbox_id: int = None,
                          category: str = None, message_ids: Optional[List[int]] = None) -> List[Dict]:
        limit = min(max(int(limit or 1000), 1), 5000)
        where = ["COALESCE(delete_state, 'active') != 'deleted'"]
        params: List[Any] = []
        if mailbox_id:
            where.append("account_id = ?")
            params.append(int(mailbox_id))
        if category:
            where.append("category = ?")
            params.append(category)
        if message_ids:
            ids = [int(x) for x in message_ids if str(x).isdigit()]
            if not ids:
                return []
            where.append(f"id IN ({','.join(['?'] * len(ids))})")
            params.extend(ids)
        query = f"SELECT * FROM emails WHERE {' AND '.join(where)} ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        return self.db.fetch_all(query, tuple(params))

    @staticmethod
    def _action_target(action: Dict) -> str:
        value = action.get("value") or action.get("target_name") or action.get("target")
        if isinstance(value, dict):
            value = value.get("name") or value.get("to") or value
        return normalize_bucket_name(value, "")

    def _planned_action_text(self, action: Dict) -> str:
        action_type = action.get("type")
        target = self._action_target(action)
        if action_type == RuleAction.MOVE_TO_FOLDER.value:
            return f"would move to folder {target or 'selected folder'}"
        if action_type in (RuleAction.ADD_LABEL.value, RuleAction.ADD_CATEGORY.value, RuleAction.SET_CATEGORY.value):
            return f"would apply label {target or 'selected label'}"
        if action_type == RuleAction.MARK_READ.value:
            return "would mark as read"
        if action_type == RuleAction.MARK_UNREAD.value:
            return "would mark as unread"
        if action_type == RuleAction.ARCHIVE.value:
            return "would archive"
        if action_type == RuleAction.FLAG.value:
            return "would star or flag"
        if action_type == RuleAction.FORWARD_EMAIL.value:
            return "would forward email"
        return f"would run {action_type}"

    def _match_details(self, rule: Any, email: Dict) -> Dict:
        enriched = enrich_email_for_rules(email, self.db, persist=True)
        if not rule.match(enriched):
            return {"matched": False, "email": enriched}
        details = match_condition_payload(rule.condition_payload, enriched, rule.match_mode)
        if not details.get("matched"):
            details = {
                "matched": True,
                "matched_condition": str(rule.condition_payload.get("type") or "condition"),
                "matched_source": "entire_email",
                "matched_text_preview": (enriched.get("message_search_text") or "")[:160],
            }
        details["email"] = enriched
        return details

    def simulate_draft_rule(self, rule_dict: Dict, limit: int = 100, mailbox_id: int = None,
                            category: str = None, message_ids: Optional[List[int]] = None) -> Dict:
        rule = self._rule_from_row(rule_dict)
        scope_mailbox = rule_dict.get("mailbox_id") if rule_dict.get("mailbox_scope") == "selected" else mailbox_id
        emails = self._candidate_emails(limit=limit, mailbox_id=scope_mailbox, category=category, message_ids=message_ids)
        matches = []
        for email in emails:
            details = self._match_details(rule, email)
            if not details.get("matched"):
                continue
            enriched = details["email"]
            matches.append({
                "email_id": enriched.get("id"),
                "mailbox_id": enriched.get("account_id") or enriched.get("mailbox_id"),
                "subject": enriched.get("subject"),
                "sender_email": enriched.get("sender_email"),
                "matched_condition": details.get("matched_condition"),
                "matched_source": details.get("matched_source"),
                "matched_text_preview": details.get("matched_text_preview"),
                "planned_actions": [self._planned_action_text(action) for action in normalize_actions(rule.actions)],
            })
        return {
            "ok": True,
            "dry_run": True,
            "rule_id": None,
            "rule_name": rule_dict.get("name", "Draft rule"),
            "scanned_count": len(emails),
            "matched_count": len(matches),
            "matches": matches[:25],
            "message": "Simulation complete. No messages were modified.",
        }

    def simulate_rule(self, rule_id: int, limit: int = 100, mailbox_id: int = None,
                      category: str = None, message_ids: Optional[List[int]] = None) -> Dict:
        row = self._load_rule_row(rule_id)
        if not row:
            return {"ok": False, "status": "not_found", "message": "Rule not found"}
        rule = self._rule_from_row(row)
        scope_mailbox = row.get("mailbox_id") if row.get("mailbox_scope") == "selected" else mailbox_id
        emails = self._candidate_emails(limit=limit, mailbox_id=scope_mailbox, category=category, message_ids=message_ids)
        matches = []
        for email in emails:
            details = self._match_details(rule, email)
            if not details.get("matched"):
                continue
            enriched = details["email"]
            matches.append({
                "email_id": enriched.get("id"),
                "mailbox_id": enriched.get("account_id") or enriched.get("mailbox_id"),
                "subject": enriched.get("subject"),
                "sender_email": enriched.get("sender_email"),
                "matched_condition": details.get("matched_condition"),
                "matched_source": details.get("matched_source"),
                "matched_text_preview": details.get("matched_text_preview"),
                "planned_actions": [self._planned_action_text(action) for action in normalize_actions(rule.actions)],
            })
        return {
            "ok": True,
            "dry_run": True,
            "rule_id": row.get("id"),
            "rule_name": row.get("name"),
            "scanned_count": len(emails),
            "matched_count": len(matches),
            "matches": matches[:25],
            "message": "Simulation complete. No messages were modified.",
        }

    def apply_rule(self, rule_id: int, limit: int = 1000, mailbox_id: int = None,
                   category: str = None, message_ids: Optional[List[int]] = None,
                   provider_write: Optional[bool] = None) -> Dict:
        row = self._load_rule_row(rule_id)
        if not row:
            return {"ok": False, "status": "not_found", "message": "Rule not found"}
        if provider_write is not None:
            old = self.enable_provider_write
            self.enable_provider_write = provider_write
        else:
            old = self.enable_provider_write
        try:
            rule = self._rule_from_row(row)
            scope_mailbox = row.get("mailbox_id") if row.get("mailbox_scope") == "selected" else mailbox_id
            emails = self._candidate_emails(limit=limit, mailbox_id=scope_mailbox, category=category, message_ids=message_ids)
            matches = []
            for email in emails:
                details = self._match_details(rule, email)
                if not details.get("matched"):
                    continue
                enriched = details["email"]
                account = self._email_account(enriched)
                adapter = get_provider_adapter(account, self.db, self.enable_provider_write)
                action_results = [self.apply_action(enriched, rule.name, action, adapter) for action in normalize_actions(rule.actions)]
                provider_status = "; ".join((result.get("provider") or {}).get("detail", "") for result in action_results if result.get("provider"))
                action_taken = ", ".join(result.get("action") or "" for result in action_results)
                self.db.log_rule_execution(
                    rule_id=row.get("id"),
                    rule_name=row.get("name"),
                    mailbox_id=enriched.get("account_id") or enriched.get("mailbox_id"),
                    message_id=enriched.get("id"),
                    matched=True,
                    matched_condition=details.get("matched_condition"),
                    matched_source=details.get("matched_source"),
                    matched_text_preview=details.get("matched_text_preview"),
                    action_taken=action_taken,
                    provider_status=provider_status,
                )
                matches.append({
                    "email_id": enriched.get("id"),
                    "mailbox_id": enriched.get("account_id") or enriched.get("mailbox_id"),
                    "matched_source": details.get("matched_source"),
                    "actions": action_results,
                })
                if rule.stop_processing:
                    break
            self.db.execute("UPDATE rules SET last_run_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), row.get("id")))
            return {
                "ok": True,
                "status": "success",
                "rule_id": row.get("id"),
                "rule_name": row.get("name"),
                "emails_checked": len(emails),
                "matched_count": len(matches),
                "matched_rules": len(matches),
                "results": matches[-25:],
            }
        finally:
            self.enable_provider_write = old

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
                if not value and action.get("target_label_id"):
                    row = self.db.fetch_one("SELECT * FROM mail_labels WHERE id = ?", (int(action.get("target_label_id")),))
                    if row and str(row.get("account_id") or row.get("mailbox_id")) == str(email.get("account_id")):
                        value = row.get("name")
                label = self.db.resolve_mail_label_name(email.get("account_id"), value) if hasattr(self.db, "resolve_mail_label_name") else normalize_bucket_name(value)
                self.db.ensure_mail_label(email.get("account_id"), label)
                self.db.add_email_label(email_id, label)
                email["labels"] = json.dumps(sorted(set(parse_labels(email.get("labels")) + [label])))
                local_success = True
                local_detail = f"label created/applied locally: {label}"
            elif action_type == RuleAction.MOVE_TO_FOLDER.value:
                if not value and action.get("target_folder_id"):
                    row = self.db.fetch_one("SELECT * FROM mail_folders WHERE id = ?", (int(action.get("target_folder_id")),))
                    if row and str(row.get("account_id") or row.get("mailbox_id")) == str(email.get("account_id")):
                        value = row.get("name")
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
        engine = build_rule_engine(self.db, include_defaults=False)
        email = enrich_email_for_rules(email, self.db, persist=True)
        matched: List[Dict] = []

        for rule in engine.rules:
            details = self._match_details(rule, email)
            if not details.get("matched"):
                continue
            actions = normalize_actions(rule.actions)
            action_results = [self.apply_action(email, rule.name, action, adapter) for action in actions]
            rule.execution_count += 1
            rule.last_executed = datetime.now()
            try:
                self.db.log_rule_execution(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    mailbox_id=email.get("account_id") or email.get("mailbox_id"),
                    message_id=email.get("id"),
                    matched=True,
                    matched_condition=details.get("matched_condition"),
                    matched_source=details.get("matched_source"),
                    matched_text_preview=details.get("matched_text_preview"),
                    action_taken=", ".join(action.get("type") for action in actions),
                    provider_status="; ".join((result.get("provider") or {}).get("detail", "") for result in action_results if result.get("provider")),
                )
            except Exception:
                pass
            matched.append({
                "rule_id": rule.rule_id,
                "rule_name": rule.name,
                "matched": True,
                "matched_source": details.get("matched_source"),
                "actions": action_results,
                "email_id": email.get("id"),
                "timestamp": utc_now(),
            })
            if rule.stop_processing:
                break

        return {"email_id": email.get("id"), "matched_rules": matched, "count": len(matched)}

    def apply_rules_to_email_id(self, email_id: int, provider_adapter: Any = None) -> Dict:
        email = self.db.fetch_one("SELECT * FROM emails WHERE id = ?", (email_id,))
        if not email:
            return {"email_id": email_id, "matched_rules": [], "count": 0, "error": "email not found"}
        return self.apply_rules_to_email(email, provider_adapter=provider_adapter)

    def apply_rules_to_existing_emails(self, limit: int = 1000, category: str = None,
                                       provider_write: Optional[bool] = None,
                                       mailbox_id: int = None,
                                       message_ids: Optional[List[int]] = None) -> Dict:
        if provider_write is not None:
            old = self.enable_provider_write
            self.enable_provider_write = provider_write
        else:
            old = self.enable_provider_write
        try:
            emails = self._candidate_emails(limit=limit, mailbox_id=mailbox_id, category=category, message_ids=message_ids)
            results = [self.apply_rules_to_email(email) for email in emails]
            matched = sum(item.get("count", 0) for item in results)
            return {"status": "success", "emails_checked": len(emails), "matched_rules": matched, "results": results[-25:]}
        finally:
            self.enable_provider_write = old
