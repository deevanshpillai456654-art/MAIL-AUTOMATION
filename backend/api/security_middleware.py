"""
API Security Middleware
====================

Security middleware for API:
- Request sanitization
- SQL injection prevention
- XSS prevention
- Rate limiting integration
- API key validation
"""

import re
import logging
import hashlib
from typing import Optional, Callable
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("api.security")


class RequestSanitizer:
    """Request input sanitizer"""
    
    # SQL injection patterns
    SQL_PATTERNS = [
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE)\b)",
        r"(--|#|/\*|\*/)",
        r"(\bUNION\b.*\bSELECT\b)",
    ]
    
    # XSS patterns
    XSS_PATTERNS = [
        r"(<script|</script>|<iframe|</iframe>)",
        r"(javascript:)",
        r"(on\w+\s*=)",
    ]
    
    def __init__(self):
        self._sql_regex = [re.compile(p, re.IGNORECASE) for p in self.SQL_PATTERNS]
        self._xss_regex = [re.compile(p, re.IGNORECASE) for p in self.XSS_PATTERNS]
    
    def sanitize(self, value: str) -> str:
        """Sanitize input value"""
        if not isinstance(value, str):
            return value
        
        # Check SQL injection
        for regex in self._sql_regex:
            if regex.search(value):
                logger.warning(f"SQL injection attempt: {value[:50]}")
                raise HTTPException(status_code=400, detail="Invalid input")
        
        # Check XSS
        for regex in self._xss_regex:
            if regex.search(value):
                logger.warning(f"XSS attempt: {value[:50]}")
                raise HTTPException(status_code=400, detail="Invalid input")
        
        return value
    
    def sanitize_dict(self, data: dict) -> dict:
        """Sanitize dictionary input"""
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.sanitize(value)
            elif isinstance(value, dict):
                result[key] = self.sanitize_dict(value)
            elif isinstance(value, list):
                result[key] = [self.sanitize(v) if isinstance(v, str) else v for v in value]
            else:
                result[key] = value
        return result


class APIKeyValidator:
    """API key validation"""
    
    def __init__(self):
        self._valid_keys: set = set()
        self._key_metadata: dict = {}
    
    def add_key(self, api_key: str, metadata: dict = None):
        """Add valid API key"""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        self._valid_keys.add(key_hash)
        if metadata:
            self._key_metadata[key_hash] = metadata
    
    def validate(self, api_key: str) -> bool:
        """Validate API key"""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        return key_hash in self._valid_keys
    
    def remove_key(self, api_key: str):
        """Remove API key"""
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        self._valid_keys.discard(key_hash)
        self._key_metadata.pop(key_hash, None)


# Global sanitizer
_sanitizer = RequestSanitizer()


def get_sanitizer() -> RequestSanitizer:
    """Get global sanitizer"""
    return _sanitizer


__all__ = ["RequestSanitizer", "APIKeyValidator", "get_sanitizer"]