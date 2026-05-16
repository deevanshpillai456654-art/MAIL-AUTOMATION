"""HMAC request signing and nonce replay protection."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class SignatureDecision:
    ok: bool
    reason: str


class NonceReplayGuard:
    def __init__(self, ttl_seconds: int = 300, max_entries: int = 10000):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._seen: "OrderedDict[str, float]" = OrderedDict()

    def _prune(self, now: float) -> None:
        cutoff = now - self.ttl_seconds
        for key, ts in list(self._seen.items()):
            if ts < cutoff or len(self._seen) > self.max_entries:
                self._seen.pop(key, None)
            else:
                break

    def has_seen(self, nonce: str, now: float | None = None) -> bool:
        now = now or time.time()
        self._prune(now)
        return nonce in self._seen

    def store(self, nonce: str, now: float | None = None) -> None:
        now = now or time.time()
        self._prune(now)
        self._seen[nonce] = now

    def check_and_store(self, nonce: str, now: float | None = None) -> bool:
        if self.has_seen(nonce, now):
            return False
        self.store(nonce, now)
        return True


class RequestSigner:
    def __init__(self, secret: str | None = None, window_seconds: int = 300):
        self.secret = secret or os.environ.get("REQUEST_SIGNING_SECRET", "")
        self.window_seconds = int(os.environ.get("REQUEST_SIGNING_WINDOW_SECONDS", window_seconds))
        self.nonces = NonceReplayGuard(self.window_seconds)

    @staticmethod
    def body_hash(body: bytes) -> str:
        return hashlib.sha256(body or b"").hexdigest()

    @staticmethod
    def canonical(method: str, path: str, timestamp: str, nonce: str, body_hash: str) -> str:
        return "\n".join([method.upper(), path, timestamp, nonce, body_hash])

    def sign(self, method: str, path: str, timestamp: str, nonce: str, body: bytes) -> str:
        if not self.secret:
            raise ValueError("request signing secret is not configured")
        message = self.canonical(method, path, timestamp, nonce, self.body_hash(body)).encode("utf-8")
        return hmac.new(self.secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    def verify(self, method: str, path: str, headers: Dict[str, str], body: bytes) -> SignatureDecision:
        if not self.secret:
            return SignatureDecision(False, "signing_secret_missing")
        ts = headers.get("x-aiemail-timestamp", "")
        nonce = headers.get("x-aiemail-nonce", "")
        signature = headers.get("x-aiemail-signature", "")
        if not ts or not nonce or not signature:
            return SignatureDecision(False, "signature_headers_missing")
        if len(nonce) < 6 or len(nonce) > 160 or not all(ch.isalnum() or ch in "-_.:" for ch in nonce):
            return SignatureDecision(False, "invalid_nonce")
        try:
            ts_value = float(ts)
        except ValueError:
            return SignatureDecision(False, "invalid_timestamp")
        now = time.time()
        if abs(now - ts_value) > self.window_seconds:
            return SignatureDecision(False, "timestamp_outside_window")
        if self.nonces.has_seen(nonce, now):
            return SignatureDecision(False, "nonce_replay")
        expected = self.sign(method, path, ts, nonce, body)
        if not hmac.compare_digest(expected, signature):
            return SignatureDecision(False, "bad_signature")
        self.nonces.store(nonce, now)
        return SignatureDecision(True, "ok")


__all__ = ["RequestSigner", "SignatureDecision", "NonceReplayGuard"]
