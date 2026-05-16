"""
Local token encryption utilities.
"""

import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from backend import config


class TokenCipher:
    def __init__(self, key: Optional[str] = None):
        self.key = self._load_key(key)
        self.fernet = Fernet(self.key)

    def _load_key(self, key: Optional[str]) -> bytes:
        configured = key or config.TOKEN_ENCRYPTION_KEY
        if configured:
            raw = configured.encode() if isinstance(configured, str) else configured
            try:
                Fernet(raw)
                return raw
            except Exception as exc:
                raise ValueError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc

        key_file = Path(config.DATA_DIR) / "token.key"
        if key_file.exists():
            raw = key_file.read_bytes().strip()
            try:
                Fernet(raw)
                return raw
            except Exception:
                # Release packages may contain a non-secret marker at this path to
                # preserve the baseline folder structure without shipping a usable
                # encryption key. Replace invalid/marker content with a fresh local
                # key on first runtime use.
                pass

        generated = Fernet.generate_key()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(generated)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        return generated

    def encrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return self.fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return self.fernet.decrypt(value.encode("utf-8")).decode("utf-8")
