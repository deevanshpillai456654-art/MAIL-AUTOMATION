"""
Verify file integrity with SHA-256 and optional Ed25519 signatures.

Production deployments can provide public keys from KMS or another trusted key source.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

logger = logging.getLogger("artifact_verify")


class ArtifactVerifier:
    def __init__(self):
        self._lock = threading.Lock()

    def sha256_file(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def verify_digest(self, path: Path, expected_hex: str) -> Tuple[bool, str]:
        actual = self.sha256_file(path)
        ok = actual.lower() == expected_hex.lower()
        return ok, actual

    def verify_signature(
        self,
        path: Path,
        signature_b64: str,
        public_key_provider: Optional[Callable[[], bytes]] = None,
    ) -> bool:
        if public_key_provider is None:
            logger.warning("Signature verification requires a public key provider")
            return False
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            key_bytes = public_key_provider()
            signature = base64.b64decode(signature_b64)
            public_key = Ed25519PublicKey.from_public_bytes(key_bytes)
            public_key.verify(signature, path.read_bytes())
            return True
        except Exception as exc:
            logger.warning("Artifact signature verification failed: %s", exc)
            return False


__all__ = ["ArtifactVerifier"]
