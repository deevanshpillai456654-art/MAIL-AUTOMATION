"""
Data Loss Prevention Engine
============================

Enterprise DLP for PII/PHI/PCI detection:
- Pattern detection (SSN, CC, etc)
- Content scanning
- Outbound validation
- Quarantine
- Audit logging
"""

import logging
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("dlp_engine")


class DLPPattern(Enum):
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    BANK_ACCOUNT = "bank_account"
    API_KEY = "api_key"
    PASSWORD = "password"
    PHI = "phi"
    EMAIL = "email"
    PHONE = "phone"
    DRIVERS_LICENSE = "drivers_license"
    PASSPORT = "passport"


class DLPSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class DLPViolation:
    """DLP violation record"""
    violation_id: str
    pattern_type: DLPPattern
    severity: DLPSeverity
    content_preview: str
    location: str
    detected_at: float = field(default_factory=time.time)
    quarantined: bool = False
    resolved: bool = False


@dataclass
class DLPConfig:
    """DLP configuration"""
    enable_ssn: bool = True
    enable_credit_card: bool = True
    enable_bank_account: bool = True
    enable_api_key: bool = True
    enable_password: bool = True
    enable_phi: bool = True

    ssn_patterns: List[str] = field(default_factory=lambda: [
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"
    ])

    credit_card_patterns: List[str] = field(default_factory=lambda: [
        r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        r"\b\d{4}\s\d{4}\s\d{4}\s\d{4}\b"
    ])

    bank_account_patterns: List[str] = field(default_factory=lambda: [
        r"\b\d{8,17}\b"
    ])

    api_key_patterns: List[str] = field(default_factory=lambda: [
        r"sk-[a-zA-Z0-9]{20,}",
        r"api[_-]?key['\"]?\s*[:=]\s*['\"]?[a-zA-Z0-9]{20,}"
    ])

    password_patterns: List[str] = field(default_factory=lambda: [
        r"password['\"]?\s*[:=]\s*['\"]?[^\s]{8,}",
        r"passwd['\"]?\s*[:=]\s*['\"]?[^\s]{8,}"
    ])

    phi_patterns: List[str] = field(default_factory=lambda: [
        r"\b(?:diagnosis|treatment|prescription|medication)\s*[:\-]\s*[^\n]{10,}",
        r"\b(?:patient|medical)\s+(?:record|id|note)\b"
    ])


class DLPEngine:
    """Data Loss Prevention Engine"""

    def __init__(self, config: Optional[DLPConfig] = None):
        self._config = config or DLPConfig()
        self._patterns: Dict[DLPPattern, List[re.Pattern]] = {}
        self._violations: deque = deque(maxlen=10000)
        self._quarantine: Dict[str, DLPViolation] = {}
        self._stats = defaultdict(int)
        self._lock = threading.RLock()

        self._compile_patterns()

        logger.info("DLP engine initialized")

    def _compile_patterns(self):
        """Compile regex patterns"""
        if self._config.enable_ssn:
            self._patterns[DLPPattern.SSN] = [
                re.compile(p, re.IGNORECASE)
                for p in self._config.ssn_patterns
            ]

        if self._config.enable_credit_card:
            self._patterns[DLPPattern.CREDIT_CARD] = [
                re.compile(p, re.IGNORECASE)
                for p in self._config.credit_card_patterns
            ]

        if self._config.enable_bank_account:
            self._patterns[DLPPattern.BANK_ACCOUNT] = [
                re.compile(p)
                for p in self._config.bank_account_patterns
            ]

        if self._config.enable_api_key:
            self._patterns[DLPPattern.API_KEY] = [
                re.compile(p, re.IGNORECASE)
                for p in self._config.api_key_patterns
            ]

        if self._config.enable_password:
            self._patterns[DLPPattern.PASSWORD] = [
                re.compile(p, re.IGNORECASE)
                for p in self._config.password_patterns
            ]

        if self._config.enable_phi:
            self._patterns[DLPPattern.PHI] = [
                re.compile(p, re.IGNORECASE)
                for p in self._config.phi_patterns
            ]

    def scan_content(self,
                  content: str,
                  content_type: str = "text",
                  sender: str = "",
                  recipient: str = "") -> List[DLPViolation]:
        """Scan content for DLP violations"""
        violations = []

        with self._lock:
            for pattern_type, patterns in self._patterns.items():
                for pattern in patterns:
                    matches = pattern.finditer(content)

                    for match in matches:
                        violation = self._create_violation(
                            pattern_type,
                            content[max(0, match.start()-10):min(len(content), match.end()+10)],
                            content_type,
                            sender,
                            recipient
                        )
                        violations.append(violation)
                        self._violations.append(violation)
                        self._stats[pattern_type.value] += 1

        return violations

    def _create_violation(self,
                        pattern_type: DLPPattern,
                        content_preview: str,
                        content_type: str,
                        sender: str,
                        recipient: str) -> DLPViolation:
        """Create violation record"""
        violation_id = str(uuid.uuid4())

        severity = DLPSeverity.HIGH
        if pattern_type in [DLPPattern.CREDIT_CARD, DLPPattern.BANK_ACCOUNT]:
            severity = DLPSeverity.CRITICAL
        elif pattern_type in [DLPPattern.SSN, DLPPattern.PHI]:
            severity = DLPSeverity.CRITICAL
        elif pattern_type in [DLPPattern.API_KEY, DLPPattern.PASSWORD]:
            severity = DLPSeverity.CRITICAL

        return DLPViolation(
            violation_id=violation_id,
            pattern_type=pattern_type,
            severity=severity,
            content_preview=content_preview[:50],
            location=f"{content_type}:{sender}:{recipient}"
        )

    def quarantine_violation(self, violation_id: str) -> bool:
        """Quarantine violation"""
        with self._lock:
            for v in self._violations:
                if v.violation_id == violation_id:
                    v.quarantined = True
                    self._quarantine[violation_id] = v
                    return True
            return False

    def get_violations(self,
                     severity: Optional[DLPSeverity] = None,
                     unresolved_only: bool = False) -> List[DLPViolation]:
        """Get violations"""
        with self._lock:
            violations = list(self._violations)

            if severity:
                violations = [v for v in violations if v.severity == severity]

            if unresolved_only:
                violations = [v for v in violations if not v.resolved]

            return violations

    def resolve_violation(self, violation_id: str) -> bool:
        """Resolve violation"""
        with self._lock:
            for v in self._violations:
                if v.violation_id == violation_id:
                    v.resolved = True
                    return True
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get DLP statistics"""
        with self._lock:
            return {
                "total_violations": len(self._violations),
                "quarantined": len(self._quarantine),
                "by_pattern": dict(self._stats)
            }

    def redact_content(self, content: str) -> str:
        """Redact sensitive content"""
        redacted = content

        if DLPPattern.CREDIT_CARD in self._patterns:
            for pattern in self._patterns[DLPPattern.CREDIT_CARD]:
                redacted = pattern.sub("[REDACTED_CC]", redacted)

        if DLPPattern.SSN in self._patterns:
            for pattern in self._patterns[DLPPattern.SSN]:
                redacted = pattern.sub("[REDACTED_SSN]", redacted)

        if DLPPattern.API_KEY in self._patterns:
            for pattern in self._patterns[DLPPattern.API_KEY]:
                redacted = pattern.sub("[REDACTED_KEY]", redacted)

        if DLPPattern.PASSWORD in self._patterns:
            for pattern in self._patterns[DLPPattern.PASSWORD]:
                redacted = pattern.sub("[REDACTED_PWD]", redacted)

        return redacted


class TenantBoundaryGuard:
    """Tenant boundary guard for multi-tenant isolation"""

    def __init__(self):
        self._namespaces: Set[str] = set()
        self._boundary_violations: List[Dict[str, Any]] = []
        self._lock = threading.RLock()

        logger.info("Tenant boundary guard initialized")

    def register_namespace(self, tenant_id: str):
        """Register tenant namespace"""
        with self._lock:
            self._namespaces.add(tenant_id)

    def validate_query(self,
                      tenant_id: str,
                      query: str,
                      params: Dict[str, Any]) -> Tuple[bool, str]:
        """Validate query doesn't cross tenant boundary"""
        with self._lock:
            query_lower = query.lower()

            for other_tenant in self._namespaces:
                if other_tenant != tenant_id:
                    if other_tenant in query_lower:
                        self._boundary_violations.append({
                            "tenant_id": tenant_id,
                            "attempted_tenant": other_tenant,
                            "query": query,
                            "timestamp": time.time()
                        })
                        return False, f"boundary_violation: {other_tenant}"

            param_tenant = params.get("tenant_id")
            if param_tenant and param_tenant != tenant_id:
                return False, f"invalid_tenant_in_params: {param_tenant}"

            return True, "allowed"

    def validate_vector_query(self,
                            tenant_id: str,
                            filter_clause: str) -> Tuple[bool, str]:
        """Validate vector query doesn't access other tenant data"""
        with self._lock:
            if filter_clause and tenant_id not in filter_clause:
                return False, "missing_tenant_filter"

            for other_tenant in self._namespaces:
                if other_tenant != tenant_id and other_tenant in filter_clause:
                    return False, f"cross_tenant_filter: {other_tenant}"

            return True, "allowed"

    def get_boundary_violations(self) -> List[Dict[str, Any]]:
        """Get boundary violations"""
        with self._lock:
            return list(self._boundary_violations)


_global_dlp_engine: Optional[DLPEngine] = None
_global_boundary_guard: Optional[TenantBoundaryGuard] = None


def get_dlp_engine() -> DLPEngine:
    """Get global DLP engine"""
    global _global_dlp_engine
    if _global_dlp_engine is None:
        _global_dlp_engine = DLPEngine()
    return _global_dlp_engine


def get_boundary_guard() -> TenantBoundaryGuard:
    """Get global boundary guard"""
    global _global_boundary_guard
    if _global_boundary_guard is None:
        _global_boundary_guard = TenantBoundaryGuard()
    return _global_boundary_guard


__all__ = [
    "DLPPattern",
    "DLPSeverity",
    "DLPViolation",
    "DLPConfig",
    "DLPEngine",
    "TenantBoundaryGuard",
    "get_dlp_engine",
    "get_boundary_guard"
]
