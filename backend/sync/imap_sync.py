"""
IMAP email synchronization module.

Every IMAP provider now reports real read errors instead of silently converting
provider failures to an empty successful sync.
"""

import email
import imaplib
import json
import socket
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.policy import default
from email.utils import parseaddr
from typing import Dict, Optional, List

from backend.ai.classifier import EmailClassifier
from backend.auth.imap_auth import IMAPAccountManager
from backend.db.database import Database
from backend import config
from backend.rules.action_executor import RuleActionExecutor


class ProviderSyncReadError(RuntimeError):
    """Raised when the IMAP mailbox could not be read successfully."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _text_body(message: email.message.EmailMessage) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                try:
                    return part.get_content()
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        for part in message.walk():
            if part.get_content_type() == "text/html" and not part.get_filename():
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    try:
        return message.get_content()
    except Exception:
        payload = message.get_payload(decode=True) or b""
        return payload.decode(message.get_content_charset() or "utf-8", errors="replace")


class IMAPSync:
    def __init__(self, account_id: int):
        self.account_id = account_id
        self.db = Database(config.DB_PATH)
        self.classifier = EmailClassifier(db=self.db)
        self.manager = IMAPAccountManager(self.db)
        self.account = self.db.get_account_by_id(account_id)
        if not self.account:
            raise ProviderSyncReadError("IMAP account not found")
        self.provider = self.account.get("provider") or "imap"
        self.metadata = self._metadata(self.account)
        if not self.account.get("refresh_token"):
            raise ProviderSyncReadError("No IMAP credential stored. Reconnect this account with an app password.")

    @staticmethod
    def _metadata(account: Dict) -> Dict:
        try:
            return json.loads(account.get("metadata") or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}

    def _connect(self):
        host = self.metadata.get("host")
        port = int(self.metadata.get("port") or 993)
        security = (self.metadata.get("security") or "ssl").lower()
        if not host:
            raise ProviderSyncReadError("IMAP host is not configured")

        socket.setdefaulttimeout(30)
        try:
            if security == "ssl":
                client = imaplib.IMAP4_SSL(host, port)
            else:
                client = imaplib.IMAP4(host, port)
                if security == "starttls":
                    client.starttls()
            password = self.manager.get_password(self.account)
            if not password:
                raise ProviderSyncReadError("No IMAP credential stored. Reconnect this account with an app password.")
            try:
                client.login(self.account["email"], password)
            finally:
                password = None
            return client
        except (imaplib.IMAP4.error, OSError, socket.error) as exc:
            raise ProviderSyncReadError(f"IMAP connection/login failed for {host}:{port}: {exc}") from exc

    def _parse_message(self, uid: str, raw: bytes) -> Dict:
        message = email.message_from_bytes(raw, policy=default)
        from_header = _header(message.get("From", ""))
        sender_name, sender_email = parseaddr(from_header)
        message_id = _header(message.get("Message-ID", "")) or f"imap:{self.account_id}:{uid}"
        return {
            "uid": uid,
            "message_id": message_id,
            "subject": _header(message.get("Subject", "")),
            "sender": sender_name or sender_email,
            "sender_email": sender_email,
            "body": _text_body(message),
            "date": _header(message.get("Date", "")),
        }

    @staticmethod
    def _list_folders(client) -> List[Dict]:
        status, data = client.list()
        if status != "OK" or not data:
            return []
        folders: List[Dict] = []
        for raw in data:
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            name = text.rsplit(' "/" ', 1)[-1].strip().strip('"')
            if name:
                folders.append({"name": name, "raw": text})
        return folders

    def _record_diagnostic(self, status: str, stats: Dict):
        try:
            self.db.add_provider_diagnostic(self.account_id, self.provider, status, stats)
        except Exception:
            pass

    def sync(self, max_results: int = 50, sync_id: int = None) -> int:
        sync_id = sync_id or self.db.add_sync_status(self.account_id, "in_progress")
        self.db.update_sync_status(sync_id, "in_progress", progress=0, processed_emails=0, total_emails=0)
        processed = 0
        duplicates = 0
        skipped = 0
        client = None
        max_uid = int(self.account.get("sync_checkpoint") or 0) if str(self.account.get("sync_checkpoint") or "").isdigit() else 0
        warnings: List[str] = []
        folders: List[Dict] = []
        try:
            client = self._connect()
            try:
                folders = self._list_folders(client)
            except Exception as exc:
                warnings.append(f"IMAP folder list failed: {exc}")
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise ProviderSyncReadError("Unable to select IMAP INBOX")

            # Always re-scan the latest UID window.  This prevents old checkpoints
            # from hiding newly delivered test mail while duplicate detection keeps
            # repeated background polling safe.
            status, data = client.uid("SEARCH", None, "ALL")
            if status != "OK":
                raise ProviderSyncReadError("IMAP UID search failed")

            uids = data[0].split() if data and data[0] else []
            uids = uids[-max_results:]
            total = len(uids)
            self.db.update_sync_status(sync_id, "in_progress", progress=5 if total else 90, processed_emails=0, total_emails=total)

            for index, uid_bytes in enumerate(uids):
                uid = uid_bytes.decode("ascii", errors="ignore")
                if not uid:
                    skipped += 1
                    continue
                try:
                    status, fetched = client.uid("FETCH", uid, "(RFC822)")
                except (imaplib.IMAP4.error, OSError, socket.error) as exc:
                    skipped += 1
                    warnings.append(f"UID {uid} fetch failed: {exc}")
                    continue
                if status != "OK" or not fetched:
                    skipped += 1
                    warnings.append(f"UID {uid} fetch returned status {status}")
                    continue

                raw = None
                for item in fetched:
                    if isinstance(item, tuple):
                        raw = item[1]
                        break
                if not raw:
                    skipped += 1
                    warnings.append(f"UID {uid} had no RFC822 payload")
                    continue

                detail = self._parse_message(uid, raw)
                try:
                    max_uid = max(max_uid, int(uid))
                except ValueError:
                    pass
                existing = self.db.fetch_one(
                    "SELECT id FROM emails WHERE account_id = ? AND message_id = ?",
                    (self.account_id, detail["message_id"]),
                )
                if existing:
                    duplicates += 1
                    self.db.update_sync_status(sync_id, "in_progress", progress=int((index + 1) / max(total, 1) * 100), processed_emails=processed, total_emails=total)
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
                    emit_sync("email.received", "imap_sync", {
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
                self.db.update_sync_status(sync_id, "in_progress", progress=int((index + 1) / max(total, 1) * 100), processed_emails=processed, total_emails=total)

            if total and processed == 0 and duplicates == 0 and skipped == total:
                raise ProviderSyncReadError("IMAP returned message UIDs, but no email bodies could be fetched. Check IMAP permissions, folder access, and app password settings.")

            now = _utc_now()
            stats = {
                "provider": self.provider,
                "mode": "recent_uid_window",
                "folder": "INBOX",
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
                metadata={"folders": folders, "last_sync_stats": stats},
                sync_checkpoint=str(max_uid) if max_uid else None,
                last_sync_at=now,
            )
            self.db.sync_existing_infrastructure(
                self.account_id,
                {"folders": folders},
                provider=self.provider,
            )
            self.db.update_account_status(self.account_id, "connected", "ok")
            self.db.update_sync_status(sync_id, "completed", progress=100, processed_emails=processed, total_emails=total)
            self._record_diagnostic("sync_completed", stats)
            return processed
        except Exception as exc:
            error = str(exc)
            stats = {
                "provider": self.provider,
                "mode": "recent_uid_window",
                "folder": "INBOX",
                "max_results": max_results,
                "saved": processed,
                "duplicates": duplicates,
                "skipped": skipped,
                "warnings": warnings[-5:],
                "error": error,
                "failed_at": _utc_now(),
            }
            self.db.update_sync_status(sync_id, "failed", error=error, processed_emails=processed)
            self.db.update_account_status(self.account_id, "needs_reconnect", "sync_failed", error)
            self._record_diagnostic("sync_failed", stats)
            raise
        finally:
            if client:
                try:
                    client.logout()
                except Exception:
                    pass


def sync_imap_account(account_id: int, max_results: int = 50, sync_id: int = None) -> int:
    return IMAPSync(account_id).sync(max_results=max_results, sync_id=sync_id)
