"""Canonical mailbox event and email schema normalization."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Dict, Iterable, Optional
import hashlib
import re

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _clean(value: Any, limit: int = 50000) -> str:
    text = "" if value is None else str(value)
    text = _CONTROL_RE.sub("", text).strip()
    if len(text) > limit:
        return text[:limit]
    return text


def normalize_email_address(value: str) -> str:
    _, address = parseaddr(value or "")
    return _clean(address, 320).lower()


@dataclass(frozen=True)
class CanonicalEmail:
    provider: str
    account_id: int
    message_id: str
    subject: str = ""
    sender: str = ""
    sender_email: str = ""
    body_text: str = ""
    body_html: str = ""
    received_at: Optional[str] = None
    labels: Iterable[str] = field(default_factory=tuple)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        material = f"{self.provider}:{self.account_id}:{self.message_id or self.subject}:{self.sender_email}"
        return hashlib.sha256(material.encode("utf-8", errors="ignore")).hexdigest()

    def as_db_payload(self) -> Dict[str, Any]:
        return {
            "account_id": self.account_id,
            "message_id": self.message_id,
            "subject": self.subject,
            "sender": self.sender,
            "sender_email": self.sender_email,
            "body_text": self.body_text,
            "body_html": self.body_html,
        }

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["labels"] = list(self.labels or [])
        data["dedupe_key"] = self.dedupe_key
        return data


class CanonicalEmailNormalizer:
    @staticmethod
    def normalize(raw: Dict[str, Any], provider: str, account_id: int) -> CanonicalEmail:
        sender_raw = raw.get("from") or raw.get("sender") or raw.get("sender_email") or ""
        sender_name, sender_email = parseaddr(sender_raw)
        sender_email = normalize_email_address(raw.get("sender_email") or sender_email)
        if not sender_name and sender_email:
            sender_name = sender_email.split("@")[0]
        message_id = _clean(raw.get("message_id") or raw.get("id") or raw.get("uid") or "", 500)
        if not message_id:
            seed = f"{account_id}:{raw.get('subject','')}:{sender_email}:{raw.get('date') or raw.get('received_at') or ''}"
            message_id = "generated:" + hashlib.sha256(seed.encode()).hexdigest()[:32]
        received_at = raw.get("received_at") or raw.get("date")
        if isinstance(received_at, datetime):
            received_at = received_at.astimezone(timezone.utc).isoformat()
        return CanonicalEmail(
            provider=(provider or "custom").lower(),
            account_id=int(account_id),
            message_id=message_id,
            subject=_clean(raw.get("subject"), 500),
            sender=_clean(sender_name or raw.get("sender"), 300),
            sender_email=sender_email,
            body_text=_clean(raw.get("body_text") or raw.get("body") or raw.get("snippet"), 50000),
            body_html=_clean(raw.get("body_html"), 200000),
            received_at=_clean(received_at, 100) if received_at else None,
            labels=tuple(_clean(v, 100) for v in (raw.get("labels") or [])),
            metadata={k: v for k, v in (raw.get("metadata") or {}).items() if isinstance(k, str)},
        )
