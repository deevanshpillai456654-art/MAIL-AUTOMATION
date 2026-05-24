"""Credential encryption facade for provider secrets."""
from __future__ import annotations

from typing import Optional

from backend.auth.token_crypto import TokenCipher


class CredentialEncryptor:
    def __init__(self, cipher: TokenCipher = None):
        self.cipher = cipher or TokenCipher()

    def encrypt_secret(self, value: Optional[str]) -> Optional[str]:
        return self.cipher.encrypt(value)

    def decrypt_secret(self, value: Optional[str]) -> Optional[str]:
        return self.cipher.decrypt(value)

    def assert_encrypted(self, stored: Optional[str], raw: Optional[str]) -> None:
        if stored and raw and stored == raw:
            raise ValueError("Provider credentials must not be stored in plaintext")
