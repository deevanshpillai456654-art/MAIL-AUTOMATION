from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List
from sdk.models import utc_now

@dataclass
class LocalWhatsAppSession:
    session_id: str
    tenant_id: str
    branch_id: str | None
    label: str
    phone_hint: str | None = None
    status: str = "disconnected"
    qr_status: str = "not_requested"
    reconnect_attempts: int = 0
    updated_at: str = field(default_factory=utc_now)

class LocalWhatsAppSessionManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, LocalWhatsAppSession] = {}

    def create_session(self, tenant_id: str, label: str, branch_id: str | None = None, phone_hint: str | None = None) -> LocalWhatsAppSession:
        session_id = f"wa-{tenant_id}-{len(self.sessions)+1}"
        session = LocalWhatsAppSession(session_id=session_id, tenant_id=tenant_id, branch_id=branch_id, label=label, phone_hint=phone_hint)
        self.sessions[session_id] = session
        return session

    def request_qr(self, session_id: str) -> dict:
        session = self.sessions[session_id]
        session.qr_status = "ready"
        session.updated_at = utc_now()
        return {"session_id": session_id, "qr_status": "ready", "qr_payload": f"local-session://{session_id}"}

    def connect(self, session_id: str) -> LocalWhatsAppSession:
        session = self.sessions[session_id]
        session.status = "connected"
        session.qr_status = "scanned"
        session.updated_at = utc_now()
        return session

    def disconnect(self, session_id: str) -> LocalWhatsAppSession:
        session = self.sessions[session_id]
        session.status = "disconnected"
        session.updated_at = utc_now()
        return session

    def health(self, tenant_id: str) -> dict:
        items = [s for s in self.sessions.values() if s.tenant_id == tenant_id]
        return {
            "connected": sum(1 for s in items if s.status == "connected"),
            "disconnected": sum(1 for s in items if s.status != "connected"),
            "sessions": [s.__dict__ for s in items],
        }
