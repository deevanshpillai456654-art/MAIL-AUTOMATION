"""Signed extension message envelope support."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import hmac
import json
import time
from typing import Any, Dict, Set

@dataclass(frozen=True)
class BridgeDecision:
    ok: bool
    reason: str = "ok"

class SecureMessageBridge:
    def __init__(self, secret: str, window_seconds: int = 300):
        if not secret:
            raise ValueError("secret is required")
        self.secret = secret.encode("utf-8")
        self.window_seconds = int(window_seconds)
        self._nonces: Set[str] = set()

    def sign(self, message_type: str, nonce: str, timestamp: int, payload: Dict[str, Any]) -> str:
        body = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
        value = f"{message_type}.{nonce}.{timestamp}.{sha256(body.encode()).hexdigest()}".encode("utf-8")
        return hmac.new(self.secret, value, sha256).hexdigest()

    def verify(self, message: Dict[str, Any]) -> BridgeDecision:
        try:
            message_type = str(message["type"])
            nonce = str(message["nonce"])
            timestamp = int(message["timestamp"])
            signature = str(message["signature"])
            payload = message.get("payload", {})
        except (KeyError, TypeError, ValueError):
            return BridgeDecision(False, "missing_fields")
        if abs(int(time.time()) - timestamp) > self.window_seconds:
            return BridgeDecision(False, "timestamp_out_of_window")
        if nonce in self._nonces:
            return BridgeDecision(False, "nonce_replay")
        expected = self.sign(message_type, nonce, timestamp, payload)
        if not hmac.compare_digest(expected, signature):
            return BridgeDecision(False, "bad_signature")
        self._nonces.add(nonce)
        if len(self._nonces) > 5000:
            self._nonces.clear()
        return BridgeDecision(True)
