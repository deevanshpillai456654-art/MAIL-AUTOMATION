"""
Token Vault - Encrypted Token Storage
======================================

Enterprise token security:
- Encrypted token vault
- Rotating encryption keys
- Token compromise detection
- Automatic revocation
- Token lifecycle management
- Refresh token rotation
- Refresh reuse detection
"""
import os

__path__ = [os.path.join(os.path.dirname(__file__), "token_vault")]

import base64
import hashlib
import json
import logging
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from backend import config

try:
    import keyring as _keyring
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False

_KEYRING_SERVICE = "INTEMO"
_KEYRING_USER = "vault_master"

logger = logging.getLogger("token.vault")


class TokenType(Enum):
    ACCESS = "access"
    REFRESH = "refresh"
    ID_TOKEN = "id_token"


class TokenStatus(Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ROTATING = "rotating"
    COMPROMISED = "compromised"


@dataclass
class TokenRecord:
    """Token record with encryption"""
    token_id: str
    account_id: int
    provider: str
    token_type: TokenType
    encrypted_token: bytes
    encrypted_refresh_token: Optional[bytes]
    created_at: float
    expires_at: Optional[float]
    last_used: float
    rotation_count: int = 0
    is_revoked: bool = False
    revocation_reason: Optional[str] = None
    family_id: Optional[str] = None


@dataclass
class EncryptionKey:
    """Rotating encryption key"""
    key_id: str
    key: bytes
    created_at: float
    expires_at: float
    is_active: bool = True


@dataclass
class TokenCompromiseAlert:
    """Token compromise detection alert"""
    alert_id: str
    account_id: int
    provider: str
    alert_type: str
    details: Dict[str, Any]
    timestamp: float
    resolved: bool = False


class TokenVault:
    """
    Enterprise encrypted token vault with rotating keys.
    """

    def __init__(self, db_path: str = None, master_password: str = None):
        self.db_path = db_path or (Path(config.DATA_DIR) / "token_vault.db")
        self._master_password = master_password or self._get_or_create_master_password()

        # Encryption
        self._current_key: Optional[EncryptionKey] = None
        self._key_rotation_days = 30
        self._keys: Dict[str, EncryptionKey] = {}

        # Token tracking
        self._tokens: Dict[str, TokenRecord] = {}
        self._refresh_token_hashes: Dict[str, str] = {}  # hash -> token_id
        self._lock = threading.RLock()

        # Initialize
        self._init_vault()
        self._load_or_create_key()

        logger.info("Token Vault initialized")

    def _get_or_create_master_password(self) -> str:
        """Get or create master password using OS keychain (Windows Credential Manager,
        macOS Keychain, libsecret on Linux).  Falls back to a permission-restricted file
        when the keyring backend is unavailable."""
        if _KEYRING_AVAILABLE:
            try:
                stored = _keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
                if stored:
                    return stored
                password = secrets.token_urlsafe(32)
                _keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, password)
                return password
            except Exception as exc:
                logger.warning("Keyring unavailable (%s) — falling back to restricted file", exc)

        # File-based fallback: chmod 600 prevents other users from reading it
        password_file = Path(config.DATA_DIR) / ".vault_key"
        if password_file.exists():
            return password_file.read_bytes().decode()

        password = secrets.token_urlsafe(32)
        password_file.write_bytes(password.encode())
        try:
            os.chmod(password_file, 0o600)
        except Exception as _chmod_exc:
            logger.warning("Could not restrict vault key file permissions (%s)", _chmod_exc)
        logger.warning(
            "Master vault password stored in file — install 'keyring' for OS-backed secure storage"
        )
        return password

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """Derive encryption key from password"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
            backend=default_backend()
        )
        return kdf.derive(password.encode())

    def _init_vault(self):
        """Initialize vault database"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Tokens table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tokens (
                token_id TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                token_type TEXT NOT NULL,
                encrypted_token BLOB NOT NULL,
                encrypted_refresh_token BLOB,
                created_at REAL NOT NULL,
                expires_at REAL,
                last_used REAL,
                rotation_count INTEGER DEFAULT 0,
                is_revoked INTEGER DEFAULT 0,
                revocation_reason TEXT,
                family_id TEXT,
                key_id TEXT
            )
        """)

        # Encryption keys table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS encryption_keys (
                key_id TEXT PRIMARY KEY,
                key_data BLOB NOT NULL,
                salt BLOB NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Compromise alerts table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compromise_alerts (
                alert_id TEXT PRIMARY KEY,
                account_id INTEGER NOT NULL,
                provider TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                details TEXT,
                timestamp REAL NOT NULL,
                resolved INTEGER DEFAULT 0
            )
        """)

        # Refresh token reuse tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS refresh_token_hashes (
                hash TEXT PRIMARY KEY,
                token_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                used_count INTEGER DEFAULT 1
            )
        """)

        conn.commit()
        conn.close()

    def _load_or_create_key(self):
        """Load existing key or create new one.

        The derived key bytes are NEVER persisted — only the salt is stored.
        We re-derive the Fernet key from (master_password, salt) at load time
        so that a stolen database alone cannot decrypt any tokens.
        """
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT key_id, salt, created_at, expires_at, is_active
            FROM encryption_keys
            WHERE is_active = 1
            ORDER BY created_at DESC
            LIMIT 1
        """)

        row = cursor.fetchone()
        conn.close()

        if row:
            key_id, salt, created_at, expires_at, is_active = row
            raw_key = self._derive_key(self._master_password, bytes(salt))
            fernet_key = base64.urlsafe_b64encode(raw_key)
            self._current_key = EncryptionKey(
                key_id=key_id,
                key=fernet_key,
                created_at=created_at,
                expires_at=expires_at,
                is_active=bool(is_active),
            )
        else:
            self._rotate_key()

    def _rotate_key(self):
        """Rotate encryption key.

        Only the salt is persisted.  The actual Fernet key is derived at runtime
        from (master_password, salt) and held in memory only.  key_data column
        stores a zero-placeholder to satisfy the NOT NULL constraint.
        """
        salt = os.urandom(16)
        raw_key = self._derive_key(self._master_password, salt)
        fernet_key = base64.urlsafe_b64encode(raw_key)

        key_id = f"key_{secrets.token_hex(8)}"
        now = time.time()

        new_key = EncryptionKey(
            key_id=key_id,
            key=fernet_key,
            created_at=now,
            expires_at=now + (self._key_rotation_days * 86400),
            is_active=True,
        )

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        # Deactivate old keys
        cursor.execute("UPDATE encryption_keys SET is_active = 0")
        # Store only the salt; key_data is a NOT NULL placeholder (never read back)
        cursor.execute("""
            INSERT INTO encryption_keys (key_id, key_data, salt, created_at, expires_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (key_id, b'\x00' * 32, salt, now, new_key.expires_at, 1))
        conn.commit()
        conn.close()

        if self._current_key:
            self._current_key.is_active = False
        self._current_key = new_key
        logger.info(f"Encryption key rotated: {key_id}")

    def _encrypt(self, data: str) -> bytes:
        """Encrypt data with current key"""
        if not self._current_key:
            raise Exception("No encryption key available")

        f = Fernet(self._current_key.key)
        return f.encrypt(data.encode())

    def _decrypt(self, encrypted_data: bytes) -> str:
        """Decrypt data with current key"""
        if not self._current_key:
            raise Exception("No encryption key available")

        f = Fernet(self._current_key.key)
        return f.decrypt(encrypted_data).decode()

    def store_token(self, account_id: int, provider: str,
                   access_token: str, refresh_token: Optional[str] = None,
                   expires_in: int = 3600) -> str:
        """Store token with encryption"""
        with self._lock:
            token_id = f"token_{secrets.token_hex(8)}"

            # Generate family ID if this is first token
            family_id = self._get_or_create_family(account_id, provider)

            created_at = time.time()
            expires_at = created_at + expires_in if expires_in else None

            # Encrypt tokens
            encrypted_access = self._encrypt(access_token)
            encrypted_refresh = self._encrypt(refresh_token) if refresh_token else None

            # Hash refresh token for reuse detection
            refresh_hash = None
            if refresh_token:
                refresh_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
                self._refresh_token_hashes[refresh_hash] = token_id

            token_record = TokenRecord(
                token_id=token_id,
                account_id=account_id,
                provider=provider,
                token_type=TokenType.ACCESS,
                encrypted_token=encrypted_access,
                encrypted_refresh_token=encrypted_refresh,
                created_at=created_at,
                expires_at=expires_at,
                last_used=created_at,
                family_id=family_id
            )

            # Store in database
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tokens (
                    token_id, account_id, provider, token_type,
                    encrypted_token, encrypted_refresh_token,
                    created_at, expires_at, last_used, family_id, key_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                token_id, account_id, provider, TokenType.ACCESS.value,
                encrypted_access, encrypted_refresh,
                created_at, expires_at, created_at, family_id,
                self._current_key.key_id
            ))

            if refresh_hash:
                cursor.execute("""
                    INSERT OR REPLACE INTO refresh_token_hashes (hash, token_id, created_at)
                    VALUES (?, ?, ?)
                """, (refresh_hash, token_id, created_at))

            conn.commit()
            conn.close()

            self._tokens[token_id] = token_record

            logger.info(f"Token stored for account {account_id} ({provider})")

            return token_id

    def _get_or_create_family(self, account_id: int, provider: str) -> str:
        """Get or create token family"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT family_id FROM tokens
            WHERE account_id = ? AND provider = ? AND family_id IS NOT NULL
            LIMIT 1
        """, (account_id, provider))

        row = cursor.fetchone()

        if row:
            family_id = row[0]
        else:
            family_id = f"family_{secrets.token_hex(8)}"

        conn.close()

        return family_id

    def get_token(self, token_id: str) -> Optional[str]:
        """Get decrypted access token"""
        with self._lock:
            # Load from DB if not in memory
            if token_id not in self._tokens:
                self._load_token(token_id)

            if token_id not in self._tokens:
                return None

            token_record = self._tokens[token_id]

            # Check expiration
            if token_record.expires_at and time.time() > token_record.expires_at:
                token_record.is_revoked = True
                return None

            # Update last used
            token_record.last_used = time.time()

            return self._decrypt(token_record.encrypted_token)

    def _load_token(self, token_id: str):
        """Load token from database"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM tokens WHERE token_id = ?", (token_id,))
        row = cursor.fetchone()

        if row:
            self._tokens[token_id] = TokenRecord(
                token_id=row["token_id"],
                account_id=row["account_id"],
                provider=row["provider"],
                token_type=TokenType(row["token_type"]),
                encrypted_token=row["encrypted_token"],
                encrypted_refresh_token=row["encrypted_refresh_token"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                last_used=row["last_used"],
                rotation_count=row["rotation_count"],
                is_revoked=bool(row["is_revoked"]),
                revocation_reason=row["revocation_reason"],
                family_id=row["family_id"]
            )

        conn.close()

    def rotate_token(self, token_id: str, new_access_token: str,
                    new_refresh_token: Optional[str] = None,
                    expires_in: int = 3600) -> bool:
        """Rotate token (refresh)"""
        with self._lock:
            # Load current token
            if token_id not in self._tokens:
                self._load_token(token_id)

            if token_id not in self._tokens:
                return False

            old_token = self._tokens[token_id]

            # Revoke old token
            old_token.is_revoked = True
            old_token.revocation_reason = "rotated"

            # Check refresh token reuse
            if new_refresh_token:
                new_hash = hashlib.sha256(new_refresh_token.encode()).hexdigest()

                if new_hash in self._refresh_token_hashes:
                    # Refresh token reuse detected - possible attack
                    logger.critical(f"Refresh token reuse detected for token {token_id}")
                    self._log_compromise(
                        old_token.account_id,
                        old_token.provider,
                        "refresh_token_reuse",
                        {"token_id": token_id, "new_hash": new_hash[:16]}
                    )

                    # Invalidate entire family
                    self._invalidate_family(old_token.family_id)
                    return False

            # Store new token
            new_token_id = self.store_token(
                old_token.account_id,
                old_token.provider,
                new_access_token,
                new_refresh_token,
                expires_in
            )

            # Update family
            if old_token.family_id:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE tokens SET rotation_count = rotation_count + 1
                    WHERE family_id = ?
                """, (old_token.family_id,))
                conn.commit()
                conn.close()

            logger.info(f"Token rotated: {token_id} -> {new_token_id}")

            return True

    def _invalidate_family(self, family_id: str):
        """Invalidate all tokens in a family"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE tokens SET is_revoked = 1, revocation_reason = 'family_invalidated'
            WHERE family_id = ?
        """, (family_id,))

        conn.commit()
        conn.close()

        logger.warning(f"Token family invalidated: {family_id}")

    def _log_compromise(self, account_id: int, provider: str,
                       alert_type: str, details: Dict):
        """Log token compromise alert"""
        alert_id = f"alert_{secrets.token_hex(8)}"

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO compromise_alerts (alert_id, account_id, provider, alert_type, details, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (alert_id, account_id, provider, alert_type, json.dumps(details), time.time()))
        conn.commit()
        conn.close()

        logger.critical(f"Token compromise alert: {alert_type} for account {account_id}")

    def revoke_token(self, token_id: str, reason: str = "manual"):
        """Revoke a token"""
        with self._lock:
            if token_id not in self._tokens:
                self._load_token(token_id)

            if token_id in self._tokens:
                self._tokens[token_id].is_revoked = True
                self._tokens[token_id].revocation_reason = reason

                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE tokens SET is_revoked = 1, revocation_reason = ?
                    WHERE token_id = ?
                """, (reason, token_id))
                conn.commit()
                conn.close()

                logger.info(f"Token revoked: {token_id} ({reason})")

    def revoke_all_for_account(self, account_id: int, reason: str = "account_deleted"):
        """Revoke all tokens for an account"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE tokens SET is_revoked = 1, revocation_reason = ?
            WHERE account_id = ?
        """, (reason, account_id))

        count = cursor.rowcount
        conn.commit()
        conn.close()

        logger.info(f"Revoked {count} tokens for account {account_id}")

        return count

    def get_active_tokens(self, account_id: int) -> List[Dict]:
        """Get active tokens for account"""
        tokens = []

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT * FROM tokens
            WHERE account_id = ? AND is_revoked = 0
            ORDER BY last_used DESC
        """, (account_id,))

        for row in cursor.fetchall():
            tokens.append({
                "token_id": row["token_id"],
                "provider": row["provider"],
                "token_type": row["token_type"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "last_used": row["last_used"],
                "rotation_count": row["rotation_count"]
            })

        conn.close()

        return tokens

    def check_token_health(self, account_id: int) -> Dict:
        """Check token health for account"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN is_revoked = 1 THEN 1 ELSE 0 END) as revoked,
                SUM(CASE WHEN expires_at IS NOT NULL AND expires_at < ? THEN 1 ELSE 0 END) as expired
            FROM tokens WHERE account_id = ?
        """, (time.time(), account_id))

        row = cursor.fetchone()

        conn.close()

        return {
            "total_tokens": row[0] or 0,
            "revoked_tokens": row[1] or 0,
            "expired_tokens": row[2] or 0,
            "healthy_tokens": (row[0] or 0) - (row[1] or 0) - (row[2] or 0)
        }

    def get_compromise_alerts(self, account_id: int = None) -> List[TokenCompromiseAlert]:
        """Get compromise alerts"""
        alerts = []

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if account_id:
            cursor.execute("""
                SELECT * FROM compromise_alerts
                WHERE account_id = ? AND resolved = 0
                ORDER BY timestamp DESC
            """, (account_id,))
        else:
            cursor.execute("""
                SELECT * FROM compromise_alerts
                WHERE resolved = 0
                ORDER BY timestamp DESC
            """)

        for row in cursor.fetchall():
            alerts.append(TokenCompromiseAlert(
                alert_id=row["alert_id"],
                account_id=row["account_id"],
                provider=row["provider"],
                alert_type=row["alert_type"],
                details=json.loads(row["details"] or "{}"),
                timestamp=row["timestamp"],
                resolved=bool(row["resolved"])
            ))

        conn.close()

        return alerts

    def resolve_alert(self, alert_id: str):
        """Resolve a compromise alert"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE compromise_alerts SET resolved = 1 WHERE alert_id = ?
        """, (alert_id,))
        conn.commit()
        conn.close()


# Global vault
_token_vault: Optional[TokenVault] = None


def get_token_vault() -> TokenVault:
    """Get global token vault"""
    global _token_vault
    if _token_vault is None:
        _token_vault = TokenVault()
    return _token_vault
