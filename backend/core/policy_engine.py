"""
Enterprise Policy Engine - Retention, Legal Hold, DLP
======================================================

Enterprise policy features:
- Retention policies
- Legal hold
- DLP scanning
- PII masking
- Enterprise compliance
- Audit logs
- Policy enforcement
- Attachment policies
- Email retention automation
"""

import json
import logging
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

from backend import config

logger = logging.getLogger("policy.engine")


class PolicyType(Enum):
    RETENTION = "retention"
    LEGAL_HOLD = "legal_hold"
    DLP = "dlp"
    PII_MASKING = "pii_masking"
    ATTACHMENT = "attachment"
    ENCRYPTION = "encryption"


class PolicyAction(Enum):
    KEEP = "keep"
    DELETE = "delete"
    ARCHIVE = "archive"
    HOLD = "hold"
    MASK = "mask"
    QUARANTINE = "quarantine"
    ALERT = "alert"
    LOG = "log"


class RetentionPeriod(Enum):
    DAYS_7 = 7
    DAYS_30 = 30
    DAYS_90 = 90
    DAYS_180 = 180
    DAYS_365 = 365
    YEARS_3 = 1095
    YEARS_7 = 2555
    FOREVER = -1


@dataclass
class RetentionPolicy:
    """Retention policy configuration"""
    policy_id: str
    name: str
    folder_pattern: str
    retention_days: int
    action_on_expiry: PolicyAction
    exclude_flagged: bool = False
    exclude_dl: bool = False
    is_active: bool = True


@dataclass
class LegalHold:
    """Legal hold configuration"""
    hold_id: str
    name: str
    account_ids: List[int]
    folder_patterns: List[str]
    sender_patterns: List[str]
    keywords: List[str]
    start_date: float
    end_date: Optional[float]
    created_by: str
    is_active: bool = True


@dataclass
class DLPRule:
    """DLP rule configuration"""
    rule_id: str
    name: str
    pattern: str
    pattern_type: str  # regex, keyword, exact
    severity: str  # low, medium, high, critical
    actions: List[PolicyAction]
    notify: List[str]  # email addresses
    is_active: bool = True


@dataclass
class PIIDetection:
    """PII detection result"""
    pii_type: str
    value: str
    start_index: int
    end_index: int
    is_masked: bool = False


@dataclass
class PolicyAuditLog:
    """Policy audit log entry"""
    log_id: str
    timestamp: float
    policy_type: PolicyType
    policy_id: str
    action: PolicyAction
    email_id: Optional[int]
    account_id: int
    details: str
    result: str


class PolicyEngine:
    """
    Enterprise policy engine for retention, legal hold, and DLP.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or (Path(config.DATA_DIR) / "policy_engine.db")
        self._init_db()

        # Policies
        self._retention_policies: Dict[str, RetentionPolicy] = {}
        self._legal_holds: Dict[str, LegalHold] = {}
        self._dlp_rules: Dict[str, DLPRule] = {}

        # PII patterns
        self._pii_patterns = self._init_pii_patterns()

        # Callbacks
        self.on_policy_violation: Optional[Callable] = None
        self.on_retention_expired: Optional[Callable] = None
        self.on_legal_hold_match: Optional[Callable] = None

        self._lock = threading.RLock()

        logger.info("Policy Engine initialized")

    def _init_db(self):
        """Initialize policy database"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # Retention policies
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS retention_policies (
                policy_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                folder_pattern TEXT,
                retention_days INTEGER,
                action_on_expiry TEXT,
                exclude_flagged INTEGER DEFAULT 0,
                exclude_dl INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Legal holds
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS legal_holds (
                hold_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                account_ids TEXT,
                folder_patterns TEXT,
                sender_patterns TEXT,
                keywords TEXT,
                start_date REAL,
                end_date REAL,
                created_by TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)

        # DLP rules
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dlp_rules (
                rule_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                pattern TEXT,
                pattern_type TEXT,
                severity TEXT,
                actions TEXT,
                notify TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Policy audit logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS policy_audit_logs (
                log_id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                policy_type TEXT NOT NULL,
                policy_id TEXT,
                action TEXT NOT NULL,
                email_id INTEGER,
                account_id INTEGER,
                details TEXT,
                result TEXT
            )
        """)

        # Email retention tracking
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_retention (
                email_id INTEGER PRIMARY KEY,
                account_id INTEGER,
                policy_id TEXT,
                retention_expires_at REAL,
                is_on_legal_hold INTEGER DEFAULT 0
            )
        """)

        conn.commit()
        conn.close()

    def _init_pii_patterns(self) -> Dict[str, str]:
        """Initialize PII detection patterns"""
        return {
            "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
            "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
            "phone": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",
            "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            "ip_address": r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
            "date_of_birth": r"\b(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/\d{4}\b",
            "passport": r"\b[A-Z]{1,2}\d{6,9}\b",
            "drivers_license": r"\b[A-Z]{1,2}\d{5,8}\b"
        }

    @contextmanager
    def _get_conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def create_retention_policy(self, name: str, folder_pattern: str,
                               retention_days: int, action_on_expiry: PolicyAction,
                               exclude_flagged: bool = False, exclude_dl: bool = False) -> str:
        """Create retention policy"""
        import secrets
        policy_id = f"ret_{secrets.token_hex(8)}"

        policy = RetentionPolicy(
            policy_id=policy_id,
            name=name,
            folder_pattern=folder_pattern,
            retention_days=retention_days,
            action_on_expiry=action_on_expiry,
            exclude_flagged=exclude_flagged,
            exclude_dl=exclude_dl
        )

        self._retention_policies[policy_id] = policy

        # Store in database
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO retention_policies
                (policy_id, name, folder_pattern, retention_days, action_on_expiry, exclude_flagged, exclude_dl)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                policy_id, name, folder_pattern, retention_days,
                action_on_expiry.value, 1 if exclude_flagged else 0, 1 if exclude_dl else 0
            ))
            conn.commit()

        logger.info(f"Retention policy created: {name}")

        return policy_id

    def apply_retention_policy(self, email: Dict, account_id: int) -> PolicyAction:
        """Apply retention policy to an email"""
        folder = email.get("folder", "")
        received_at = email.get("received_at", time.time())

        # Check legal hold first
        if self._is_on_legal_hold(account_id, email):
            self._log_audit(PolicyType.LEGAL_HOLD, "", PolicyAction.HOLD,
                          email.get("id"), account_id, "Email on legal hold")
            return PolicyAction.HOLD

        # Find applicable policy
        for policy in self._retention_policies.values():
            if not policy.is_active:
                continue

            if self._matches_pattern(folder, policy.folder_pattern):
                # Check exclusions
                if policy.exclude_flagged and email.get("flagged", False):
                    continue
                if policy.exclude_dl and email.get("is_dl", False):
                    continue

                # Calculate expiry
                age_days = (time.time() - received_at) / 86400

                if age_days > policy.retention_days:
                    # Expired
                    self._log_audit(PolicyType.RETENTION, policy.policy_id,
                                  policy.action_on_expiry, email.get("id"),
                                  account_id, f"Retention expired ({age_days:.0f} days)")

                    return policy.action_on_expiry

        return PolicyAction.KEEP

    def _is_on_legal_hold(self, account_id: int, email: Dict) -> bool:
        """Check if email is on legal hold"""
        for hold in self._legal_holds.values():
            if not hold.is_active:
                continue

            # Check account
            if account_id not in hold.account_ids:
                continue

            # Check folder pattern
            folder = email.get("folder", "")
            if not any(self._matches_pattern(folder, fp) for fp in hold.folder_patterns):
                continue

            # Check sender pattern
            sender = email.get("from", "")
            if not any(self._matches_pattern(sender, sp) for sp in hold.sender_patterns):
                continue

            # Check keywords
            body = email.get("body_text", "")
            if any(kw.lower() in body.lower() for kw in hold.keywords):
                return True

        return False

    def create_legal_hold(self, name: str, account_ids: List[int],
                          folder_patterns: List[str], sender_patterns: List[str],
                          keywords: List[str], created_by: str,
                          end_date: float = None) -> str:
        """Create legal hold"""
        import secrets
        hold_id = f"hold_{secrets.token_hex(8)}"

        hold = LegalHold(
            hold_id=hold_id,
            name=name,
            account_ids=account_ids,
            folder_patterns=folder_patterns,
            sender_patterns=sender_patterns,
            keywords=keywords,
            start_date=time.time(),
            end_date=end_date,
            created_by=created_by
        )

        self._legal_holds[hold_id] = hold

        # Store in database
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO legal_holds
                (hold_id, name, account_ids, folder_patterns, sender_patterns, keywords, start_date, end_date, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                hold_id, name, json.dumps(account_ids), json.dumps(folder_patterns),
                json.dumps(sender_patterns), json.dumps(keywords), time.time(),
                end_date, created_by
            ))
            conn.commit()

        logger.info(f"Legal hold created: {name}")

        return hold_id

    def create_dlp_rule(self, name: str, pattern: str, pattern_type: str,
                        severity: str, actions: List[PolicyAction],
                        notify: List[str] = None) -> str:
        """Create DLP rule"""
        import secrets
        rule_id = f"dlp_{secrets.token_hex(8)}"

        rule = DLPRule(
            rule_id=rule_id,
            name=name,
            pattern=pattern,
            pattern_type=pattern_type,
            severity=severity,
            actions=actions,
            notify=notify or []
        )

        self._dlp_rules[rule_id] = rule

        # Store in database
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO dlp_rules
                (rule_id, name, pattern, pattern_type, severity, actions, notify)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                rule_id, name, pattern, pattern_type, severity,
                json.dumps([a.value for a in actions]), json.dumps(notify or [])
            ))
            conn.commit()

        logger.info(f"DLP rule created: {name}")

        return rule_id

    def scan_dlp(self, email: Dict) -> List[Dict]:
        """Scan email for DLP violations"""
        violations = []

        # Combine text to scan
        text_to_scan = f"{email.get('subject', '')} {email.get('body_text', '')}"

        for rule in self._dlp_rules.values():
            if not rule.is_active:
                continue

            matches = []

            if rule.pattern_type == "regex":
                try:
                    matches = re.findall(rule.pattern, text_to_scan, re.IGNORECASE)
                except re.error:
                    pass
            elif rule.pattern_type == "keyword":
                keywords = rule.pattern.split(",")
                matches = [kw for kw in keywords if kw.lower() in text_to_scan.lower()]
            elif rule.pattern_type == "exact":
                if rule.pattern.lower() in text_to_scan.lower():
                    matches = [rule.pattern]

            if matches:
                violation = {
                    "rule_id": rule.rule_id,
                    "rule_name": rule.name,
                    "severity": rule.severity,
                    "matches": matches,
                    "actions": rule.actions
                }
                violations.append(violation)

                # Log violation
                self._log_audit(PolicyType.DLP, rule.rule_id, PolicyAction.ALERT,
                              email.get("id"), email.get("account_id"),
                              f"DLP violation: {rule.name}")

        return violations

    def detect_pii(self, text: str) -> List[PIIDetection]:
        """Detect PII in text"""
        detections = []

        for pii_type, pattern in self._pii_patterns.items():
            try:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    detections.append(PIIDetection(
                        pii_type=pii_type,
                        value=match.group(),
                        start_index=match.start(),
                        end_index=match.end()
                    ))
            except re.error:
                continue

        return detections

    def mask_pii(self, text: str, pii_types: List[str] = None) -> tuple[str, List[PIIDetection]]:
        """Mask PII in text"""
        detections = self.detect_pii(text)

        if pii_types:
            detections = [d for d in detections if d.pii_type in pii_types]

        masked_text = text
        # Sort by reverse index to avoid offset issues
        for detection in sorted(detections, key=lambda x: x.start_index, reverse=True):
            pii_type = detection.pii_type
            replacement = self._get_pii_mask(pii_type)
            masked_text = masked_text[:detection.start_index] + replacement + masked_text[detection.end_index:]
            detection.is_masked = True

        return masked_text, detections

    def _get_pii_mask(self, pii_type: str) -> str:
        """Get mask for PII type"""
        masks = {
            "ssn": "XXX-XX-XXXX",
            "credit_card": "XXXX-XXXX-XXXX-XXXX",
            "phone": "XXX-XXX-XXXX",
            "email": "xxxx@xxxx.xxx",
            "ip_address": "X.X.X.X",
            "date_of_birth": "XX/XX/XXXX",
            "passport": "XXXXXXXXXX",
            "drivers_license": "XXXXXXXX"
        }
        return masks.get(pii_type, "XXXX")

    def _matches_pattern(self, text: str, pattern: str) -> bool:
        """Check if text matches pattern"""
        if not pattern or pattern == "*" or pattern == "all":
            return True

        # Simple wildcard match
        if "*" in pattern:
            import fnmatch
            return fnmatch.fnmatch(text.lower(), pattern.lower())

        return pattern.lower() in text.lower()

    def _log_audit(self, policy_type: PolicyType, policy_id: str,
                  action: PolicyAction, email_id: int, account_id: int, details: str):
        """Log policy audit"""
        import secrets
        log_id = f"audit_{secrets.token_hex(8)}"

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO policy_audit_logs
                (log_id, timestamp, policy_type, policy_id, action, email_id, account_id, details, result)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log_id, time.time(), policy_type.value, policy_id,
                action.value, email_id, account_id, details, "success"
            ))
            conn.commit()

    def get_audit_logs(self, account_id: int = None,
                       limit: int = 100) -> List[PolicyAuditLog]:
        """Get policy audit logs"""
        logs = []

        with self._get_conn() as conn:
            cursor = conn.cursor()

            if account_id:
                cursor.execute("""
                    SELECT * FROM policy_audit_logs
                    WHERE account_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (account_id, limit))
            else:
                cursor.execute("""
                    SELECT * FROM policy_audit_logs
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
                    result=row["result"]
                ))

        return logs

    def get_policy_stats(self) -> Dict:
        """Get policy statistics"""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM retention_policies WHERE is_active = 1")
            active_retention = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM legal_holds WHERE is_active = 1")
            active_holds = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM dlp_rules WHERE is_active = 1")
            active_dlp = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM policy_audit_logs WHERE timestamp > ?",
                         (time.time() - 86400,))
            recent_logs = cursor.fetchone()[0]

        return {
            "active_retention_policies": active_retention,
            "active_legal_holds": active_holds,
            "active_dlp_rules": active_dlp,
            "recent_audit_logs": recent_logs,
            "total_retention_policies": len(self._retention_policies),
            "total_legal_holds": len(self._legal_holds),
            "total_dlp_rules": len(self._dlp_rules)
        }


# Global policy engine
_policy_engine: Optional[PolicyEngine] = None


def get_policy_engine() -> PolicyEngine:
    """Get global policy engine"""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = PolicyEngine()
    return _policy_engine


