"""
Gmail email synchronization module.

The sync path must never report "completed" when Gmail could not actually be
read.  Provider/API/network failures raise explicit errors, while valid empty
inbox results are reported with fetched/saved/duplicate counts.
"""

import base64
import logging
import time
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Dict, List

from backend import config
from backend.ai.classifier import EmailClassifier
from backend.auth.gmail_auth import GmailOAuth
from backend.db.database import Database
from backend.rules.action_executor import RuleActionExecutor

_log = logging.getLogger(__name__)


class ProviderSyncReadError(RuntimeError):
    """Raised when the provider could not be read successfully."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GmailSync:
    API_BASE = "https://gmail.googleapis.com/gmail/v1"
    MAX_RESULTS = 100
    RECENT_QUERY = "in:inbox newer_than:7d"

    def __init__(self, account_id: int):
        self.account_id = account_id
        self.db = Database(config.DB_PATH)
        self.classifier = EmailClassifier(db=self.db)
        self.oauth = GmailOAuth()
        self.access_token = self.oauth.get_valid_token(account_id)
        if not self.access_token:
            raise ProviderSyncReadError("No valid Gmail token available. Reconnect the Gmail account.")
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
                        raise ProviderSyncReadError(f"Gmail returned invalid JSON for {endpoint}: {exc}") from exc

                if response.status_code == 401 and attempt == 0:
                    self.access_token = self.oauth.get_valid_token(self.account_id)
                    if self.access_token:
                        self.headers["Authorization"] = f"Bearer {self.access_token}"
                        continue
                    message = "Gmail authorization expired. Reconnect the Gmail account."
                    self.db.update_account_status(self.account_id, "needs_reconnect", "token_expired", message)
                    raise ProviderSyncReadError(message)

                body = (response.text or "").strip()[:500]
                last_error = f"Gmail API {response.status_code} for {endpoint}: {body or response.reason}"
                if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                self.db.update_account_status(self.account_id, "degraded", "provider_error", last_error)
                raise ProviderSyncReadError(last_error)
            except requests.RequestException as exc:
                last_error = f"Gmail network error for {endpoint}: {exc}"
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                self.db.update_account_status(self.account_id, "degraded", "network_error", last_error)
                raise ProviderSyncReadError(last_error) from exc

        raise ProviderSyncReadError(last_error or f"Gmail request failed for {endpoint}")

    async def _make_request_async(self, method: str, endpoint: str, **kwargs) -> Dict:
        from backend.sync.async_provider_transport import AsyncProviderTransport, ProviderTransportError

        transport = AsyncProviderTransport(provider="gmail", api_base=self.API_BASE, headers=self.headers)
        try:
            return await transport.request_json(method, endpoint, **kwargs)
        except ProviderTransportError as exc:
            self.db.update_account_status(self.account_id, "degraded", "provider_error", str(exc))
            raise ProviderSyncReadError(str(exc)) from exc

    def get_labels(self) -> List[Dict]:
        result = self._make_request("GET", "/users/me/labels")
        return result.get("labels", [])

    def get_filters(self) -> List[Dict]:
        result = self._make_request("GET", "/users/me/settings/filters")
        return result.get("filter", [])

    def get_forwarding_addresses(self) -> List[Dict]:
        result = self._make_request("GET", "/users/me/settings/forwardingAddresses")
        return result.get("forwardingAddresses", [])

    def get_forwarding_rules(self) -> List[Dict]:
        flows: List[Dict] = []
        for item in self.get_filters():
            action = item.get("action") or {}
            forward_to = action.get("forward")
            if forward_to:
                flows.append({
                    "id": item.get("id"),
                    "to": [forward_to],
                    "condition": item.get("criteria") or {},
                    "raw": item,
                })
        for item in self.get_forwarding_addresses():
            email = item.get("forwardingEmail")
            if email:
                flows.append({
                    "id": item.get("forwardingEmail"),
                    "to": [email],
                    "condition": "gmail-forwarding-address",
                    "raw": item,
                })
        return flows

    def get_messages(self, query: str = "", max_results: int = 100, label_ids: List[str] = None) -> List[Dict]:
        params = {"maxResults": min(max_results, self.MAX_RESULTS)}
        if query:
            params["q"] = query
        if label_ids:
            params["labelIds"] = label_ids
        result = self._make_request("GET", "/users/me/messages", params=params)
        return result.get("messages", [])

    def _decode_body(self, payload: Dict) -> str:
        body = payload.get("body", {}).get("data", "")
        if body:
            try:
                return base64.urlsafe_b64decode(body).decode("utf-8", errors="replace")
            except Exception as exc:
                _log.debug("Gmail body decode failed: %s", exc)
        for part in payload.get("parts", []) or []:
            mime_type = part.get("mimeType")
            if mime_type == "text/plain":
                decoded = self._decode_body(part)
                if decoded:
                    return decoded
        for part in payload.get("parts", []) or []:
            mime_type = part.get("mimeType")
            if mime_type == "text/html":
                decoded = self._decode_body(part)
                if decoded:
                    return decoded
        for part in payload.get("parts", []) or []:
            decoded = self._decode_body(part)
            if decoded:
                return decoded
        return ""

    def get_message_detail(self, message_id: str) -> Dict:
        result = self._make_request("GET", f"/users/me/messages/{message_id}", params={"format": "full"})
        headers = result.get("payload", {}).get("headers", [])
        header_dict = {h.get("name", "").lower(): h.get("value", "") for h in headers}
        body = self._decode_body(result.get("payload", {}))
        snippet = result.get("snippet", "")
        sender_name, sender_email = parseaddr(header_dict.get("from", ""))
        return {
            "message_id": result.get("id") or message_id,
            "subject": header_dict.get("subject", ""),
            "from": header_dict.get("from", ""),
            "sender": sender_name,
            "sender_email": sender_email,
            "to": header_dict.get("to", ""),
            "date": header_dict.get("date", ""),
            "body": body or snippet,
            "snippet": snippet,
            "labels": result.get("labelIds", []),
        }

    def _record_diagnostic(self, status: str, stats: Dict):
        try:
            self.db.add_provider_diagnostic(self.account_id, "gmail", status, stats)
        except Exception as exc:
            _log.debug("Unable to write Gmail diagnostic: %s", exc)

    def sync(self, max_results: int = 50, sync_id: int = None) -> int:
        """Sync recent inbox emails from Gmail and store them locally."""
        sync_id = sync_id or self.db.add_sync_status(self.account_id, "in_progress")
        self.db.update_sync_status(sync_id, "in_progress", progress=0, processed_emails=0, total_emails=0)
        processed = 0
        duplicates = 0
        skipped = 0
        warnings: List[str] = []
        query = self.RECENT_QUERY
        labels: List[Dict] = []
        forwarding_rules: List[Dict] = []
        try:
            messages = self.get_messages(query, max_results)
            total = len(messages)
            try:
                labels = self.get_labels()
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
                    sender=detail["sender"],
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
                    emit_sync("email.received", "gmail_sync", {
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
                raise ProviderSyncReadError("Gmail returned message ids, but no message details could be read. Check Gmail permissions and reconnect the account.")

            now = _utc_now()
            stats = {
                "provider": "gmail",
                "mode": "recent_inbox_window",
                "query": query,
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
                metadata={"labels": labels, "forwarding_rules": forwarding_rules, "last_sync_stats": stats},
                sync_checkpoint=now,
                last_sync_at=now,
            )
            self.db.sync_existing_infrastructure(
                self.account_id,
                {"labels": labels, "forwarding_rules": forwarding_rules},
                provider="gmail",
            )
            self.db.update_account_status(self.account_id, "connected", "ok")
            self.db.update_sync_status(sync_id, "completed", progress=100, processed_emails=processed, total_emails=total)
            self._record_diagnostic("sync_completed", stats)
            return processed
        except Exception as exc:
            error = str(exc)
            stats = {
                "provider": "gmail",
                "mode": "recent_inbox_window",
                "query": query,
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

    def start_watch(self) -> Dict:
        if not config.GMAIL_PUBSUB_TOPIC:
            return {
                "status": "configuration_required",
                "missing": ["GMAIL_PUBSUB_TOPIC"],
                "message": "Set GMAIL_PUBSUB_TOPIC to enable Gmail push notifications.",
            }
        result = self._make_request(
            "POST",
            "/users/me/watch",
            json={"topicName": config.GMAIL_PUBSUB_TOPIC, "labelIds": ["INBOX"]},
        )
        self.db.update_account_metadata(self.account_id, metadata={"gmail_watch": result})
        return {"status": "active", "watch": result}


def sync_gmail_account(account_id: int, max_results: int = 50, sync_id: int = None) -> int:
    gmail = GmailSync(account_id)
    return gmail.sync(max_results, sync_id)
