"""
Session Manager - User Session Management
=========================================

Session management:
- Session creation/validation
- Session storage
- Session expiration
- Session security
- Concurrent session limits
"""

import time
import secrets
import threading
import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("session.manager")


class SessionState(Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class Session:
    """User session"""
    session_id: str
    user_id: str
    expires_at: float
    created_at: float = field(default_factory=time.time)
    last_access: float = field(default_factory=time.time)
    state: SessionState = SessionState.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class SessionManager:
    """
    User session manager.
    """
    
    def __init__(self, max_sessions_per_user: int = 5, session_ttl: float = 86400):
        self.max_sessions_per_user = max_sessions_per_user
        self.session_ttl = session_ttl
        self._sessions: Dict[str, Session] = {}
        self._user_sessions: Dict[str, set] = {}
        self._lock = threading.RLock()
        
        logger.info("SessionManager initialized")
    
    def create_session(self, user_id: str, metadata: Dict = None, ip: str = None, user_agent: str = None) -> str:
        """Create new session"""
        with self._lock:
            # Clean up old sessions if needed
            if user_id in self._user_sessions:
                if len(self._user_sessions[user_id]) >= self.max_sessions_per_user:
                    # Remove oldest session
                    old = min(
                        self._user_sessions[user_id],
                        key=lambda s: self._sessions[s].last_access
                    )
                    self.revoke_session(old)
            
            session_id = f"sess_{secrets.token_hex(32)}"
            expires_at = time.time() + self.session_ttl
            
            session = Session(
                session_id=session_id,
                user_id=user_id,
                expires_at=expires_at,
                metadata=metadata or {},
                ip_address=ip,
                user_agent=user_agent
            )
            
            self._sessions[session_id] = session
            
            if user_id not in self._user_sessions:
                self._user_sessions[user_id] = set()
            self._user_sessions[user_id].add(session_id)
            
            logger.info(f"Session created: {session_id[:16]}... for user {user_id}")
            
            return session_id
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session"""
        with self._lock:
            session = self._sessions.get(session_id)
            
            if not session:
                return None
            
            # Check expiration
            if time.time() > session.expires_at:
                self._cleanup_session(session_id)
                return None
            
            # Update last access
            session.last_access = time.time()
            
            return session
    
    def validate_session(self, session_id: str, user_id: str = None) -> bool:
        """Validate session"""
        session = self.get_session(session_id)
        
        if not session:
            return False
        
        if user_id and session.user_id != user_id:
            return False
        
        return session.state == SessionState.ACTIVE
    
    def revoke_session(self, session_id: str) -> bool:
        """Revoke session"""
        with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                session.state = SessionState.REVOKED
                
                # Remove from user sessions
                if session.user_id in self._user_sessions:
                    self._user_sessions[session.user_id].discard(session_id)
                
                del self._sessions[session_id]
                
                logger.info(f"Session revoked: {session_id[:16]}...")
                return True
            
            return False
    
    def _cleanup_session(self, session_id: str):
        """Clean up expired session"""
        if session_id in self._sessions:
            session = self._sessions[session_id]
            session.state = SessionState.EXPIRED
            
            if session.user_id in self._user_sessions:
                self._user_sessions[session.user_id].discard(session_id)
            
            del self._sessions[session_id]
    
    def get_user_sessions(self, user_id: str) -> list:
        """Get user's active sessions"""
        with self._lock:
            if user_id not in self._user_sessions:
                return []
            
            active = []
            for sid in self._user_sessions[user_id]:
                session = self._sessions.get(sid)
                if session and session.state == SessionState.ACTIVE:
                    if time.time() <= session.expires_at:
                        active.append(sid)
            
            return active
    
    def revoke_all_user_sessions(self, user_id: str) -> int:
        """Revoke all user's sessions"""
        with self._lock:
            count = 0
            for sid in list(self._user_sessions.get(user_id, [])):
                if self.revoke_session(sid):
                    count += 1
            return count
    
    def get_stats(self) -> Dict:
        """Get session manager stats"""
        with self._lock:
            active = sum(1 for s in self._sessions.values() if s.state == SessionState.ACTIVE)
            return {
                "total_sessions": len(self._sessions),
                "active_sessions": active,
                "total_users": len(self._user_sessions)
            }


# Global session manager
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get global session manager"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


__all__ = ["SessionManager", "Session", "SessionState", "get_session_manager"]