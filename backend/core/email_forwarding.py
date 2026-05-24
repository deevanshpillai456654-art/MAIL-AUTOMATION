"""Universal local-first email forwarding for rule automation.

This module gives the rules engine one provider-neutral way to forward matched
emails. It validates recipients, records a durable local audit entry, then uses
Gmail API, Microsoft Graph, or SMTP when write/send credentials are available.
Provider failures never erase the local audit trail; they are marked for retry
and shown in diagnostics.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, Iterable, List, Optional

from backend.auth.gmail_auth import GmailOAuth
from backend.auth.outlook_auth import OutlookOAuth
from backend.auth.token_crypto import TokenCipher
from backend.core.mailbox_infrastructure_guard import recipient_list
from backend.core.provider_capability_registry import ProviderCapabilityRegistry

_log = logging.getLogger(__name__)
_EMAIL_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


class ForwardProviderResult(dict):
    @classmethod
    def ok(cls, detail: str, data: Optional[Dict] = None) -> "ForwardProviderResult":
        payload = cls(success=True, skipped=False, detail=detail)
        if data:
            payload.update(data)
        return payload

    @classmethod
    def skipped(cls, detail: str, data: Optional[Dict] = None) -> "ForwardProviderResult":
        payload = cls(success=False, skipped=True, detail=detail)
        if data:
            payload.update(data)
        return payload

    @classmethod
    def failed(cls, detail: str, data: Optional[Dict] = None) -> "ForwardProviderResult":
        payload = cls(success=False, skipped=False, detail=detail)
        if data:
            payload.update(data)
        return payload


def _parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _as_email_list(value: Any) -> List[str]:
    value = _parse_jsonish(value)
    if value is None:
        return []
    if isinstance(value, str):
        candidates = re.split(r"[,;\n]+", value)
    elif isinstance(value, (list, tuple, set)):
        candidates = list(value)
    else:
        candidates = [value]

    out: List[str] = []
    for item in candidates:
        text = str(item or "").strip().strip("<>")
        # Support "Name <person@example.com>".
        match = re.search(r"<([^<>@\s]+@[^<>@\s]+\.[^<>@\s]+)>", str(item or ""))
        if match:
            text = match.group(1).strip()
        text = text.lower()
        if text and _EMAIL_RE.match(text) and text not in out:
            out.append(text)
    return out[:25]


def normalize_forward_payload(value: Any) -> Dict[str, Any]:
    """Normalize rule action value into a forwarding payload.

    Accepted forms:
    - "ops@example.com"
    - ["ops@example.com", "sales@example.com"]
    - {"to": "ops@example.com", "cc": [], "note": "RFQ lead"}
    - {"recipients": ["ops@example.com"], "subject_prefix": "RFQ"}
    """
    parsed = _parse_jsonish(value)
    if isinstance(parsed, dict):
        to_value = parsed.get("to") or parsed.get("recipient") or parsed.get("recipients") or parsed.get("email") or parsed.get("target")
        cc_value = parsed.get("cc")
        bcc_value = parsed.get("bcc")
        note = str(parsed.get("note") or parsed.get("message") or "").strip()
        subject_prefix = str(parsed.get("subject_prefix") or parsed.get("prefix") or "Fwd:").strip() or "Fwd:"
        include_body = bool(parsed.get("include_body", True))
        include_metadata = bool(parsed.get("include_metadata", True))
    else:
        to_value = parsed
        cc_value = None
        bcc_value = None
        note = ""
        subject_prefix = "Fwd:"
        include_body = True
        include_metadata = True

    recipients = _as_email_list(to_value)
    cc = _as_email_list(cc_value)
    bcc = _as_email_list(bcc_value)
    if not recipients:
        raise ValueError("Forward action needs at least one valid recipient email address")
    return {
        "to": recipients,
        "cc": cc,
        "bcc": bcc,
        "note": note[:1000],
        "subject_prefix": subject_prefix[:40],
        "include_body": include_body,
        "include_metadata": include_metadata,
    }


def build_forward_message(account: Dict, email: Dict, payload: Dict[str, Any]) -> EmailMessage:
    subject = str(email.get("subject") or "(no subject)").strip()
    prefix = payload.get("subject_prefix") or "Fwd:"
    if not subject.lower().startswith("fwd:") and not subject.lower().startswith(prefix.lower()):
        subject = f"{prefix} {subject}"

    body_parts: List[str] = []
    if payload.get("note"):
        body_parts.extend([payload["note"], ""])
    if payload.get("include_metadata", True):
        body_parts.extend([
            "---------- Forwarded message ---------",
            f"From: {email.get('sender') or ''} <{email.get('sender_email') or ''}>",
            f"Subject: {email.get('subject') or ''}",
            f"Provider: {account.get('provider') or ''}",
            "",
        ])
    if payload.get("include_body", True):
        body_parts.append(str(email.get("body_text") or email.get("snippet") or ""))

    msg = EmailMessage()
    if account.get("email"):
        msg["From"] = account["email"]
    msg["To"] = ", ".join(payload["to"])
    if payload.get("cc"):
        msg["Cc"] = ", ".join(payload["cc"])
    if payload.get("bcc"):
        msg["Bcc"] = ", ".join(payload["bcc"])
    msg["Subject"] = subject
    msg.set_content("\n".join(body_parts).strip() or "Forwarded by AI Email Organizer.")
    return msg


def message_recipients(payload: Dict[str, Any]) -> List[str]:
    return list(dict.fromkeys(payload.get("to", []) + payload.get("cc", []) + payload.get("bcc", [])))


class UniversalEmailForwarder:
    """Provider-neutral forwarding service used by rules, sync and API paths."""

    def __init__(self, db: Any, enable_provider_write: bool = True):
        self.db = db
        self.enable_provider_write = enable_provider_write
        self.registry = ProviderCapabilityRegistry()
        self.cipher = TokenCipher()

    def forward_email(self, email: Dict, value: Any, rule_name: str = "manual") -> Dict[str, Any]:
        email_id = int(email.get("id") or 0)
        if not email_id:
            return {"success": False, "local_success": False, "provider": ForwardProviderResult.failed("email id missing")}

        account = self.db.get_account_by_id(email.get("account_id")) if email.get("account_id") else None
        provider = ProviderCapabilityRegistry.normalize(account.get("provider") if account else "local")
        try:
            payload = normalize_forward_payload(value)
        except ValueError as exc:
            self._mark_and_log(email, account, provider, rule_name, [], [], [], None, False, False, str(exc), {"error": str(exc)})
            return {"success": False, "local_success": False, "detail": str(exc), "provider": ForwardProviderResult.failed(str(exc))}

        source_addresses = {
            str((account or {}).get("email") or "").strip().lower(),
            str(email.get("sender_email") or "").strip().lower(),
        }
        source_addresses.discard("")
        requested_recipients = set(recipient_list(payload))
        if source_addresses.intersection(requested_recipients):
            detail = "forwarding loop blocked; recipient matches the source mailbox or sender"
            return {
                "success": False,
                "local_success": False,
                "detail": detail,
                "payload": self.safe_payload(payload),
                "provider": ForwardProviderResult.failed(detail, {"loop_blocked": True}),
            }

        msg = build_forward_message(account or {}, email, payload)
        subject = str(msg.get("Subject", ""))
        recipients = payload["to"]
        cc = payload.get("cc", [])
        bcc = payload.get("bcc", [])

        duplicate = self._already_forwarded(email_id, rule_name, message_recipients(payload))
        if duplicate:
            detail = "forward already recorded for this email, rule and recipient set; duplicate send skipped"
            try:
                self.db.mark_email_forward_state(email_id, duplicate.get("recipients") or recipients, duplicate.get("status") or "queued", None)
            except Exception as exc:
                _log.debug("Unable to refresh duplicate forward state: %s", exc)
            return {
                "success": True,
                "local_success": True,
                "detail": detail,
                "payload": self.safe_payload(payload),
                "provider": ForwardProviderResult.skipped(detail, {"duplicate": True}),
                "forward_status": duplicate.get("status") or "queued",
                "duplicate": True,
            }

        if not account:
            detail = "forward queued locally; source account missing"
            self._mark_and_log(email, account, provider, rule_name, recipients, cc, bcc, subject, True, False, detail, {"queued": True})
            return {"success": True, "local_success": True, "detail": detail, "payload": self.safe_payload(payload), "provider": ForwardProviderResult.skipped(detail)}

        if not self.enable_provider_write:
            detail = "forward rule recorded locally; provider send disabled"
            self._mark_and_log(email, account, provider, rule_name, recipients, cc, bcc, subject, True, False, detail, {"queued": True, "provider_write": False})
            return {"success": True, "local_success": True, "detail": detail, "payload": self.safe_payload(payload), "provider": ForwardProviderResult.skipped(detail)}

        provider_result = self._send_with_provider(provider, account, msg, payload)
        status = "forwarded" if provider_result.get("success") else ("queued" if provider_result.get("skipped") else "provider_failed")
        detail = provider_result.get("detail") or status
        self._mark_and_log(email, account, provider, rule_name, recipients, cc, bcc, subject, True, bool(provider_result.get("success")), detail, {"provider": provider, "status": status})
        return {
            "success": True,
            "local_success": True,
            "detail": detail,
            "payload": self.safe_payload(payload),
            "provider": provider_result,
            "forward_status": status,
        }

    def _send_with_provider(self, provider: str, account: Dict, msg: EmailMessage, payload: Dict[str, Any]) -> ForwardProviderResult:
        try:
            if provider == "gmail":
                return self._send_gmail(account, msg)
            if provider in {"outlook", "microsoft365", "exchange", "microsoft"}:
                return self._send_outlook(account, msg, payload)
            if provider == "smtp" or self.registry.get(provider).supports_smtp:
                return self._send_smtp(account, msg, payload)
            return ForwardProviderResult.skipped(f"provider {provider} does not expose a send capability")
        except Exception as exc:  # pragma: no cover - network/runtime failures are environment-specific
            _log.warning("Forward send failed for provider %s: %s", provider, exc)
            return ForwardProviderResult.failed(str(exc), {"provider": provider})

    def _send_gmail(self, account: Dict, msg: EmailMessage) -> ForwardProviderResult:
        import requests

        token = GmailOAuth(db=self.db, email_address=account.get("email")).get_valid_token(account["id"])
        if not token:
            return ForwardProviderResult.skipped("Gmail send token unavailable; reconnect account with Gmail send scope")
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        response = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"raw": raw},
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(f"Gmail send failed {response.status_code}: {(response.text or response.reason)[:300]}")
        return ForwardProviderResult.ok("Gmail forwarded email", {"provider": "gmail"})

    def _send_outlook(self, account: Dict, msg: EmailMessage, payload: Dict[str, Any]) -> ForwardProviderResult:
        import requests

        token = OutlookOAuth(db=self.db, email_address=account.get("email")).get_valid_token(account["id"])
        if not token:
            return ForwardProviderResult.skipped("Microsoft Graph send token unavailable; reconnect account with Mail.Send scope")
        body = msg.get_content()
        message = {
            "subject": msg["Subject"],
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": email}} for email in payload.get("to", [])],
            "ccRecipients": [{"emailAddress": {"address": email}} for email in payload.get("cc", [])],
            "bccRecipients": [{"emailAddress": {"address": email}} for email in payload.get("bcc", [])],
        }
        response = requests.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"message": message, "saveToSentItems": True},
            timeout=30,
        )
        if response.status_code not in (200, 202):
            raise RuntimeError(f"Microsoft Graph send failed {response.status_code}: {(response.text or response.reason)[:300]}")
        return ForwardProviderResult.ok("Outlook forwarded email", {"provider": "microsoft_graph"})

    def _send_smtp(self, account: Dict, msg: EmailMessage, payload: Dict[str, Any]) -> ForwardProviderResult:
        metadata = self._metadata(account)
        host = metadata.get("smtp_host") or metadata.get("host")
        port = int(metadata.get("smtp_port") or (465 if str(metadata.get("smtp_security", "ssl")).lower() == "ssl" else 587))
        security = str(metadata.get("smtp_security") or metadata.get("security") or "ssl").lower()
        if not host:
            return ForwardProviderResult.skipped("SMTP host unavailable for this provider; add SMTP settings or reconnect a send-capable account")
        password = self.cipher.decrypt(account.get("refresh_token")) if account.get("refresh_token") else None
        if not password:
            return ForwardProviderResult.skipped("SMTP credential unavailable; reconnect account with app password")
        username = metadata.get("smtp_username") or metadata.get("username") or account.get("email")
        recipients = message_recipients(payload)
        if security == "ssl":
            client = smtplib.SMTP_SSL(host, port, timeout=30)
        else:
            client = smtplib.SMTP(host, port, timeout=30)
        try:
            if security in {"starttls", "tls"}:
                client.starttls()
            client.login(username, password)
            client.send_message(msg, from_addr=account.get("email"), to_addrs=recipients)
        finally:
            try:
                client.quit()
            except Exception:
                pass
        return ForwardProviderResult.ok("SMTP forwarded email", {"provider": "smtp", "smtp_host": host})

    @staticmethod
    def _metadata(account: Dict) -> Dict[str, Any]:
        raw = account.get("metadata") if account else None
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def safe_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "to": payload.get("to", []),
            "cc": payload.get("cc", []),
            "bcc_count": len(payload.get("bcc", [])),
            "subject_prefix": payload.get("subject_prefix", "Fwd:"),
            "include_body": bool(payload.get("include_body", True)),
        }

    def _already_forwarded(self, email_id: int, rule_name: str, recipients: Iterable[str]) -> Optional[Dict[str, Any]]:
        """Return existing forward audit for the same email/rule/recipients.

        Auto-run sync can re-apply rules after restart or reconnect. Forwarding
        must be idempotent so the same RFQ is not sent multiple times to the
        same destination. Labels and folders are naturally idempotent through
        database constraints; forwarding needs an explicit audit check.
        """
        wanted = set(message_recipients({"to": list(recipients or []), "cc": [], "bcc": []}))
        if not wanted:
            return None
        try:
            rows = self.db.fetch_all(
                """SELECT recipients, provider_success, local_success, provider_status
                   FROM email_forward_audit
                   WHERE email_id = ? AND rule_name = ? AND local_success = 1
                   ORDER BY id DESC LIMIT 25""",
                (email_id, rule_name),
            )
        except Exception as exc:
            _log.debug("Unable to check duplicate forward audit: %s", exc)
            return None
        for row in rows:
            try:
                previous = set(json.loads(row.get("recipients") or "[]"))
            except (TypeError, json.JSONDecodeError):
                previous = set()
            if previous == wanted:
                status = "forwarded" if row.get("provider_success") else "queued"
                return {"recipients": sorted(previous), "status": status, "provider_status": row.get("provider_status")}
        return None

    def _mark_and_log(self, email: Dict, account: Optional[Dict], provider: str, rule_name: str,
                      recipients: Iterable[str], cc: Iterable[str], bcc: Iterable[str], subject: Optional[str],
                      local_success: bool, provider_success: bool, provider_status: str, metadata: Dict[str, Any]) -> None:
        email_id = int(email.get("id") or 0)
        recipients_list = list(recipients or [])
        status = "forwarded" if provider_success else ("queued" if local_success else "failed")
        error = None if provider_success or local_success else provider_status
        try:
            self.db.mark_email_forward_state(email_id, recipients_list, status, error)
        except Exception as exc:
            _log.debug("Unable to mark email forward state: %s", exc)
        try:
            self.db.log_email_forward(
                email_id=email_id,
                account_id=(account or {}).get("id") or email.get("account_id"),
                provider=provider,
                rule_name=rule_name,
                recipients=recipients_list,
                cc=list(cc or []),
                bcc=list(bcc or []),
                subject=subject,
                local_success=local_success,
                provider_success=provider_success,
                provider_status=provider_status,
                metadata=metadata,
            )
        except Exception as exc:
            _log.debug("Unable to log email forward audit: %s", exc)
