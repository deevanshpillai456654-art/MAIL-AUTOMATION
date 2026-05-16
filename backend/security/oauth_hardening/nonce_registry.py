"""
Nonce Registry - OAuth Security Hardening
==========================================

Cryptographic nonce management:
- Nonce generation with TTL (10 minutes)
- Nonce usage tracking
- Replay attack detection
- Nonce cleanup (expired nonces)
"""

import base64
import secrets
import time
import threading
import logging
import hashlib
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

logger = logging.getLogger("nonce.registry")


@dataclass
class NonceRecord:
    """Nonce record with tracking"""
    nonce: str
    session_id: str
    created_at: float
    expires_at: float
    used: bool = False
    use_count: int = 0
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None


class NonceRegistry:
    """
    Enterprise Nonce Registry with replay protection.
    """

    NONCE_TTL = 600
    MAX_NONCE_USE = 1

    def __init__(self):
        self._nonces: Dict[str, NonceRecord] = {}
        self._used_nonces: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._require_unique_nonce = True

    def generate_nonce(self, session_id: str, ip_address: Optional[str] = None,
                       user_agent: Optional[str] = None) -> str:
        """
        Generate cryptographically secure nonce.
        Uses 256-bit random value.
        """
        nonce = secrets.token_urlsafe(32)

        with self._lock:
            now = time.time()
            self._nonces[nonce] = NonceRecord(
                nonce=nonce,
                session_id=session_id,
                created_at=now,
                expires_at=now + self.NONCE_TTL,
                ip_address=ip_address,
                user_agent=user_agent
            )

        logger.info(f"Nonce generated for session: {session_id[:8]}...")
        return nonce

    def validate_nonce(self, nonce: str, session_id: Optional[str] = None,
                      ip_address: Optional[str] = None) -> Tuple[bool, str]:
        """
        Validate nonce with strict checks.
        """
        with self._lock:
            if nonce in self._used_nonces:
                logger.warning(f"Nonce reuse detected: {nonce[:16]}...")
                return False, "nonce_reused"

            if nonce not in self._nonces:
                logger.warning(f"Unknown nonce: {nonce[:16]}...")
                return False, "nonce_unknown"

            record = self._nonces[nonce]

            if record.used:
                logger.warning(f"Nonce already used: {nonce[:16]}...")
                return False, "nonce_already_used"

            if time.time() > record.expires_at:
                logger.warning(f"Nonce expired: {nonce[:16]}...")
                return False, "nonce_expired"

            if session_id and record.session_id != session_id:
                logger.warning(f"Nonce session mismatch: {nonce[:16]}...")
                return False, "session_mismatch"

            if ip_address and record.ip_address:
                if ip_address != record.ip_address:
                    logger.warning(f"Nonce IP mismatch: {nonce[:16]}...")
                    return False, "ip_mismatch"

            record.used = True
            record.use_count += 1
            self._used_nonces[nonce] = time.time()

            logger.info(f"Nonce validated: {nonce[:16]}...")
            return True, ""

    def register_nonce(self, nonce: str, session_id: str, ip_address: Optional[str] = None,
                       user_agent: Optional[str] = None) -> bool:
        """
        Register pre-existing nonce (from auth URL).
        """
        with self._lock:
            if nonce in self._nonces:
                return False

            now = time.time()
            self._nonces[nonce] = NonceRecord(
                nonce=nonce,
                session_id=session_id,
                created_at=now,
                expires_at=now + self.NONCE_TTL,
                ip_address=ip_address,
                user_agent=user_agent
            )

            logger.info(f"Nonce registered for session: {session_id[:8]}...")
            return True

    def consume_nonce(self, nonce: str) -> Tuple[bool, str]:
        """
        Mark nonce as consumed (single use).
        """
        with self._lock:
            if nonce not in self._nonces:
                return False, "nonce_not_found"

            record = self._nonces[nonce]

            if record.used and self._require_unique_nonce:
                return False, "nonce_already_consumed"

            if time.time() > record.expires_at:
                return False, "nonce_expired"

            record.used = True
            record.use_count += 1
            self._used_nonces[nonce] = time.time()

            return True, ""

    def check_nonce_replay(self, nonce: str) -> Tuple[bool, str]:
        """
        Check for nonce replay attack.
        """
        with self._lock:
            if nonce in self._used_nonces:
                return True, "replay_detected"

            if nonce in self._nonces:
                record = self._nonces[nonce]
                if record.used:
                    return True, "already_used"

            return False, ""

    def get_nonce_session(self, nonce: str) -> Optional[str]:
        """Get session ID for nonce"""
        with self._lock:
            if nonce in self._nonces:
                return self._nonces[nonce].session_id
            return None

    def revoke_nonce(self, nonce: str, reason: str = "manual") -> bool:
        """
        Revoke a nonce.
        """
        with self._lock:
            if nonce in self._nonces:
                self._nonces[nonce].used = True
                logger.info(f"Nonce revoked: {nonce[:16]}... ({reason})")
                return True
            return False

    def revoke_session_nonces(self, session_id: str) -> int:
        """
        Revoke all nonces for a session.
        """
        with self._lock:
            count = 0
            for nonce, record in self._nonces.items():
                if record.session_id == session_id:
                    record.used = True
                    count += 1

            if count > 0:
                logger.info(f"Revoked {count} nonces for session: {session_id[:8]}...")

            return count

    def cleanup_expired(self) -> int:
        """
        Clean up expired nonces.
        """
        with self._lock:
            now = time.time()
            expired_nonces = [
                nonce for nonce, record in self._nonces.items()
                if now > record.expires_at
            ]

            for nonce in expired_nonces:
                del self._nonces[nonce]

            expired_used = [
                nonce for nonce, timestamp in self._used_nonces.items()
                if now - timestamp > 3600
            ]

            for nonce in expired_used:
                del self._used_nonces[nonce]

            if expired_nonces or expired_used:
                logger.info(f"Cleaned up {len(expired_nonces)} nonces, {len(expired_used)} used nonces")

            return len(expired_nonces)

    def get_nonce_info(self, nonce: str) -> Optional[Dict]:
        """
        Get nonce information.
        """
        with self._lock:
            if nonce not in self._nonces:
                return None

            record = self._nonces[nonce]
            return {
                "nonce": nonce[:16] + "...",
                "session_id": record.session_id[:8] + "..." if record.session_id else None,
                "created_at": record.created_at,
                "expires_at": record.expires_at,
                "used": record.used,
                "use_count": record.use_count,
                "ip_address": record.ip_address
            }

    def validate_nonce_signature(self, nonce: str, signature: str, secret: str) -> Tuple[bool, str]:
        """
        Validate nonce with HMAC signature.
        """
        expected_sig = self._compute_nonce_signature(nonce, secret)

        if not secrets.compare_digest(expected_sig, signature):
            return False, "invalid_signature"

        return self.validate_nonce(nonce)

    def _compute_nonce_signature(self, nonce: str, secret: str) -> str:
        """Compute HMAC signature for nonce"""
        return hmac.new(
            secret.encode(),
            nonce.encode(),
            hashlib.sha256
        ).hexdigest()


_nonce_registry: Optional[NonceRegistry] = None


def get_nonce_registry() -> NonceRegistry:
    """Get global nonce registry"""
    global _nonce_registry
    if _nonce_registry is None:
        _nonce_registry = NonceRegistry()
    return _nonce_registry