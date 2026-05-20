"""Provider-aware folder and label creation for connected mailboxes."""

from __future__ import annotations

import imaplib
import json
import re
import socket
from datetime import datetime
from typing import Any, Dict, List

import requests

from backend.auth.gmail_auth import GmailOAuth
from backend.auth.imap_auth import IMAPAccountManager
from backend.auth.outlook_auth import OutlookOAuth
from backend.core.provider_capability_registry import ProviderCapabilityRegistry
from backend.rules.action_executor import normalize_bucket_name


class ProviderMailboxTaxonomy:
    """Create mailbox folders/labels remotely when the selected provider supports it.

    The class is intentionally account driven: every operation receives the
    exact mailbox row, so provider writes cannot drift to the first connected
    account for a provider.
    """

    def __init__(self, db: Any):
        self.db = db

    @staticmethod
    def _provider(account: Dict) -> str:
        return ProviderCapabilityRegistry.normalize(account.get("provider") or "")

    @staticmethod
    def _ok(provider_id: str, message: str, data: Dict[str, Any] = None, local_only: bool = False) -> Dict[str, Any]:
        payload = {
            "ok": True,
            "remote": not local_only,
            "local_only": local_only,
            "provider_id": provider_id,
            "message": message,
        }
        if data:
            payload.update(data)
        return payload

    @staticmethod
    def _unsupported(message: str) -> Dict[str, Any]:
        return {"ok": True, "remote": False, "local_only": True, "unsupported": True, "message": message}

    @staticmethod
    def _failed(message: str) -> Dict[str, Any]:
        return {"ok": False, "remote": False, "local_only": False, "message": message}

    def _gmail_token(self, account: Dict) -> str:
        return GmailOAuth(db=self.db, email_address=account.get("email")).get_valid_token(account["id"])

    def _microsoft_token(self, account: Dict) -> str:
        return OutlookOAuth(db=self.db, email_address=account.get("email")).get_valid_token(account["id"])

    @staticmethod
    def _metadata(account: Dict) -> Dict:
        try:
            return json.loads(account.get("metadata") or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}

    def _set_structure_status(self, account_id: int, status: str, error: str = None) -> None:
        if hasattr(self.db, "update_mailbox_structure_status"):
            self.db.update_mailbox_structure_status(account_id, status, error=error)

    @staticmethod
    def _label_color(item: Dict[str, Any]) -> str:
        color = item.get("color") if isinstance(item, dict) else None
        if isinstance(color, dict):
            return color.get("backgroundColor") or color.get("textColor")
        return color if isinstance(color, str) else None

    def _record_gmail_label(self, account: Dict, item: Dict[str, Any]) -> Dict[str, Any]:
        label_id = str(item.get("id") or item.get("name") or "").strip()
        name = str(item.get("name") or label_id).strip()
        if not name:
            return {}
        label_type = "system" if str(item.get("type") or "").lower() == "system" or label_id.isupper() else "custom"
        self.db.ensure_mail_label(
            account["id"],
            name,
            provider_label_id=label_id or name,
            color=self._label_color(item),
            synced_to_provider=True,
            label_type=label_type,
        )
        self.db.ensure_mail_folder(
            account["id"],
            name,
            {"source": "provider_discovery", "provider": "gmail", "raw": item},
            provider_folder_id=label_id or name,
            folder_type=label_type,
            folder_path=name,
            synced_to_provider=True,
        )
        return {"id": label_id or name, "name": name, "type": label_type}

    def _discover_gmail_labels(self, account: Dict) -> List[Dict[str, Any]]:
        token = self._gmail_token(account)
        if not token:
            raise RuntimeError("Gmail account needs reconnect before labels can be discovered.")
        response = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/labels",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if not response.ok:
            raise RuntimeError(f"Gmail label discovery failed: {(response.text or response.reason)[:300]}")
        saved = []
        for item in response.json().get("labels", []):
            record = self._record_gmail_label(account, item)
            if record:
                saved.append(record)
        return saved

    def _graph_get_collection(self, account: Dict, path: str) -> List[Dict[str, Any]]:
        token = self._microsoft_token(account)
        if not token:
            raise RuntimeError("Microsoft account needs reconnect before mailbox structure can be discovered.")
        items: List[Dict[str, Any]] = []
        url = f"https://graph.microsoft.com/v1.0{path}"
        for _ in range(8):
            response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
            if not response.ok:
                raise RuntimeError(f"Microsoft Graph discovery failed: {(response.text or response.reason)[:300]}")
            payload = response.json()
            items.extend(payload.get("value", []))
            url = payload.get("@odata.nextLink")
            if not url:
                break
        return items

    def _discover_microsoft_folders(self, account: Dict) -> List[Dict[str, Any]]:
        saved = []
        for item in self._graph_get_collection(account, "/me/mailFolders?$top=100"):
            folder_id = str(item.get("id") or item.get("displayName") or "").strip()
            name = str(item.get("displayName") or folder_id).strip()
            if not name:
                continue
            self.db.ensure_mail_folder(
                account["id"],
                name,
                {"source": "provider_discovery", "provider": "microsoft", "raw": item},
                provider_folder_id=folder_id or name,
                folder_type="system" if str(item.get("wellKnownName") or "").strip() else "custom",
                folder_path=name,
                synced_to_provider=True,
            )
            saved.append({"id": folder_id or name, "name": name})
        return saved

    def _discover_microsoft_labels(self, account: Dict) -> List[Dict[str, Any]]:
        saved = []
        try:
            items = self._graph_get_collection(account, "/me/outlook/masterCategories")
        except RuntimeError:
            items = []
        for item in items:
            name = str(item.get("displayName") or item.get("id") or "").strip()
            if not name:
                continue
            self.db.ensure_mail_label(
                account["id"],
                name,
                provider_label_id=str(item.get("id") or name),
                color=item.get("color"),
                synced_to_provider=True,
            )
            saved.append({"id": item.get("id") or name, "name": name})
        return saved

    @staticmethod
    def _parse_imap_folder(line: Any) -> str:
        text = line.decode(errors="ignore") if isinstance(line, bytes) else str(line or "")
        quoted = re.findall(r'"([^"]+)"', text)
        if quoted:
            return quoted[-1]
        parts = text.split()
        return parts[-1].strip('"') if parts else ""

    def _discover_imap_folders(self, account: Dict) -> List[Dict[str, Any]]:
        metadata = self._metadata(account)
        host = metadata.get("host") or metadata.get("imap_host")
        port = int(metadata.get("port") or metadata.get("imap_port") or 993)
        security = str(metadata.get("security") or "ssl").lower()
        if not host:
            raise RuntimeError("IMAP host is not configured for this mailbox.")
        password = IMAPAccountManager(self.db).get_password(account)
        if not password:
            raise RuntimeError("IMAP credentials are not available for this mailbox.")
        client = None
        socket.setdefaulttimeout(20)
        try:
            if security == "ssl":
                client = imaplib.IMAP4_SSL(host, port)
            else:
                client = imaplib.IMAP4(host, port)
                if security == "starttls":
                    client.starttls()
            client.login(account["email"], password)
            status, rows = client.list()
            if status != "OK":
                raise RuntimeError(f"IMAP LIST returned {status}.")
            saved = []
            for row in rows or []:
                name = self._parse_imap_folder(row)
                if not name:
                    continue
                self.db.ensure_mail_folder(
                    account["id"],
                    name,
                    {"source": "provider_discovery", "provider": self._provider(account)},
                    provider_folder_id=name,
                    folder_type="system" if name.upper() in {"INBOX", "SENT", "DRAFTS", "TRASH", "SPAM"} else "custom",
                    folder_path=name,
                    synced_to_provider=True,
                )
                saved.append({"id": name, "name": name})
            return saved
        finally:
            password = None
            if client:
                try:
                    client.logout()
                except Exception:
                    pass

    def discover_provider_folders(self, mailbox_id: int) -> Dict[str, Any]:
        account = self.db.get_account_by_id(mailbox_id)
        if not account:
            return self._failed("Mailbox not found.")
        provider = self._provider(account)
        try:
            if provider == "gmail":
                folders = self._discover_gmail_labels(account)
            elif provider in {"outlook", "microsoft365", "exchange"}:
                folders = self._discover_microsoft_folders(account)
            elif provider in {"imap", "yahoo", "zoho", "yandex", "enterprise", "custom", "rediffmail", "fastmail", "aol", "icloud", "proton"}:
                folders = self._discover_imap_folders(account)
            else:
                folders = []
            return {"ok": True, "folders": folders, "folders_synced": len(folders), "mailbox_id": mailbox_id}
        except Exception as exc:
            return {"ok": False, "folders": [], "folders_synced": 0, "mailbox_id": mailbox_id, "message": str(exc)}

    def discover_provider_labels(self, mailbox_id: int) -> Dict[str, Any]:
        account = self.db.get_account_by_id(mailbox_id)
        if not account:
            return self._failed("Mailbox not found.")
        provider = self._provider(account)
        try:
            if provider == "gmail":
                labels = self._discover_gmail_labels(account)
            elif provider in {"outlook", "microsoft365", "exchange"}:
                labels = self._discover_microsoft_labels(account)
            else:
                labels = []
            return {"ok": True, "labels": labels, "labels_synced": len(labels), "mailbox_id": mailbox_id}
        except Exception as exc:
            return {"ok": False, "labels": [], "labels_synced": 0, "mailbox_id": mailbox_id, "message": str(exc)}

    def sync_mailbox_structure(self, mailbox_id: int) -> Dict[str, Any]:
        account = self.db.get_account_by_id(mailbox_id)
        if not account:
            return self._failed("Mailbox not found.")
        self._set_structure_status(mailbox_id, "scanning")
        folders = self.discover_provider_folders(mailbox_id)
        labels = self.discover_provider_labels(mailbox_id)
        ok = bool(folders.get("ok")) and bool(labels.get("ok"))
        error = None if ok else "; ".join(x.get("message", "") for x in (folders, labels) if not x.get("ok"))
        self._set_structure_status(mailbox_id, "synced" if ok else "failed", error=error)
        return {
            "ok": ok,
            "mailbox_id": mailbox_id,
            "provider": account.get("provider"),
            "email_address": account.get("email"),
            "folders_synced": folders.get("folders_synced", 0),
            "labels_synced": labels.get("labels_synced", 0),
            "folders": folders.get("folders", []),
            "labels": labels.get("labels", []),
            "status": "synced" if ok else "failed",
            "message": "Folders and labels synced." if ok else (error or "Could not sync folders/labels for this mailbox. Retry."),
        }

    def refresh_inbox_folder_label_cache(self, mailbox_id: int) -> Dict[str, Any]:
        return self.sync_mailbox_structure(mailbox_id)

    def _create_gmail_label(self, account: Dict, name: str) -> Dict[str, Any]:
        token = self._gmail_token(account)
        if not token:
            return self._failed("Gmail account needs reconnect before remote labels can be created.")
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        response = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/labels",
            headers=headers,
            json={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
            timeout=20,
        )
        if response.status_code == 409:
            existing = requests.get("https://gmail.googleapis.com/gmail/v1/users/me/labels", headers=headers, timeout=20)
            if existing.ok:
                for item in existing.json().get("labels", []):
                    if str(item.get("name") or "").lower() == name.lower():
                        return self._ok(item.get("id") or name, "Gmail label already exists.")
        if not response.ok:
            return self._failed(f"Gmail label creation failed: {(response.text or response.reason)[:300]}")
        created = response.json()
        return self._ok(created.get("id") or name, "Gmail label created.")

    def _create_microsoft_folder(self, account: Dict, name: str) -> Dict[str, Any]:
        token = self._microsoft_token(account)
        if not token:
            return self._failed("Microsoft account needs reconnect before remote folders can be created.")
        response = requests.post(
            "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/childFolders",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"displayName": name},
            timeout=20,
        )
        if not response.ok:
            return self._failed(f"Microsoft folder creation failed: {(response.text or response.reason)[:300]}")
        created = response.json()
        return self._ok(created.get("id") or name, "Microsoft mail folder created.")

    def _create_microsoft_category(self, account: Dict, name: str) -> Dict[str, Any]:
        token = self._microsoft_token(account)
        if not token:
            return self._failed("Microsoft account needs reconnect before remote categories can be created.")
        response = requests.post(
            "https://graph.microsoft.com/v1.0/me/outlook/masterCategories",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"displayName": name, "color": "preset0"},
            timeout=20,
        )
        if response.status_code == 409:
            return self._ok(name, "Microsoft category already exists.")
        if not response.ok:
            return self._failed(f"Microsoft category creation failed: {(response.text or response.reason)[:300]}")
        created = response.json()
        return self._ok(created.get("id") or created.get("displayName") or name, "Microsoft category created.")

    def _create_imap_folder(self, account: Dict, name: str) -> Dict[str, Any]:
        metadata = self._metadata(account)
        host = metadata.get("host") or metadata.get("imap_host")
        port = int(metadata.get("port") or metadata.get("imap_port") or 993)
        security = str(metadata.get("security") or "ssl").lower()
        if not host:
            return self._failed("IMAP host is not configured for this mailbox.")
        password = IMAPAccountManager(self.db).get_password(account)
        if not password:
            return self._failed("IMAP credentials are not available for this mailbox.")
        client = None
        socket.setdefaulttimeout(20)
        try:
            if security == "ssl":
                client = imaplib.IMAP4_SSL(host, port)
            else:
                client = imaplib.IMAP4(host, port)
                if security == "starttls":
                    client.starttls()
            client.login(account["email"], password)
            status, _ = client.create(name)
            if status != "OK":
                return self._failed(f"IMAP folder creation returned {status}.")
            return self._ok(name, "IMAP folder created.")
        except (imaplib.IMAP4.error, OSError, socket.error) as exc:
            return self._failed(f"IMAP folder creation failed: {exc}")
        finally:
            password = None
            if client:
                try:
                    client.logout()
                except Exception:
                    pass

    def create_remote_folder(self, account: Dict, name: str) -> Dict[str, Any]:
        folder_name = normalize_bucket_name(name, "INBOX")
        provider = self._provider(account)
        if provider == "gmail":
            return self._create_gmail_label(account, folder_name)
        if provider in {"outlook", "microsoft365", "exchange"}:
            return self._create_microsoft_folder(account, folder_name)
        if provider in {"imap", "yahoo", "zoho", "yandex", "enterprise", "custom", "rediffmail", "fastmail", "aol", "icloud", "proton"}:
            return self._create_imap_folder(account, folder_name)
        return self._unsupported("This provider does not support remote folder creation in this runtime.")

    def create_remote_label(self, account: Dict, name: str) -> Dict[str, Any]:
        label_name = normalize_bucket_name(name)
        provider = self._provider(account)
        if provider == "gmail":
            return self._create_gmail_label(account, label_name)
        if provider in {"outlook", "microsoft365", "exchange"}:
            return self._create_microsoft_category(account, label_name)
        if provider in {"imap", "yahoo", "zoho", "yandex", "enterprise", "custom", "rediffmail", "fastmail", "aol", "icloud", "proton"}:
            remote = self._create_imap_folder(account, label_name)
            if not remote.get("ok"):
                return remote
            folder_id = remote.get("provider_id") or label_name
            label_id = str(folder_id) if str(folder_id).startswith("imap-folder:") else f"imap-folder:{folder_id}"
            return self._ok(
                label_id,
                "IMAP folder-backed label created.",
                {"folder_backed": True, "folder_name": label_name, "provider_folder_id": folder_id},
            )
        return self._unsupported("This provider did not expose a remote label endpoint in this runtime.")
