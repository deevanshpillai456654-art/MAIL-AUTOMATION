"""PKCE (Proof Key for Code Exchange) utilities — RFC 7636."""
from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Dict


def generate_pkce_pair() -> Dict[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return {"verifier": verifier, "challenge": challenge}


def generate_state() -> str:
    return secrets.token_urlsafe(32)
