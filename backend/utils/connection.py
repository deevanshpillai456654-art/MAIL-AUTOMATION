"""
Connection Validator for Browser Extensions
Validates extension/add-in connections to local service
"""

import hashlib
import os
import time
import secrets
from typing import Optional, Dict
from datetime import datetime, timedelta


class ConnectionValidator:
    def __init__(self):
        self.valid_tokens: Dict[str, Dict] = {}
        self.max_connections = 100
        self.token_expiry_seconds = 3600

    def generate_token(self, client_id: str) -> str:
        token = secrets.token_urlsafe(32)

        self.valid_tokens[token] = {
            "client_id": client_id,
            "created_at": datetime.now(),
            "last_used": datetime.now(),
            "requests": 0
        }

        self._cleanup_old_tokens()

        return token

    def validate_token(self, token: str, client_id: str = None) -> bool:
        if token not in self.valid_tokens:
            return False

        token_data = self.valid_tokens[token]

        age = datetime.now() - token_data["created_at"]
        if age > timedelta(seconds=self.token_expiry_seconds):
            del self.valid_tokens[token]
            return False

        if client_id and token_data["client_id"] != client_id:
            return False

        token_data["last_used"] = datetime.now()
        token_data["requests"] += 1

        return True

    def revoke_token(self, token: str):
        if token in self.valid_tokens:
            del self.valid_tokens[token]

    def _cleanup_old_tokens(self):
        now = datetime.now()
        expired = [
            t for t, data in self.valid_tokens.items()
            if now - data["created_at"] > timedelta(seconds=self.token_expiry_seconds)
        ]

        for t in expired:
            del self.valid_tokens[t]

        while len(self.valid_tokens) > self.max_connections:
            oldest = min(self.valid_tokens.items(), key=lambda x: x[1]["created_at"])
            del self.valid_tokens[oldest[0]]

    def get_stats(self) -> Dict:
        return {
            "active_tokens": len(self.valid_tokens),
            "max_tokens": self.max_connections,
            "expiry_seconds": self.token_expiry_seconds
        }


class ExtensionHandshake:
    SECRET_KEY = os.environ.get("AIO_EXTENSION_SECRET", "ai_email_organizer_dev_only")

    @staticmethod
    def create_handshake(client_id: str, timestamp: int) -> str:
        data = f"{client_id}:{timestamp}:{ExtensionHandshake.SECRET_KEY}"
        return hashlib.sha256(data.encode()).hexdigest()

    @staticmethod
    def verify_handshake(client_id: str, timestamp: int, signature: str) -> bool:
        if abs(time.time() - timestamp) > 300:
            return False

        expected = ExtensionHandshake.create_handshake(client_id, timestamp)
        return secrets.compare_digest(expected, signature)


class PortScanner:
    SAFE_PORTS = list(range(4597, 4510))
    TIMEOUT = 0.5

    @staticmethod
    def scan_ports() -> Dict[int, bool]:
        import socket

        results = {}
        for port in PortScanner.SAFE_PORTS:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(PortScanner.TIMEOUT)
                result = sock.connect_ex(("127.0.0.1", port))
                sock.close()
                results[port] = result == 0
            except Exception:
                results[port] = False

        return results

    @staticmethod
    def find_first_available() -> Optional[int]:
        results = PortScanner.scan_ports()
        for port, is_used in results.items():
            if not is_used:
                return port
        return None


connection_validator = ConnectionValidator()
handshake = ExtensionHandshake()


def validate_extension_connection(token: str, client_id: str = None) -> bool:
    return connection_validator.validate_token(token, client_id)


def create_extension_token(client_id: str) -> str:
    return connection_validator.generate_token(client_id)


def get_connection_stats() -> Dict:
    return connection_validator.get_stats()