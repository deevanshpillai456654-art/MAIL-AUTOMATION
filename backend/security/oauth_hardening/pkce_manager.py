"""
PKCE Manager - OAuth Security Hardening
=======================================

Strict PKCE enforcement with S256 method:
- Code verifier generation (43-128 char random)
- Code challenge computation (SHA256 + base64url)
- PKCE state validation
- PKCE replay protection
- Weak PKCE detection
"""

import base64
import hashlib
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger("pkce.manager")


@dataclass
class PKCEState:
    """PKCE state tracking"""
    verifier: str
    challenge: str
    method: str
    created_at: float
    expires_at: float
    used: bool = False
    session_id: Optional[str] = None


class PKCEManager:
    """
    Enterprise PKCE Manager with strict security enforcement.
    """

    MIN_VERIFIER_LENGTH = 43
    MAX_VERIFIER_LENGTH = 128
    PKCE_LIFETIME = 600

    UNSAFE_PATTERNS = [
        r'^[a-zA-Z0-9_-]*[A-Z][A-Z]*.*[a-z]',  # Only caps followed by lowercase
        r'^(.)\1{5,}$',  # Repeated single char
        r'.*(password|secret|token|key).*',  # Known patterns
    ]

    def __init__(self):
        self._states: Dict[str, PKCEState] = {}
        self._used_challenges: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._strict_mode = True

    def generate_verifier(self) -> str:
        """
        Generate cryptographically secure code verifier.
        Per RFC 7636: 43-128 characters from [A-Z] / [a-z] / [0-9] / "-" / "." / "_" / "~"
        """
        verifier = secrets.token_urlsafe(96)[:128]
        if len(verifier) < self.MIN_VERIFIER_LENGTH:
            verifier = secrets.token_urlsafe(64)
        return verifier[:self.MAX_VERIFIER_LENGTH]

    def compute_challenge(self, verifier: str, method: str = "S256") -> str:
        """
        Compute code challenge from verifier.
        S256: BASE64URL(SHA256(verifier))
        """
        if method == "S256":
            digest = hashlib.sha256(verifier.encode("ascii")).digest()
            return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        elif method == "plain":
            return verifier
        else:
            raise ValueError(f"Unsupported PKCE method: {method}")

    def create_pkce_pair(self, session_id: Optional[str] = None) -> Tuple[PKCEState, str]:
        """
        Create new PKCE pair with strict validation.
        Returns: (pkce_state, auth_url_challenge)
        """
        with self._lock:
            verifier = self.generate_verifier()

            if not self._validate_verifier(verifier):
                raise ValueError("Generated verifier failed security validation")

            challenge = self.compute_challenge(verifier, "S256")

            now = time.time()
            pkce_id = secrets.token_hex(16)

            state = PKCEState(
                verifier=verifier,
                challenge=challenge,
                method="S256",
                created_at=now,
                expires_at=now + self.PKCE_LIFETIME,
                session_id=session_id
            )

            self._states[pkce_id] = state
            self._used_challenges[challenge] = now

            logger.info(f"PKCE pair created: {pkce_id[:8]}... (S256)")

            return state, challenge

    def validate_verifier(self, pkce_id: str, verifier: str) -> Tuple[bool, str]:
        """
        Validate code verifier against stored challenge.
        """
        with self._lock:
            if pkce_id not in self._states:
                return False, "pkce_not_found"

            state = self._states[pkce_id]

            if state.used:
                return False, "pkce_already_used"

            if time.time() > state.expires_at:
                return False, "pkce_expired"

            if not self._validate_verifier(verifier):
                return False, "weak_verifier"

            expected_challenge = self.compute_challenge(verifier, state.method)

            if not secrets.compare_digest(state.challenge, expected_challenge):
                return False, "verifier_mismatch"

            state.used = True

            logger.info(f"PKCE validated: {pkce_id[:8]}...")

            return True, ""

    def _validate_verifier(self, verifier: str) -> bool:
        """
        Validate verifier meets security requirements.
        """
        if not verifier or len(verifier) < self.MIN_VERIFIER_LENGTH:
            return False

        if len(verifier) > self.MAX_VERIFIER_LENGTH:
            return False

        if self._strict_mode:
            if not re.match(r'^[A-Za-z0-9_-]+$', verifier):
                return False

            for pattern in self.UNSAFE_PATTERNS:
                if re.match(pattern, verifier, re.IGNORECASE):
                    return False

            if self._detect_entropy(verifier) < 0.7:
                return False

        return True

    def _detect_entropy(self, verifier: str) -> float:
        """Estimate verifier entropy (0.0 - 1.0)"""
        if not verifier:
            return 0.0

        charset_size = 0
        if any(c.islower() for c in verifier):
            charset_size += 26
        if any(c.isupper() for c in verifier):
            charset_size += 26
        if any(c.isdigit() for c in verifier):
            charset_size += 10
        if any(c in '-_~' for c in verifier):
            charset_size += 3

        if charset_size == 0:
            return 0.0

        entropy_per_char = charset_size ** 0.5 / charset_size if charset_size > 0 else 0

        return min(1.0, len(verifier) * entropy_per_char / 10)

    def check_challenge_reuse(self, challenge: str) -> Tuple[bool, str]:
        """
        Check if challenge has been used before (replay attack detection).
        """
        with self._lock:
            if challenge in self._used_challenges:
                age = time.time() - self._used_challenges[challenge]
                if age < self.PKCE_LIFETIME:
                    logger.warning(f"PKCE challenge reuse detected: {challenge[:16]}...")
                    return True, "challenge_reuse"
                else:
                    del self._used_challenges[challenge]

            return False, ""

    def validate_state(self, pkce_id: str, expected_state: str, provided_state: str) -> Tuple[bool, str]:
        """
        Validate state parameter for OAuth flow.
        """
        with self._lock:
            if pkce_id not in self._states:
                return False, "pkce_not_found"

            if not secrets.compare_digest(expected_state, provided_state):
                return False, "state_mismatch"

            return True, ""

    def revoke_pkce(self, pkce_id: str, reason: str = "manual") -> bool:
        """
        Revoke a PKCE state.
        """
        with self._lock:
            if pkce_id in self._states:
                self._states[pkce_id].used = True
                logger.info(f"PKCE revoked: {pkce_id[:8]}... ({reason})")
                return True
            return False

    def cleanup_expired(self) -> int:
        """
        Clean up expired PKCE states.
        """
        with self._lock:
            now = time.time()
            expired_ids = [
                pkce_id for pkce_id, state in self._states.items()
                if now > state.expires_at
            ]

            for pkce_id in expired_ids:
                del self._states[pkce_id]

            expired_challenges = [
                challenge for challenge, timestamp in self._used_challenges.items()
                if now - timestamp > 3600
            ]
            for challenge in expired_challenges:
                del self._used_challenges[challenge]

            return len(expired_ids) + len(expired_challenges)

    def get_pkce_info(self, pkce_id: str) -> Optional[Dict]:
        """
        Get PKCE state information.
        """
        with self._lock:
            if pkce_id not in self._states:
                return None

            state = self._states[pkce_id]
            return {
                "pkce_id": pkce_id,
                "method": state.method,
                "challenge": state.challenge[:16] + "...",
                "created_at": state.created_at,
                "expires_at": state.expires_at,
                "used": state.used,
                "session_id": state.session_id
            }

    def detect_weak_pkce(self, challenge: str, method: str) -> Dict[str, any]:
        """
        Detect weak PKCE configuration.
        """
        warnings = []

        if method != "S256":
            warnings.append(f"Method should be S256, got {method}")

        if len(challenge) < 43:
            warnings.append("Challenge too short")

        if method == "plain":
            warnings.append("Plain method is insecure")

        return {
            "is_weak": len(warnings) > 0,
            "warnings": warnings,
            "method": method,
            "challenge_length": len(challenge)
        }


_pkcemanager: Optional[PKCEManager] = None


def get_pkce_manager() -> PKCEManager:
    """Get global PKCE manager"""
    global _pkcemanager
    if _pkcemanager is None:
        _pkcemanager = PKCEManager()
    return _pkcemanager
