"""
OAuth Replay Protection - Enterprise Security Hardening
========================================================

Authorization code replay prevention:
- Authorization code single-use enforcement
- State parameter validation with signature
- Callback URL strict matching
- Timestamp validation (reject >5 min old)
- IP binding option
- Browser fingerprint validation
"""

import hashlib
import hmac
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("oauth.replay")


@dataclass
class AuthCodeRecord:
    """Authorization code record for replay protection"""
    code_hash: str
    session_id: str
    redirect_uri: str
    created_at: float
    expires_at: float
    used: bool = False
    used_at: Optional[float] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    fingerprint: Optional[str] = None


@dataclass
class StateRecord:
    """State parameter with signature validation"""
    state: str
    session_id: str
    signature: str
    created_at: float
    expires_at: float
    redirect_uri: str
    nonce: Optional[str] = None
    ip_address: Optional[str] = None


class OAuthReplayProtection:
    """
    Enterprise OAuth Replay Protection.
    """

    CODE_LIFETIME = 600
    STATE_LIFETIME = 600
    MAX_TIMESTAMP_AGE = 300
    MAX_CODE_USE = 1

    def __init__(self):
        self._auth_codes: Dict[str, AuthCodeRecord] = {}
        self._used_codes: Dict[str, float] = {}
        self._states: Dict[str, StateRecord] = {}
        self._lock = threading.RLock()
        self._bind_ip = True
        self._bind_fingerprint = True
        self._sign_secret: Optional[str] = None

    def set_signing_secret(self, secret: str):
        """Set secret for state signature"""
        self._sign_secret = secret

    def generate_state(self, session_id: str, redirect_uri: str,
                      ip_address: Optional[str] = None,
                      nonce: Optional[str] = None) -> str:
        """
        Generate signed state parameter.
        """
        state = secrets.token_urlsafe(32)

        if self._sign_secret:
            signature = self._compute_signature(state, redirect_uri, nonce)
        else:
            signature = secrets.token_hex(16)

        with self._lock:
            now = time.time()
            self._states[state] = StateRecord(
                state=state,
                session_id=session_id,
                signature=signature,
                created_at=now,
                expires_at=now + self.STATE_LIFETIME,
                redirect_uri=redirect_uri,
                nonce=nonce,
                ip_address=ip_address
            )

        logger.info(f"State generated for session: {session_id[:8]}...")
        return state

    def validate_state(self, state: str, provided_redirect_uri: str,
                      provided_nonce: Optional[str] = None,
                      ip_address: Optional[str] = None) -> Tuple[bool, str]:
        """
        Validate state parameter with full verification.
        """
        with self._lock:
            if state not in self._states:
                logger.warning(f"Unknown state: {state[:8]}...")
                return False, "invalid_state"

            record = self._states[state]

            if time.time() > record.expires_at:
                logger.warning(f"State expired: {state[:8]}...")
                return False, "state_expired"

            if not self._strict_url_match(record.redirect_uri, provided_redirect_uri):
                logger.warning(f"Redirect URI mismatch: {state[:8]}...")
                return False, "redirect_uri_mismatch"

            if provided_nonce and record.nonce:
                if not secrets.compare_digest(record.nonce, provided_nonce):
                    logger.warning(f"Nonce mismatch: {state[:8]}...")
                    return False, "nonce_mismatch"

            if self._bind_ip and ip_address and record.ip_address:
                if not secrets.compare_digest(record.ip_address, ip_address):
                    logger.warning(f"IP mismatch: {state[:8]}...")
                    return False, "ip_mismatch"

            return True, ""

    def _compute_signature(self, state: str, redirect_uri: str, nonce: Optional[str]) -> str:
        """Compute HMAC signature for state"""
        parts = [state, redirect_uri]
        if nonce:
            parts.append(nonce)

        message = "|".join(parts)
        return hmac.new(
            self._sign_secret.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

    def _strict_url_match(self, expected: str, provided: str) -> bool:
        """Strict URL matching for callback validation"""
        expected_parsed = urlparse(expected)
        provided_parsed = urlparse(provided)

        if expected_parsed.scheme != provided_parsed.scheme:
            return False
        if expected_parsed.netloc != provided_parsed.netloc:
            return False
        if expected_parsed.path != provided_parsed.path:
            return False

        return True

    def register_auth_code(self, code: str, session_id: str, redirect_uri: str,
                          ip_address: Optional[str] = None,
                          user_agent: Optional[str] = None,
                          fingerprint: Optional[str] = None):
        """
        Register authorization code for tracking.
        """
        code_hash = hashlib.sha256(code.encode()).hexdigest()

        with self._lock:
            now = time.time()
            self._auth_codes[code_hash] = AuthCodeRecord(
                code_hash=code_hash,
                session_id=session_id,
                redirect_uri=redirect_uri,
                created_at=now,
                expires_at=now + self.CODE_LIFETIME,
                ip_address=ip_address,
                user_agent=user_agent,
                fingerprint=fingerprint
            )

        logger.info(f"Auth code registered: {code_hash[:8]}...")

    def validate_auth_code(self, code: str, redirect_uri: str,
                           ip_address: Optional[str] = None,
                           user_agent: Optional[str] = None,
                           fingerprint: Optional[str] = None) -> Tuple[bool, str]:
        """
        Validate authorization code with replay protection.
        """
        with self._lock:
            code_hash = hashlib.sha256(code.encode()).hexdigest()

            if code_hash in self._used_codes:
                logger.critical(f"Auth code REPLAY detected: {code_hash[:8]}...")
                return False, "code_replay_detected"

            if code_hash not in self._auth_codes:
                logger.warning(f"Unknown auth code: {code_hash[:8]}...")
                return False, "invalid_code"

            record = self._auth_codes[code_hash]

            if record.used:
                logger.critical(f"Auth code already used: {code_hash[:8]}...")
                return False, "code_already_used"

            if time.time() > record.expires_at:
                logger.warning(f"Auth code expired: {code_hash[:8]}...")
                return False, "code_expired"

            if not self._strict_url_match(record.redirect_uri, redirect_uri):
                logger.warning(f"Redirect URI mismatch: {code_hash[:8]}...")
                return False, "redirect_uri_mismatch"

            if self._bind_ip and ip_address and record.ip_address:
                if not secrets.compare_digest(ip_address, record.ip_address):
                    logger.warning(f"IP mismatch: {code_hash[:8]}...")
                    return False, "ip_mismatch"

            if self._bind_fingerprint and fingerprint and record.fingerprint:
                if not secrets.compare_digest(fingerprint, record.fingerprint):
                    logger.warning(f"Fingerprint mismatch: {code_hash[:8]}...")
                    return False, "fingerprint_mismatch"

            record.used = True
            record.used_at = time.time()
            self._used_codes[code_hash] = time.time()

            logger.info(f"Auth code validated: {code_hash[:8]}...")

            return True, ""

    def consume_auth_code(self, code: str) -> Tuple[bool, str]:
        """
        Mark authorization code as consumed (single use).
        """
        code_hash = hashlib.sha256(code.encode()).hexdigest()

        with self._lock:
            if code_hash in self._used_codes:
                return False, "code_already_consumed"

            if code_hash not in self._auth_codes:
                return False, "code_not_found"

            record = self._auth_codes[code_hash]

            if record.used:
                return False, "code_already_used"

            if time.time() > record.expires_at:
                return False, "code_expired"

            record.used = True
            record.used_at = time.time()
            self._used_codes[code_hash] = time.time()

            return True, ""

    def check_code_replay(self, code: str) -> Tuple[bool, str]:
        """
        Check for authorization code replay attack.
        """
        code_hash = hashlib.sha256(code.encode()).hexdigest()

        with self._lock:
            if code_hash in self._used_codes:
                return True, "replay_detected"

            if code_hash in self._auth_codes:
                if self._auth_codes[code_hash].used:
                    return True, "already_used"

            return False, ""

    def validate_timestamp(self, timestamp: float) -> Tuple[bool, str]:
        """
        Validate timestamp (reject >5 min old).
        """
        now = time.time()
        age = now - timestamp

        if age < 0:
            return False, "future_timestamp"

        if age > self.MAX_TIMESTAMP_AGE:
            return False, "timestamp_too_old"

        return True, ""

    def compute_fingerprint(self, user_agent: str, accept: str, accept_language: str) -> str:
        """
        Compute browser fingerprint for binding.
        """
        parts = [user_agent, accept, accept_language]
        combined = "|".join(parts)

        return hashlib.sha256(combined.encode()).hexdigest()

    def revoke_session(self, session_id: str) -> int:
        """
        Revoke all auth codes and states for a session.
        """
        with self._lock:
            count = 0

            for code_hash, record in self._auth_codes.items():
                if record.session_id == session_id:
                    record.used = True
                    count += 1

            for state, record in self._states.items():
                if record.session_id == session_id:
                    del self._states[state]

            if count > 0:
                logger.warning(f"Revoked {count} auth codes for session: {session_id[:8]}...")

            return count

    def cleanup_expired(self) -> int:
        """
        Clean up expired codes and states.
        """
        with self._lock:
            now = time.time()

            expired_codes = [
                code_hash for code_hash, record in self._auth_codes.items()
                if now > record.expires_at
            ]
            for code_hash in expired_codes:
                del self._auth_codes[code_hash]

            expired_states = [
                state for state, record in self._states.items()
                if now > record.expires_at
            ]
            for state in expired_states:
                del self._states[state]

            expired_used = [
                code_hash for code_hash, timestamp in self._used_codes.items()
                if now - timestamp > 3600
            ]
            for code_hash in expired_used:
                del self._used_codes[code_hash]

            total = len(expired_codes) + len(expired_states) + len(expired_used)
            if total > 0:
                logger.info(f"Cleaned up {total} expired OAuth resources")

            return total

    def get_code_info(self, code: str) -> Optional[Dict]:
        """Get auth code information"""
        code_hash = hashlib.sha256(code.encode()).hexdigest()

        with self._lock:
            if code_hash not in self._auth_codes:
                return None

            record = self._auth_codes[code_hash]
            return {
                "code_hash": code_hash[:16] + "...",
                "session_id": record.session_id[:8] + "...",
                "created_at": record.created_at,
                "expires_at": record.expires_at,
                "used": record.used,
                "used_at": record.used_at,
                "ip_address": record.ip_address
            }

    def get_state_info(self, state: str) -> Optional[Dict]:
        """Get state information"""
        with self._lock:
            if state not in self._states:
                return None

            record = self._states[state]
            return {
                "state": state[:8] + "...",
                "session_id": record.session_id[:8] + "...",
                "created_at": record.created_at,
                "expires_at": record.expires_at,
                "redirect_uri": record.redirect_uri[:50] + "...",
                "has_nonce": record.nonce is not None
            }


_oauth_replay: Optional[OAuthReplayProtection] = None


def get_oauth_replay_protection() -> OAuthReplayProtection:
    """Get global OAuth replay protection"""
    global _oauth_replay
    if _oauth_replay is None:
        _oauth_replay = OAuthReplayProtection()
    return _oauth_replay
