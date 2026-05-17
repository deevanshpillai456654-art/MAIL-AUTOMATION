"""Local token encryption utilities with MultiFernet key rotation support.

Key management:
  - Primary key: DATA_DIR/token.key (or TOKEN_ENCRYPTION_KEY env var)
  - Retired keys: DATA_DIR/token.key.1, token.key.2, ... (kept for decryption)

MultiFernet encrypts with the primary key and can decrypt with any key in the
chain, allowing zero-downtime rotation: generate a new primary key, all new
tokens are encrypted with it, all old tokens remain decryptable until rotated.
"""

import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, MultiFernet

from backend import config


class TokenCipher:
    def __init__(self, key: Optional[str] = None):
        self.key = self._load_primary_key(key)
        self._fernet = self._build_multi_fernet()

    def _load_primary_key(self, key: Optional[str]) -> bytes:
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
                # Non-valid marker file (e.g. placeholder in release packages) — generate fresh key
                pass

        generated = Fernet.generate_key()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_bytes(generated)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        return generated

    def _build_multi_fernet(self) -> MultiFernet:
        """Load the primary key + any rotation predecessors and return a MultiFernet."""
        fernets = [Fernet(self.key)]
        data_dir = Path(config.DATA_DIR)
        for n in range(1, 10):
            old_key_file = data_dir / f"token.key.{n}"
            if not old_key_file.exists():
                break
            try:
                raw = old_key_file.read_bytes().strip()
                fernets.append(Fernet(raw))
            except Exception:
                break
        return MultiFernet(fernets)

    def rotate(self) -> None:
        """Rotate encryption key.

        Archives the current token.key as token.key.1 (shifting older archives
        down), generates a new primary key, and rebuilds the MultiFernet so that
        tokens encrypted with any prior key remain decryptable.

        Callers are responsible for re-encrypting stored tokens using
        ``encrypt(decrypt(old_ciphertext))`` at a convenient time.
        """
        data_dir = Path(config.DATA_DIR)
        current_key_file = data_dir / "token.key"
        # Shift rotation files: token.key.8 → token.key.9, ..., token.key.1 → token.key.2
        for n in range(8, 0, -1):
            src = data_dir / f"token.key.{n}"
            dst = data_dir / f"token.key.{n + 1}"
            if src.exists():
                src.rename(dst)
        # Archive current primary key as token.key.1
        if current_key_file.exists():
            current_key_file.rename(data_dir / "token.key.1")
        # Generate new primary key
        new_key = Fernet.generate_key()
        current_key_file.write_bytes(new_key)
        try:
            os.chmod(current_key_file, 0o600)
        except OSError:
            pass
        self.key = new_key
        self._fernet = self._build_multi_fernet()

    def encrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def decrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")
