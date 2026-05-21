"""
Enterprise Policy Engine - Phase 17
=================================

Comprehensive enterprise policy features:
- RetentionPolicies: Per-folder, time-based, action-based retention
- LegalHoldSystem: Legal holds, hold exceptions, multi-hold support
- DLPScanner: Credit card, SSN, API key, password detection
- PIIMaskingEngine: Email, phone, address, name masking
- EnterpriseComplianceFramework: GDPR, HIPAA, SOX compliance
- PolicyEnforcementEngine: Pre/post-processing enforcement
- AttachmentPolicyEngine: Size limits, type restrictions
- EmailRetentionAutomation: Auto-archival, auto-deletion

Key requirements:
- All policies must be enforceable
- Audit logs for all policy actions
- Compliance with enterprise regulations
- PII must be masked where required
- Retention must be automated
"""

import os
import re
import time
import json
import hashlib
import logging
import threading
import sqlite3
import secrets
import fnmatch
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set, Callable, Tuple
from enum import Enum
from collections import deque
from contextlib import contextmanager

logger = logging.getLogger("enterprise.policy")


class PolicyType(Enum):
    RETENTION = "retention"
    LEGAL_HOLD = "legal_hold"
    DLP = "dlp"
    PII_MASKING = "pii_masking"
    ATTACHMENT = "attachment"
    COMPLIANCE = "compliance"
    ENFORCEMENT = "enforcement"


class PolicyAction(Enum):
    KEEP = "keep"
    DELETE = "delete"
    ARCHIVE = "archive"
    HOLD = "hold"
    MASK = "mask"
    QUARANTINE = "quarantine"
    ALERT = "alert"
    LOG = "log"
    BLOCK = "block"
    WARN = "warn"
    NOTIFY = "notify"


class RetentionPeriod(Enum):
    DAILY = 1
    DAYS_7 = 7
    DAYS_30 = 30
    DAYS_90 = 90
    DAYS_180 = 180
    DAYS_365 = 365
    YEARS_3 = 1095
    YEARS_7 = 2555
    FOREVER = -1


class DLPSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ComplianceRegulation(Enum):
    GDPR = "gdpr"
    HIPAA = "hipaa"
    SOX = "sox"
    PCI_DSS = "pci_dss"
    CCPA = "ccpa"
    CUSTOM = "custom"


class HoldStatus(Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    RELEASED = "released"
    PENDING = "pending"


class EnforcementPoint(Enum):
    PRE_SEND = "pre_send"
    PRE_RECEIVE = "pre_receive"
    POST_RECEIVE = "post_receive"
    POST_STORAGE = "post_storage"
    PRE_ARCHIVE = "pre_archive"
    PRE_DELETE = "pre_delete"


@dataclass
class RetentionPolicy:
    policy_id: str
    name: str
    folder_pattern: str
    retention_days: int
    action_on_expiry: PolicyAction
    exclude_flagged: bool = False
    exclude_dl: bool = False
    exclude_legal_hold: bool = True
    is_active: bool = True
    schedule: str = "daily"
    created_at: float = field(default_factory=time.time)
    created_by: str = "system"


@dataclass
class LegalHold:
    hold_id: str
    name: str
    account_ids: List[int]
    folder_patterns: List[str]
    sender_patterns: List[str]
    keywords: List[str]
    date_range_start: float
    date_range_end: Optional[float]
    start_date: float
    end_date: Optional[float]
    created_by: str
    status: HoldStatus = HoldStatus.ACTIVE
    hold_type: str = "general"
    priority: int = 0


@dataclass
class DLPRule:
    rule_id: str
    name: str
    pattern: str
    pattern_type: str
    severity: DLPSeverity
    actions: List[PolicyAction]
    notify: List[str]
    is_active: bool = True
    regulation: Optional[ComplianceRegulation] = None


@dataclass
class PIIDetection:
    pii_type: str
    value: str
    start_index: int
    end_index: int
    is_masked: bool = False
    original_value: str = ""


@dataclass
class PIIMaskRule:
    rule_id: str
    name: str
    pii_types: List[str]
    mask_pattern: str
    action: PolicyAction
    is_active: bool = True


@dataclass
class CompliancePolicy:
    policy_id: str
    name: str
    regulation: ComplianceRegulation
    requirements: List[str]
    enforcement_enabled: bool = True
    alert_enabled: bool = True
    reporting_enabled: bool = True


@dataclass
class AttachmentPolicy:
    policy_id: str
    name: str
    max_size_bytes: int
    allowed_types: List[str]
    blocked_types: List[str]
    action: PolicyAction
    is_active: bool = True
    enforce_on_receive: bool = True
    enforce_on_send: bool = False


@dataclass
class PolicyAuditLog:
    log_id: str
    timestamp: float
    policy_type: PolicyType
    policy_id: str
    action: PolicyAction
    email_id: Optional[int]
    account_id: int
    details: str
    result: str
    user: str = "system"


@dataclass
class PolicyViolation:
    violation_id: str
    timestamp: float
    policy_type: PolicyType
    policy_id: str
    severity: str
    email_id: Optional[int]
    account_id: int
    description: str
    action_taken: PolicyAction
    notified: bool = False


class RetentionPolicies:
    """Per-folder retention rules with time-based deletion"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._policies: Dict[str, RetentionPolicy] = {}
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS retention_policies (
                policy_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                folder_pattern TEXT,
                retention_days INTEGER,
                action_on_expiry TEXT,
                exclude_flagged INTEGER DEFAULT 0,
                exclude_dl INTEGER DEFAULT 0,
                exclude_legal_hold INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                schedule TEXT DEFAULT 'daily',
                created_at REAL,
                created_by TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_retention (
                email_id INTEGER PRIMARY KEY,
                account_id INTEGER,
                policy_id TEXT,
                retention_expires_at REAL,
                is_on_legal_hold INTEGER DEFAULT 0,
                last_retention_check REAL
            )
        """)
        conn.commit()
        conn.close()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_policy(self, name: str, folder_pattern: str, retention_days: int,
                  action_on_expiry: PolicyAction, schedule: str = "daily",
                  exclude_flagged: bool = False, exclude_dl: bool = False,
                  exclude_legal_hold: bool = True, created_by: str = "system") -> str:
        with self._lock:
            policy_id = f"ret_{secrets.token_hex(8)}"
            policy = RetentionPolicy(
                policy_id=policy_id,
                name=name,
                folder_pattern=folder_pattern,
                retention_days=retention_days,
                action_on_expiry=action_on_expiry,
                schedule=schedule,
                exclude_flagged=exclude_flagged,
                exclude_dl=exclude_dl,
                exclude_legal_hold=exclude_legal_hold,
                created_by=created_by
            )
            self._policies[policy_id] = policy

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO retention_policies
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    policy_id, name, folder_pattern, retention_days,
                    action_on_expiry.value, int(exclude_flagged), int(exclude_dl),
                    int(exclude_legal_hold), int(policy.is_active),
                    schedule, policy.created_at, created_by
                ))
                conn.commit()

            logger.info(f"Retention policy created: {name}")
            return policy_id

    def apply_retention(self, email: Dict, account_id: int,
                      is_on_legal_hold: bool = False) -> PolicyAction:
        folder = email.get("folder", "")
        received_at = email.get("received_at", time.time())

        if is_on_legal_hold:
            return PolicyAction.HOLD

        for policy in self._policies.values():
            if not policy.is_active:
                continue

            if self._matches_pattern(folder, policy.folder_pattern):
                if policy.exclude_flagged and email.get("flagged", False):
                    continue
                if policy.exclude_dl and email.get("is_dl", False):
                    continue

                age_days = (time.time() - received_at) / 86400

                if age_days > policy.retention_days:
                    return policy.action_on_expiry

        return PolicyAction.KEEP

    def _matches_pattern(self, text: str, pattern: str) -> bool:
        if not pattern or pattern == "*" or pattern == "all":
            return True
        if "*" in pattern:
            return fnmatch.fnmatch(text.lower(), pattern.lower())
        return pattern.lower() in text.lower()

    def get_policies(self) -> List[RetentionPolicy]:
        return list(self._policies.values())

    def delete_policy(self, policy_id: str) -> bool:
        if policy_id in self._policies:
            del self._policies[policy_id]
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM retention_policies WHERE policy_id = ?", (policy_id,))
                conn.commit()
            return True
        return False


class LegalHoldSystem:
    """Legal hold with multi-hold support and hold exception management"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._holds: Dict[str, LegalHold] = self._load_holds()
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS legal_holds (
                hold_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                account_ids TEXT,
                folder_patterns TEXT,
                sender_patterns TEXT,
                keywords TEXT,
                date_range_start REAL,
                date_range_end REAL,
                start_date REAL,
                end_date REAL,
                created_by TEXT,
                status TEXT,
                hold_type TEXT,
                priority INTEGER DEFAULT 0
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hold_exceptions (
                exception_id TEXT PRIMARY KEY,
                hold_id TEXT,
                email_id INTEGER,
                reason TEXT,
                created_by TEXT,
                created_at REAL
            )
        """)
        conn.commit()
        conn.close()

    def _load_holds(self) -> Dict[str, LegalHold]:
        holds = {}
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM legal_holds WHERE status = 'active' LIMIT 10000")
                for row in cursor.fetchall():
                    holds[row["hold_id"]] = LegalHold(
                        hold_id=row["hold_id"],
                        name=row["name"],
                        account_ids=json.loads(row["account_ids"]),
                        folder_patterns=json.loads(row["folder_patterns"]),
                        sender_patterns=json.loads(row["sender_patterns"]),
                        keywords=json.loads(row["keywords"]),
                        date_range_start=row["date_range_start"],
                        date_range_end=row["date_range_end"],
                        start_date=row["start_date"],
                        end_date=row["end_date"],
                        created_by=row["created_by"],
                        status=HoldStatus(row["status"]),
                        hold_type=row["hold_type"],
                        priority=row["priority"]
                    )
        except Exception:
            pass
        return holds

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_hold(self, name: str, account_ids: List[int],
                    folder_patterns: List[str], sender_patterns: List[str],
                    keywords: List[str], date_range_start: float,
                    date_range_end: Optional[float], created_by: str,
                    hold_type: str = "general") -> str:
        with self._lock:
            hold_id = f"hold_{secrets.token_hex(8)}"
            hold = LegalHold(
                hold_id=hold_id,
                name=name,
                account_ids=account_ids,
                folder_patterns=folder_patterns,
                sender_patterns=sender_patterns,
                keywords=keywords,
                date_range_start=date_range_start,
                date_range_end=date_range_end,
                start_date=time.time(),
                end_date=date_range_end,
                created_by=created_by,
                status=HoldStatus.ACTIVE,
                hold_type=hold_type
            )
            self._holds[hold_id] = hold

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO legal_holds
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    hold_id, name, json.dumps(account_ids),
                    json.dumps(folder_patterns), json.dumps(sender_patterns),
                    json.dumps(keywords), date_range_start, date_range_end or 0,
                    hold.start_date, hold.end_date or 0, created_by,
                    hold.status.value, hold_type, hold.priority
                ))
                conn.commit()

            logger.info(f"Legal hold created: {name}")
            return hold_id

    def check_legal_hold(self, email: Dict, account_id: int) -> Tuple[bool, List[str]]:
        matching_holds = []

        for hold in self._holds.values():
            if hold.status != HoldStatus.ACTIVE:
                continue
            if account_id not in hold.account_ids:
                continue
            if not self._matches_any_pattern(email.get("folder", ""), hold.folder_patterns):
                continue
            if not self._matches_any_pattern(email.get("from", ""), hold.sender_patterns):
                continue
            body = email.get("body_text", "")
            if any(kw.lower() in body.lower() for kw in hold.keywords):
                matching_holds.append(hold.hold_id)
                continue
            received_at = email.get("received_at", time.time())
            if hold.date_range_start and received_at < hold.date_range_start:
                continue
            if hold.date_range_end and received_at > hold.date_range_end:
                continue
            matching_holds.append(hold.hold_id)

        return len(matching_holds) > 0, matching_holds

    def release_hold(self, hold_id: str, released_by: str) -> bool:
        if hold_id in self._holds:
            self._holds[hold_id].status = HoldStatus.RELEASED
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE legal_holds SET status = 'released'
                    WHERE hold_id = ?
                """, (hold_id,))
                conn.commit()
            return True
        return False

    def get_active_holds(self) -> List[LegalHold]:
        return [h for h in self._holds.values() if h.status == HoldStatus.ACTIVE]

    def _matches_any_pattern(self, text: str, patterns: List[str]) -> bool:
        if not patterns:
            return True
        return any(self._matches_pattern(text, p) for p in patterns)

    def _matches_pattern(self, text: str, pattern: str) -> bool:
        if not pattern or pattern == "*":
            return True
        if "*" in pattern:
            return fnmatch.fnmatch(text.lower(), pattern.lower())
        return pattern.lower() in text.lower()


class DLPScanner:
    """Data Loss Prevention scanner with credit card, SSN, API key detection"""

    CREDIT_CARD_PATTERNS = [
        r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        r"\b\d{4}\s\d{4}\s\d{4}\s\d{4}\b",
    ]

    SSN_PATTERNS = [
        r"\b\d{3}-\d{2}-\d{4}\b",
        r"\b\d{3} \d{2} \d{4}\b",
    ]

    API_KEY_PATTERNS = [
        r"(?i)(api[_-]?key['\"]?\s*[:=]\s*['\"])[a-zA-Z0-9_\-]{20,}",
        r"(?i)(secret[_-]?key['\"]?\s*[:=]\s*['\"])[a-zA-Z0-9_\-]{20,}",
        r"(?i)(access[_-]?token['\"]?\s*[:=]\s*['\"])[a-zA-Z0-9_\-]{20,}",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"\b(xox[abobarps]+\d+-[a-zA-Z0-9-]+)\b",
    ]

    PASSWORD_PATTERNS = [
        r"(?i)(password['\"]?\s*[:=]\s*['\"])[^\s]{6,}",
        r"(?i)(passwd['\"]?\s*[:=]\s*['\"])[^\s]{6,}",
        r"(?i)(pwd['\"]?\s*[:=]\s*['\"])[^\s]{6,}",
    ]

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._rules: Dict[str, DLPRule] = {}
        self._lock = threading.RLock()
        self._init_db()
        self._build_patterns()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dlp_rules (
                rule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                pattern TEXT,
                pattern_type TEXT,
                severity TEXT,
                actions TEXT,
                notify TEXT,
                is_active INTEGER DEFAULT 1,
                regulation TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dlp_violations (
                violation_id TEXT PRIMARY KEY,
                rule_id TEXT,
                email_id INTEGER,
                account_id INTEGER,
                detected_value TEXT,
                timestamp REAL,
                action_taken TEXT,
                notified INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def _build_patterns(self):
        self._patterns = {
            "credit_card": self.CREDIT_CARD_PATTERNS,
            "ssn": self.SSN_PATTERNS,
            "api_key": self.API_KEY_PATTERNS,
            "password": self.PASSWORD_PATTERNS,
        }

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_rule(self, name: str, pattern: str, pattern_type: str,
                  severity: DLPSeverity, actions: List[PolicyAction],
                  notify: List[str] = None,
                  regulation: ComplianceRegulation = None) -> str:
        with self._lock:
            rule_id = f"dlp_{secrets.token_hex(8)}"
            rule = DLPRule(
                rule_id=rule_id,
                name=name,
                pattern=pattern,
                pattern_type=pattern_type,
                severity=severity,
                actions=actions,
                notify=notify or [],
                regulation=regulation
            )
            self._rules[rule_id] = rule

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO dlp_rules
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rule_id, name, pattern, pattern_type, severity.value,
                    json.dumps([a.value for a in actions]),
                    json.dumps(notify or []), 1,
                    regulation.value if regulation else None
                ))
                conn.commit()

            logger.info(f"DLP rule created: {name}")
            return rule_id

    def scan_email(self, email: Dict) -> List[Dict]:
        violations = []
        text = f"{email.get('subject', '')} {email.get('body_text', '')}"

        for rule in self._rules.values():
            if not rule.is_active:
                continue

            matches = self._scan_pattern(text, rule.pattern, rule.pattern_type)
            if matches:
                violation = {
                    "rule_id": rule.rule_id,
                    "rule_name": rule.name,
                    "severity": rule.severity.value,
                    "matches": matches,
                    "actions": rule.actions,
                    "notify": rule.notify
                }
                violations.append(violation)

                self._log_violation(
                    email.get("id"), email.get("account_id"),
                    rule.rule_id, matches, rule.actions[0]
                )

        return violations

    def _scan_pattern(self, text: str, pattern: str, pattern_type: str) -> List[str]:
        matches = []
        try:
            if pattern_type == "regex":
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    matches.append(match.group())
            elif pattern_type == "keyword":
                for kw in pattern.split(","):
                    if kw.lower() in text.lower():
                        matches.append(kw)
            elif pattern_type == "exact":
                if pattern.lower() in text.lower():
                    matches.append(pattern)
        except Exception:
            pass
        return matches

    def _log_violation(self, email_id: int, account_id: int,
                    rule_id: str, matches: List[str], action: PolicyAction):
        violation_id = f"dlpv_{secrets.token_hex(8)}"
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO dlp_violations
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                violation_id, rule_id, email_id, account_id,
                json.dumps(matches), time.time(), action.value, 0
            ))
            conn.commit()

    def add_custom_regex(self, pattern: str, rule_name: str) -> str:
        return self.create_rule(
            name=rule_name,
            pattern=pattern,
            pattern_type="regex",
            severity=DLPSeverity.HIGH,
            actions=[PolicyAction.LOG, PolicyAction.ALERT]
        )


class PIIMaskingEngine:
    """PII masking with email, phone, address, name masking"""

    MASK_PATTERNS = {
        "email": (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "xxxx@xxxx.xxx"),
        "phone": (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "XXX-XXX-XXXX"),
        "ssn": (r"\b\d{3}-\d{2}-\d{4}\b", "XXX-XX-XXXX"),
        "credit_card": (r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b", "XXXX-XXXX-XXXX-XXXX"),
        "ip_address": (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "X.X.X.X"),
        "date_of_birth": (r"\b(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/\d{4}\b", "XX/XX/XXXX"),
        "address": (r"\b\d+\s+[\w\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl)\b", "[ADDRESS REDACTED]"),
    }

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._rules: Dict[str, PIIMaskRule] = {}
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pii_mask_rules (
                rule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                pii_types TEXT,
                mask_pattern TEXT,
                action TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pii_mask_logs (
                log_id TEXT PRIMARY KEY,
                email_id INTEGER,
                account_id INTEGER,
                pii_type TEXT,
                original_value TEXT,
                masked_value TEXT,
                timestamp REAL
            )
        """)
        conn.commit()
        conn.close()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_mask_rule(self, name: str, pii_types: List[str],
                        action: PolicyAction) -> str:
        with self._lock:
            rule_id = f"pii_{secrets.token_hex(8)}"
            rule = PIIMaskRule(
                rule_id=rule_id,
                name=name,
                pii_types=pii_types,
                mask_pattern="default",
                action=action
            )
            self._rules[rule_id] = rule

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO pii_mask_rules
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    rule_id, name, json.dumps(pii_types),
                    "default", action.value, 1
                ))
                conn.commit()

            logger.info(f"PII mask rule created: {name}")
            return rule_id

    def mask_content(self, text: str, pii_types: List[str] = None,
                   account_id: int = 0, email_id: int = 0) -> Tuple[str, List[PIIDetection]]:
        detections = []
        masked_text = text

        types_to_scan = pii_types if pii_types else list(self.MASK_PATTERNS.keys())

        for pii_type in types_to_scan:
            if pii_type not in self.MASK_PATTERNS:
                continue

            pattern, replacement = self.MASK_PATTERNS[pii_type]

            try:
                for match in re.finditer(pattern, masked_text, re.IGNORECASE):
                    detection = PIIDetection(
                        pii_type=pii_type,
                        value=match.group(),
                        start_index=match.start(),
                        end_index=match.end(),
                        is_masked=False,
                        original_value=match.group()
                    )
                    masked_text = masked_text[:match.start()] + replacement + masked_text[match.end():]
                    detection.is_masked = True
                    detections.append(detection)

                    if email_id:
                        self._log_mask(email_id, account_id, pii_type,
                                     detection.original_value, replacement)

            except Exception:
                continue

        return masked_text, detections

    def _log_mask(self, email_id: int, account_id: int, pii_type: str,
                 original: str, masked: str):
        log_id = f"piilog_{secrets.token_hex(8)}"
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pii_mask_logs
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (log_id, email_id, account_id, pii_type,
                  original, masked, time.time()))
            conn.commit()

    def detect_pii(self, text: str) -> List[PIIDetection]:
        detections = []

        for pii_type, (pattern, _) in self.MASK_PATTERNS.items():
            try:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    detections.append(PIIDetection(
                        pii_type=pii_type,
                        value=match.group(),
                        start_index=match.start(),
                        end_index=match.end()
                    ))
            except Exception:
                continue

        return detections


class EnterpriseComplianceFramework:
    """Compliance framework with GDPR, HIPAA, SOX templates"""

    GDPR_REQUIREMENTS = [
        "data_minimization",
        "consent_management",
        "right_to_erasure",
        "data_portability",
        "breach_notification",
    ]

    HIPAA_REQUIREMENTS = [
        "phi_protection",
        "access_control",
        "audit_trails",
        "encryption",
        "business_associate_agreement",
    ]

    SOX_REQUIREMENTS = [
        "financial_record_protection",
        "audit_trails",
        "access_control",
        "change_management",
        "data_retention",
    ]

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._policies: Dict[str, CompliancePolicy] = {}
        self._lock = threading.RLock()
        self._init_db()
        self._load_policies()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compliance_policies (
                policy_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                regulation TEXT,
                requirements TEXT,
                enforcement_enabled INTEGER DEFAULT 1,
                alert_enabled INTEGER DEFAULT 1,
                reporting_enabled INTEGER DEFAULT 1
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compliance_violations (
                violation_id TEXT PRIMARY KEY,
                policy_id TEXT,
                email_id INTEGER,
                account_id INTEGER,
                requirement TEXT,
                details TEXT,
                timestamp REAL,
                resolved INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    def _load_policies(self):
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM compliance_policies LIMIT 10000")
                for row in cursor.fetchall():
                    self._policies[row["policy_id"]] = CompliancePolicy(
                        policy_id=row["policy_id"],
                        name=row["name"],
                        regulation=ComplianceRegulation(row["regulation"]),
                        requirements=json.loads(row["requirements"]),
                        enforcement_enabled=bool(row["enforcement_enabled"]),
                        alert_enabled=bool(row["alert_enabled"]),
                        reporting_enabled=bool(row["reporting_enabled"])
                    )
        except Exception:
            pass

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_from_template(self, regulation: ComplianceRegulation) -> str:
        requirements_map = {
            ComplianceRegulation.GDPR: self.GDPR_REQUIREMENTS,
            ComplianceRegulation.HIPAA: self.HIPAA_REQUIREMENTS,
            ComplianceRegulation.SOX: self.SOX_REQUIREMENTS,
        }

        requirements = requirements_map.get(regulation, [])
        name = f"{regulation.value.upper()} Compliance Policy"

        return self.create_policy(name, regulation, requirements)

    def create_policy(self, name: str, regulation: ComplianceRegulation,
                     requirements: List[str]) -> str:
        with self._lock:
            policy_id = f"comp_{secrets.token_hex(8)}"
            policy = CompliancePolicy(
                policy_id=policy_id,
                name=name,
                regulation=regulation,
                requirements=requirements
            )
            self._policies[policy_id] = policy

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO compliance_policies
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    policy_id, name, regulation.value,
                    json.dumps(requirements), 1, 1, 1
                ))
                conn.commit()

            logger.info(f"Compliance policy created: {name}")
            return policy_id

    def get_policy(self, regulation: ComplianceRegulation) -> Optional[CompliancePolicy]:
        for policy in self._policies.values():
            if policy.regulation == regulation:
                return policy
        return None

    def check_compliance(self, regulation: ComplianceRegulation,
                        email: Dict) -> Tuple[bool, List[str]]:
        policy = self.get_policy(regulation)
        if not policy:
            return True, []

        violations = []

        if policy.regulation == ComplianceRegulation.GDPR:
            if "data_minimization" in policy.requirements:
                if len(email.get("body_text", "")) > 10000:
                    violations.append("GDPR: Excessive data in email body")

            if "right_to_erasure" in policy.requirements:
                pass

        elif policy.regulation == ComplianceRegulation.HIPAA:
            if "phi_protection" in policy.requirements:
                body = email.get("body_text", "")
                phi_patterns = [
                    r"\b\d{3}-\d{2}-\d{4}\b",
                    r"\b(medical|diagnosis|treatment|prescription)\b",
                ]
                for pattern in phi_patterns:
                    if re.search(pattern, body, re.IGNORECASE):
                        violations.append("HIPAA: Potential PHI detected")
                        break

        elif policy.regulation == ComplianceRegulation.SOX:
            if "financial_record_protection" in policy.requirements:
                body = email.get("body_text", "").lower()
                if "revenue" in body or "profit" in body or "$" in body:
                    pass

        return len(violations) == 0, violations


class PolicyEnforcementEngine:
    """Policy enforcement with pre/post-processing"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._enforcement_points: Dict[EnforcementPoint, List[Callable]] = {
            EnforcementPoint.PRE_SEND: [],
            EnforcementPoint.PRE_RECEIVE: [],
            EnforcementPoint.POST_RECEIVE: [],
            EnforcementPoint.POST_STORAGE: [],
            EnforcementPoint.PRE_ARCHIVE: [],
            EnforcementPoint.PRE_DELETE: [],
        }
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enforcement_logs (
                log_id TEXT PRIMARY KEY,
                enforcement_point TEXT,
                policy_id TEXT,
                email_id INTEGER,
                account_id INTEGER,
                action_taken TEXT,
                result TEXT,
                timestamp REAL
            )
        """)
        conn.commit()
        conn.close()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def register_enforcement(self, point: EnforcementPoint,
                          handler: Callable[[Dict], PolicyAction]):
        with self._lock:
            self._enforcement_points[point].append(handler)

    def enforce(self, point: EnforcementPoint, email: Dict,
              account_id: int) -> Tuple[PolicyAction, Dict]:
        action = PolicyAction.KEEP
        details = {}

        for handler in self._enforcement_points.get(point, []):
            try:
                result = handler(email)
                if isinstance(result, PolicyAction):
                    action = result
                elif isinstance(result, dict):
                    details.update(result)
                    if "action" in result:
                        action = result["action"]
            except Exception as e:
                logger.error(f"Enforcement error: {e}")

        self._log_enforcement(point, email.get("id"), account_id, action, details)

        return action, details

    def _log_enforcement(self, point: EnforcementPoint, email_id: int,
                     account_id: int, action: PolicyAction, details: Dict):
        log_id = f"enf_{secrets.token_hex(8)}"
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO enforcement_logs
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_id, point.value, details.get("policy_id", ""),
                email_id, account_id, action.value,
                json.dumps(details), time.time()
            ))
            conn.commit()


class AttachmentPolicyEngine:
    """Attachment policy with size limits, type restrictions"""

    EXECUTABLE_EXTENSIONS = {
        ".exe", ".dll", ".bat", ".cmd", ".ps1", ".sh", ".bash",
        ".vbs", ".js", ".jse", ".wsf", ".wsh", ".msi",
        ".scr", ".pif", ".com", ".jar", ".class",
        ".shx", ".app", ".bin", ".dmg", ".pkg",
    }

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._policies: Dict[str, AttachmentPolicy] = {}
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attachment_policies (
                policy_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                max_size_bytes INTEGER,
                allowed_types TEXT,
                blocked_types TEXT,
                action TEXT,
                is_active INTEGER DEFAULT 1,
                enforce_on_receive INTEGER DEFAULT 1,
                enforce_on_send INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_policy(self, name: str, max_size_bytes: int,
                     allowed_types: List[str], blocked_types: List[str],
                     action: PolicyAction) -> str:
        with self._lock:
            policy_id = f"att_{secrets.token_hex(8)}"
            policy = AttachmentPolicy(
                policy_id=policy_id,
                name=name,
                max_size_bytes=max_size_bytes,
                allowed_types=allowed_types,
                blocked_types=blocked_types,
                action=action
            )
            self._policies[policy_id] = policy

            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO attachment_policies
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    policy_id, name, max_size_bytes,
                    json.dumps(allowed_types), json.dumps(blocked_types),
                    action.value, 1, 1, 0
                ))
                conn.commit()

            logger.info(f"Attachment policy created: {name}")
            return policy_id

    def check_attachment(self, filename: str, size_bytes: int) -> Tuple[bool, PolicyAction]:
        ext = os.path.splitext(filename)[1].lower()

        for policy in self._policies.values():
            if not policy.is_active:
                continue

            if size_bytes > policy.max_size_bytes:
                return False, PolicyAction.BLOCK

            if policy.blocked_types and ext in policy.blocked_types:
                return False, PolicyAction.BLOCK

            if policy.allowed_types and ext not in policy.allowed_types:
                return False, PolicyAction.BLOCK

        if ext in self.EXECUTABLE_EXTENSIONS:
            return False, PolicyAction.BLOCK

        return True, PolicyAction.KEEP


class EmailRetentionAutomation:
    """Email retention automation with archival and auto-deletion"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS retention_schedule (
                schedule_id TEXT PRIMARY KEY,
                policy_id TEXT,
                schedule_type TEXT,
                cron_expression TEXT,
                is_active INTEGER DEFAULT 1,
                last_run REAL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS retention_notifications (
                notification_id TEXT PRIMARY KEY,
                email_id INTEGER,
                account_id INTEGER,
                notification_type TEXT,
                sent_at REAL,
                expires_at REAL
            )
        """)
        conn.commit()
        conn.close()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_schedule(self, policy_id: str, schedule_type: str) -> str:
        schedule_id = f"sched_{secrets.token_hex(8)}"
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO retention_schedule
                VALUES (?, ?, ?, ?, ?, ?)
            """, (schedule_id, policy_id, schedule_type, "", 1, 0))
            conn.commit()
        return schedule_id

    def schedule_retention_expiry_notifications(self, email_id: int,
                                                account_id: int,
                                                days_until_expiry: int) -> None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO retention_notifications
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                f"notif_{secrets.token_hex(8)}",
                email_id, account_id, "retention_reminder",
                time.time(), time.time() + (days_until_expiry * 86400)
            ))
            conn.commit()

    def get_expiring_emails(self, account_id: int, days: int) -> List[Dict]:
        emails = []
        expiry_time = time.time() + (days * 86400)

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM email_retention
                WHERE account_id = ? AND retention_expires_at <= ?
                AND is_on_legal_hold = 0
            """, (account_id, expiry_time))

            for row in cursor.fetchall():
                emails.append({
                    "email_id": row["email_id"],
                    "policy_id": row["policy_id"],
                    "retention_expires_at": row["retention_expires_at"]
                })

        return emails


class EnterprisePolicyEngine:
    """Comprehensive enterprise policy engine"""

    def __init__(self, data_dir: str):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "enterprise_policy.db"

        self.retention_policies = RetentionPolicies(str(self.db_path))
        self.legal_hold_system = LegalHoldSystem(str(self.db_path))
        self.dlp_scanner = DLPScanner(str(self.db_path))
        self.pii_masking = PIIMaskingEngine(str(self.db_path))
        self.compliance_framework = EnterpriseComplianceFramework(str(self.db_path))
        self.enforcement_engine = PolicyEnforcementEngine(str(self.db_path))
        self.attachment_policy = AttachmentPolicyEngine(str(self.db_path))
        self.retention_automation = EmailRetentionAutomation(str(self.db_path))

        self._lock = threading.RLock()
        self._init_db()

        self.on_policy_violation: Optional[Callable] = None
        self.on_retention_expired: Optional[Callable] = None
        self.on_legal_hold_match: Optional[Callable] = None

        logger.info("Enterprise Policy Engine initialized")

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS enterprise_audit_logs (
                log_id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                policy_type TEXT NOT NULL,
                policy_id TEXT,
                action TEXT NOT NULL,
                email_id INTEGER,
                account_id INTEGER,
                details TEXT,
                result TEXT,
                user TEXT
            )
        """)
        conn.commit()
        conn.close()

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def process_email(self, email: Dict, account_id: int,
                   enforcement_point: EnforcementPoint = EnforcementPoint.POST_RECEIVE) -> Dict:
        results = {
            "actions": [],
            "policy_violations": [],
            "dlp_violations": [],
            "pii_detections": [],
            "compliance_violations": [],
            "retention_action": PolicyAction.KEEP,
            "legal_hold": False,
            "masked_content": False,
        }

        is_on_hold, hold_ids = self.legal_hold_system.check_legal_hold(email, account_id)
        if is_on_hold:
            results["legal_hold"] = True
            results["retention_action"] = PolicyAction.HOLD
            results["hold_ids"] = hold_ids

            self._log_audit(
                PolicyType.LEGAL_HOLD, "", PolicyAction.HOLD,
                email.get("id"), account_id,
                f"Email on legal hold: {hold_ids}"
            )

        if not is_on_hold:
            retention_action = self.retention_policies.apply_retention(
                email, account_id, is_on_legal_hold=False
            )
            results["retention_action"] = retention_action
            if retention_action != PolicyAction.KEEP:
                results["actions"].append(retention_action)

        dlp_violations = self.dlp_scanner.scan_email(email)
        results["dlp_violations"] = dlp_violations
        for violation in dlp_violations:
            for action in violation.get("actions", []):
                if action == PolicyAction.BLOCK:
                    results["actions"].append(PolicyAction.QUARANTINE)
                    break
                elif action == PolicyAction.ALERT:
                    results["policy_violations"].append(violation)

        masked_body, detections = self.pii_masking.mask_content(
            email.get("body_text", ""), email_id=email.get("id", 0),
            account_id=account_id
        )
        if detections:
            results["pii_detections"] = detections
            results["masked_content"] = masked_body

        is_compliant, compl_violations = self.compliance_framework.check_compliance(
            ComplianceRegulation.GDPR, email
        )
        if not is_compliant:
            results["compliance_violations"] = compl_violations

        enforcement_action, enforcement_details = self.enforcement_engine.enforce(
            enforcement_point, email, account_id
        )
        if enforcement_action != PolicyAction.KEEP:
            results["actions"].append(enforcement_action)

        if email.get("attachments"):
            for attachment in email["attachments"]:
                allowed, action = self.attachment_policy.check_attachment(
                    attachment.get("filename", ""),
                    attachment.get("size", 0)
                )
                if not allowed:
                    results["actions"].append(action)

        return results

    def process_pre_send(self, email: Dict, account_id: int) -> Dict:
        return self.process_email(email, account_id, EnforcementPoint.PRE_SEND)

    def process_post_receive(self, email: Dict, account_id: int) -> Dict:
        return self.process_email(email, account_id, EnforcementPoint.POST_RECEIVE)

    def _log_audit(self, policy_type: PolicyType, policy_id: str,
                  action: PolicyAction, email_id: int, account_id: int,
                  details: str, result: str = "success", user: str = "system"):
        log_id = f"audit_{secrets.token_hex(8)}"
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO enterprise_audit_logs
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_id, time.time(), policy_type.value, policy_id,
                action.value, email_id, account_id, details, result, user
            ))
            conn.commit()

    def get_audit_logs(self, account_id: int = None,
                       limit: int = 100) -> List[PolicyAuditLog]:
        logs = []
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("""
                    SELECT * FROM enterprise_audit_logs
                    WHERE account_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (account_id, limit))
            else:
                cursor.execute("""
                    SELECT * FROM enterprise_audit_logs
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,))

            for row in cursor.fetchall():
                logs.append(PolicyAuditLog(
                    log_id=row["log_id"],
                    timestamp=row["timestamp"],
                    policy_type=PolicyType(row["policy_type"]),
                    policy_id=row["policy_id"],
                    action=PolicyAction(row["action"]),
                    email_id=row["email_id"],
                    account_id=row["account_id"],
                    details=row["details"],
                    result=row["result"],
                    user=row["user"]
                ))
        return logs

    def get_statistics(self) -> Dict:
        return {
            "retention_policies_count": len(self.retention_policies.get_policies()),
            "active_legal_holds": len(self.legal_hold_system.get_active_holds()),
            "dlp_rules_count": len(self.dlp_scanner._rules),
            "pii_mask_rules_count": len(self.pii_masking._rules),
            "compliance_policies_count": len(self.compliance_framework._policies),
            "attachment_policies_count": len(self.attachment_policy._policies),
        }

    def create_default_policies(self):
        self.retention_policies.create_policy(
            name="Inbox 30-day retention",
            folder_pattern="Inbox",
            retention_days=30,
            action_on_expiry=PolicyAction.ARCHIVE,
            schedule="daily"
        )

        self.dlp_scanner.create_rule(
            name="Credit Card Detection",
            pattern=r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            pattern_type="regex",
            severity=DLPSeverity.HIGH,
            actions=[PolicyAction.ALERT, PolicyAction.LOG],
            notify=[]
        )

        self.dlp_scanner.create_rule(
            name="SSN Detection",
            pattern=r"\b\d{3}-\d{2}-\d{4}\b",
            pattern_type="regex",
            severity=DLPSeverity.CRITICAL,
            actions=[PolicyAction.ALERT, PolicyAction.BLOCK],
            notify=[]
        )

        self.dlp_scanner.create_rule(
            name="API Key Detection",
            pattern=r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)",
            pattern_type="keyword",
            severity=DLPSeverity.HIGH,
            actions=[PolicyAction.LOG, PolicyAction.MASK]
        )

        self.pii_masking.create_mask_rule(
            name="Default PII Masking",
            pii_types=["email", "phone", "ssn", "credit_card"],
            action=PolicyAction.MASK
        )

        self.compliance_framework.create_from_template(ComplianceRegulation.GDPR)
        self.compliance_framework.create_from_template(ComplianceRegulation.HIPAA)
        self.compliance_framework.create_from_template(ComplianceRegulation.SOX)

        self.attachment_policy.create_policy(
            name="Default Attachment Policy",
            max_size_bytes=25 * 1024 * 1024,
            allowed_types=[".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".jpg", ".png", ".gif"],
            blocked_types=[".exe", ".dll", ".bat", ".cmd", ".ps1"],
            action=PolicyAction.BLOCK
        )


_enterprise_engine: Optional[EnterprisePolicyEngine] = None


def get_enterprise_policy_engine(data_dir: str = None) -> EnterprisePolicyEngine:
    global _enterprise_engine
    if _enterprise_engine is None:
        if data_dir is None:
            data_dir = str(Path.cwd() / "data" / "policy")
        _enterprise_engine = EnterprisePolicyEngine(data_dir)
    return _enterprise_engine