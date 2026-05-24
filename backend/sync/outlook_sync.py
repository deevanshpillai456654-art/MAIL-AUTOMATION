"""
Outlook/Microsoft Graph email synchronization module.

Provider errors are surfaced as failed syncs instead of being converted to an
empty message list.  Valid empty inbox reads still complete with fetched=0.
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from backend import config
from backend.ai.classifier import EmailClassifier
from backend.auth.outlook_auth import OutlookOAuth
from backend.db.database import Database
from backend.rules.action_executor import RuleActionExecutor

_log = logging.getLogger(__name__)


class ProviderSyncReadError(RuntimeError):
    """Raised when Microsoft Graph could not be read successfully."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _since_iso(days: int = 7) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class OutlookSync:
    API_BASE = "https://graph.microsoft.com/v1.0"
    MAX_RESULTS = 100

    def __init__(self, account_id: int):
        self.account_id = account_id
        self.db = Database(config.DB_PATH)
        self.classifier = EmailClassifier(db=self.db)
        self.oauth = OutlookOAuth()
        self.access_token = self.oauth.get_valid_token(account_id)
        if not self.access_token:
            raise ProviderSyncReadError("No valid Outlook token available. Reconnect the Microsoft account.")
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Dict:
        import requests

        url = f"{self.API_BASE}{endpoint}"
        last_error = None
        for attempt in range(3):
            try:
                response = requests.request(method, url, headers=self.headers, timeout=30, **kwargs)
                if response.ok:
                    try:
                        return response.json() if response.content else {}
                    except ValueError as exc:
                        raise ProviderSyncReadError(f"Microsoft Graph returned invalid JSON for {endpoint}: {exc}") from exc

                if response.status_code == 401 and attempt == 0:
                    self.access_token = self.oauth.get_valid_token(self.account_id)
                    if self.access_token:
                        self.headers["Authorization"] = f"Bearer {self.access_token}"
                        continue
                    message = "Microsoft authorization expired. Reconnect the Outlook account."
                    self.db.update_account_status(self.account_id, "needs_reconnect", "token_expired", message)
                    raise ProviderSyncReadError(message)

                body = (response.text or "").strip()[:500]
                last_error = f"Microsoft Graph {response.status_code} for {endpoint}: {body or response.reason}"
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                self.db.update_account_status(self.account_id, "degraded", "provider_error", last_error)
                raise ProviderSyncReadError(last_error)
            except requests.RequestException as exc:
                last_error = f"Microsoft Graph network error for {endpoint}: {exc}"
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                self.db.update_account_status(self.account_id, "degraded", "network_error", last_error)
                raise ProviderSyncReadError(last_error) from exc

        raise ProviderSyncReadError(last_error or f"Microsoft Graph request failed for {endpoint}")

    async def _make_request_async(self, method: str, endpoint: str, **kwargs) -> Dict:
        from backend.sync.async_provider_transport import AsyncProviderTransport, ProviderTransportError

        transport = AsyncProviderTransport(provider="outlook", api_base=self.API_BASE, headers=self.headers)
        try:
            return await transport.request_json(method, endpoint, **kwargs)
        except ProviderTransportError as exc:
            self.db.update_account_status(self.account_id, "degraded", "provider_error", str(exc))
            raise ProviderSyncReadError(str(exc)) from exc

    def get_messages(self, folder_id: str = "inbox", max_results: int = 100, filter_query: str = None) -> List[Dict]:
        params = {"$top": min(max_results, self.MAX_RESULTS), "$orderby": "receivedDateTime desc"}
        if filter_query:
            params["$filter"] = filter_query
        result = self._make_request("GET", f"/me/mailFolders/{folder_id}/messages", params=params)
        return result.get("value", [])

    def get_message_detail(self, message_id: str) -> Dict:
        result = self._make_request("GET", f"/me/messages/{message_id}", params={"$expand": "attachments"})
        sender = result.get("from", {}) or {}
        from_address = sender.get("emailAddress", {}) or {}
        sender_name = from_address.get("name", "")
        sender_email = from_address.get("address", "")
        body_content = (result.get("body", {}) or {}).get("content", "")
        preview = result.get("preview", "")
        return {
            "message_id": result.get("id") or message_id,
            "subject": result.get("subject", ""),
            "from": f"{sender_name} <{sender_email}>" if sender_name else sender_email,
            "sender": sender_name,
            "sender_email": sender_email,
            "to": result.get("toRecipients", []),
            "cc": result.get("ccRecipients", []),
            "date": result.get("receivedDateTime", ""),
            "body": body_content or preview,
            "preview": preview,
            "is_read": result.get("isRead", True),
            "has_attachments": result.get("hasAttachments", False),
            "importance": result.get("importance", "normal"),
            "categories": result.get("categories", []),
        }

    def get_folders(self) -> List[Dict]:
        result = self._make_request("GET", "/me/mailFolders?$top=100")
        return result.get("value", [])

    def get_categories(self) -> List[Dict]:
        result = self._make_request("GET", "/me/outlook/masterCategories")
        return result.get("value", [])

    def get_message_rules(self) -> List[Dict]:
        result = self._make_request("GET", "/me/mailFolders/inbox/messageRules")
        return result.get("value", [])

    def get_forwarding_rules(self) -> List[Dict]:
        flows: List[Dict] = []
        for item in self.get_message_rules():
            actions = item.get("actions") or {}
            recipients = []
            for key in ("forwardTo", "redirectTo", "forwardAsAttachmentTo"):
                for recipient in actions.get(key) or []:
                    recipients.append(recipient)
            if recipients:
                flows.append({
                    "id": item.get("id"),
                    "to": recipients,
                    "condition": item.get("conditions") or {},
                    "raw": item,
                })
        return flows

    def _record_diagnostic(self, status: str, stats: Dict):
        try:
            self.db.add_provider_diagnostic(self.account_id, "outlook", status, stats)
        except Exception as exc:
            _log.debug("Unable to write Outlook diagnostic: %s", exc)

    def sync(self, max_results: int = 50, sync_id: int = None) -> int:
        sync_id = sync_id or self.db.add_sync_status(self.account_id, "in_progress")
        self.db.update_sync_status(sync_id, "in_progress", progress=0, processed_emails=0, total_emails=0)
        processed = 0
        duplicates = 0
        skipped = 0
        warnings: List[str] = []
        filter_query = f"receivedDateTime ge {_since_iso(7)}"
        folders: List[Dict] = []
        categories: List[Dict] = []
        forwarding_rules: List[Dict] = []
        try:
            messages = self.get_messages("inbox", max_results, filter_query)
            total = len(messages)
            for label_name, getter in (("folders", self.get_folders), ("categories", self.get_categories)):
                try:
                    value = getter()
                    if label_name == "folders":
                        folders = value
                    else:
                        categories = value
                except ProviderSyncReadError as exc:
                    warnings.append(str(exc))
            try:
                forwarding_rules = self.get_forwarding_rules()
            except ProviderSyncReadError as exc:
                warnings.append(str(exc))

            self.db.update_sync_status(sync_id, "in_progress", progress=5 if total else 90, processed_emails=0, total_emails=total)
            for idx, msg in enumerate(messages):
                message_id = msg.get("id")
                if not message_id:
                    skipped += 1
                    continue
                try:
                    detail = self.get_message_detail(message_id)
                except ProviderSyncReadError as exc:
                    skipped += 1
                    warnings.append(str(exc))
                    self.db.update_sync_status(sync_id, "in_progress", progress=int((idx + 1) / max(total, 1) * 100), processed_emails=processed, total_emails=total)
                    continue

                existing = self.db.fetch_one(
                    "SELECT id FROM emails WHERE account_id = ? AND message_id = ?",
                    (self.account_id, detail["message_id"]),
                )
                if existing:
                    duplicates += 1
                    self.db.update_sync_status(sync_id, "in_progress", progress=int((idx + 1) / max(total, 1) * 100), processed_emails=processed, total_emails=total)
                    continue

                classification = self.classifier.classify(
                    subject=detail["subject"],
                    sender=detail["sender"],
                    sender_email=detail["sender_email"],
                    body=detail["body"],
                )
                email_id = self.db.add_email(
                    account_id=self.account_id,
                    message_id=detail["message_id"],
                    subject=detail["subject"],
                    sender=detail["from"],
                    sender_email=detail["sender_email"],
                    body_text=detail["body"],
                    category=classification["category"],
                    confidence=classification["confidence"],
                    priority=classification["priority"],
                )
                try:
                    RuleActionExecutor(self.db, enable_provider_write=True).apply_rules_to_email_id(email_id)
                except Exception as exc:
                    warnings.append(f"Rule action failed for {detail['message_id']}: {exc}")
                try:
                    from backend.api.event_bus import emit_sync
                    emit_sync("email.received", "outlook_sync", {
                        "email_id":     email_id,
                        "subject":      detail["subject"],
                        "sender_email": detail["sender_email"],
                        "category":     classification["category"],
                        "confidence":   classification["confidence"],
                        "account_id":   self.account_id,
                    })
                except Exception:
                    pass

                processed += 1
                self.db.update_sync_status(sync_id, "in_progress", progress=int((idx + 1) / max(total, 1) * 100), processed_emails=processed, total_emails=total)

            if total and processed == 0 and duplicates == 0 and skipped == total:
                raise ProviderSyncReadError("Microsoft Graph returned message ids, but no message details could be read. Check Mail.Read permission and reconnect the account.")

            now = _utc_now()
            stats = {
                "provider": "outlook",
                "mode": "recent_inbox_window",
                "filter": filter_query,
                "max_results": max_results,
                "fetched": total,
                "saved": processed,
                "duplicates": duplicates,
                "skipped": skipped,
                "warnings": warnings[-5:],
                "completed_at": now,
            }
            self.db.update_account_metadata(
                self.account_id,
                metadata={"folders": folders, "categories": categories, "forwarding_rules": forwarding_rules, "last_sync_stats": stats},
                sync_checkpoint=now,
                last_sync_at=now,
            )
            self.db.sync_existing_infrastructure(
                self.account_id,
                {"folders": folders, "categories": categories, "forwarding_rules": forwarding_rules},
                provider="outlook",
            )
            self.db.update_account_status(self.account_id, "connected", "ok")
            self.db.update_sync_status(sync_id, "completed", progress=100, processed_emails=processed, total_emails=total)
            self._record_diagnostic("sync_completed", stats)
            return processed
        except Exception as exc:
            error = str(exc)
            stats = {
                "provider": "outlook",
                "mode": "recent_inbox_window",
                "filter": filter_query,
                "max_results": max_results,
                "saved": processed,
                "duplicates": duplicates,
                "skipped": skipped,
                "warnings": warnings[-5:],
                "error": error,
                "failed_at": _utc_now(),
            }
            self.db.update_sync_status(sync_id, "failed", error=error, processed_emails=processed)
            self.db.update_account_status(self.account_id, "degraded", "sync_failed", error)
            self._record_diagnostic("sync_failed", stats)
            raise


def sync_outlook_account(account_id: int, max_results: int = 50, sync_id: int = None) -> int:
    outlook = OutlookSync(account_id)
    return outlook.sync(max_results, sync_id)
