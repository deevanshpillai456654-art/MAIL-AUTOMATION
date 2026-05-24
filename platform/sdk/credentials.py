from __future__ import annotations
import base64
import hashlib
import logging
import os
import secrets
from typing import Dict

logger = logging.getLogger(__name__)

class LocalCredentialVault:
    """Small local-only credential helper.

    This is intentionally a lightweight placeholder for the app's existing encrypted storage.
    It does not contact any central server.
    """
    def __init__(self, secret: str | None = None) -> None:
        env_secret = os.environ.get("MAILPILOT_LOCAL_SECRET")
        if secret:
            self.secret = secret
        elif env_secret:
            self.secret = env_secret
        else:
            self.secret = secrets.token_hex(32)
            logger.warning(
                "LocalCredentialVault: MAILPILOT_LOCAL_SECRET not set; "
                "using a random per-instance key. Secrets will not survive process restart."
            )
        self._store: Dict[str, str] = {}

    def _stream(self, key: str, length: int) -> bytes:
        seed = hashlib.sha256((self.secret + "|" + key).encode()).digest()
        out = bytearray()
        counter = 0
        while len(out) < length:
            out.extend(hashlib.sha256(seed + str(counter).encode()).digest())
            counter += 1
        return bytes(out[:length])

    def encrypt(self, key: str, plaintext: str) -> str:
        raw = plaintext.encode()
        stream = self._stream(key, len(raw))
        encrypted = bytes(a ^ b for a, b in zip(raw, stream))
        return base64.urlsafe_b64encode(encrypted).decode()

    def decrypt(self, key: str, token: str) -> str:
        encrypted = base64.urlsafe_b64decode(token.encode())
        stream = self._stream(key, len(encrypted))
        raw = bytes(a ^ b for a, b in zip(encrypted, stream))
        return raw.decode()

    def set_secret(self, key: str, value: str) -> None:
        self._store[key] = self.encrypt(key, value)

    def get_secret(self, key: str) -> str | None:
        token = self._store.get(key)
        return self.decrypt(key, token) if token else None
