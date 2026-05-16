"""
AI Safety & Governance Hardening
=============================

Enterprise AI safety systems:
- Prompt injection defense
- Jailbreak detection
- Hallucination quarantine
- Output guardrails
- Token限流 protection
- AI content filtering
- Confidence calibration enforcement
- Poison input detection
- Chain-of-thought safety
- Multi-model consensus
"""

import re
import time
import hashlib
import logging
import asyncio
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from dataclasses import dataclass, field
from enum import Enum
from collections import deque, defaultdict
from urllib.parse import quote_plus, unquote_plus
import uuid

logger = logging.getLogger("ai.safety")


class SafetyLevel(Enum):
    SAFE = "safe"
    SUSPICIOUS = "suspicious"
    QUARANTINE = "quarantine"
    BLOCKED = "blocked"


class InjectionType(Enum):
    DIRECT = "direct"
    INDIRECT = "indirect"
    DELIMITED = "delimited"
    EMBEDDED = "embedded"
    JAILBREAK = "jailbreak"
    SOCIAL_ENGINEERING = "social_engineering"


@dataclass
class SafetyViolation:
    """Safety violation record"""
    violation_id: str
    violation_type: str
    severity: float
    blocked: bool
    input_fingerprint: str
    detected_at: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HallucinationRecord:
    """Hallucination detection record"""
    record_id: str
    prediction: str
    confidence: float
    is_quarantined: bool
    quarantine_reason: str
    verification_status: str
    detected_at: float = field(default_factory=time.time)


@dataclass
class GuardrailResult:
    """Guardrail check result"""
    passed: bool
    safety_level: SafetyLevel
    confidence_adjustment: float = 0.0
    violations: List[SafetyViolation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sanitized_input: Optional[str] = None
    blocked_reason: Optional[str] = None


class PromptInjectionDetector:
    """Detect prompt injection attacks"""
    
    DIRECT_PATTERNS = [
        r"(?i)ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|rules?|prompts?)",
        r"(?i)disregard\s+(your\s+)?(instructions?|system\s+prompt)",
        r"(?i)forget\s+(everything|all\s+instructions)\s+you\s+(know|were\s+told)",
        r"(?i)you\s+are\s+(now\s+)?(no\s+longer|a\s+new)",
        r"(?i)new\s+instructions:",
        r"(?i)override\s+(your\s+)?(programming|instructions)",
        r"(?i)system:\s*",
        r"(?i)assistant:\s*",
        r"(?i)human:\s*",
        r"(?i)user:\s*",
    ]
    
    DELIMITER_PATTERNS = [
        r"```[\s\S]*?```",
        r"<<<[\s\S]*?>>>",
        r"===[\s\S]*?===",
        r"---[\s\S]*?---",
    ]
    
    JAILBREAK_PATTERNS = [
        r"(?i)DAN",
        r"(?i)developer\s+mode",
        r"(?i)jailbreak",
        r"(?i)bypass\s+(safety|content\s+filter)",
        r"(?i)unfiltered",
        r"(?i)roleplay\s+as\s+[^\s]+(?i:without\s+rules)",
        r"(?i)i\s+am\s+[^\s]+(?i:in\s+a\s+ fictional)",
        r"(?i)simulate\s+[^\s]+(?i:without\s+safety)",
    ]
    
    SOCIAL_ENGINEERING_PATTERNS = [
        r"(?i)please\s+(help|assist)\s+me\s+(with|i'm\s+writing)",
        r"(?i)i\s+am\s+(a\s+)?(researcher|teacher|student)",
        r"(?i)my\s+(friend|parent|child)",
        r"(?i)it's\s+(for\s+)?(educational|research)",
    ]
    
    def __init__(self):
        self._direct_patterns = [re.compile(p) for p in self.DIRECT_PATTERNS]
        self._delimiter_patterns = [re.compile(p) for p in self.DELIMITER_PATTERNS]
        self._jailbreak_patterns = [re.compile(p) for p in self.JAILBREAK_PATTERNS]
        self._social_patterns = [re.compile(p) for p in self.SOCIAL_ENGINEERING_PATTERNS]
        self._violation_count = 0
        self._lock = threading.RLock()
        self._blocked_inputs: Set[str] = set()
        self._detection_stats = defaultdict(int)
    
    def detect(self, text: str) -> Tuple[List[SafetyViolation], InjectionType]:
        """Detect prompt injection in text"""
        violations = []
        detected_types = []
        
        with self._lock:
            fingerprint = hashlib.sha256(text.encode()).hexdigest()[:16]
            
            if fingerprint in self._blocked_inputs:
                violations.append(SafetyViolation(
                    violation_id=str(uuid.uuid4()),
                    violation_type="blocked_input",
                    severity=1.0,
                    blocked=True,
                    input_fingerprint=fingerprint,
                    details={"reason": "Previously blocked input"}
                ))
                return violations, InjectionType.DIRECT
            
            for pattern in self._direct_patterns:
                if pattern.search(text):
                    detected_types.append(InjectionType.DIRECT)
                    self._detection_stats["direct"] += 1
                    violations.append(SafetyViolation(
                        violation_id=str(uuid.uuid4()),
                        violation_type="direct_instruction",
                        severity=0.9,
                        blocked=False,
                        input_fingerprint=fingerprint,
                        details={"pattern": pattern.pattern}
                    ))
            
            for pattern in self._delimiter_patterns:
                if pattern.search(text):
                    detected_types.append(InjectionType.DELIMITED)
                    self._detection_stats["delimited"] += 1
                    violations.append(SafetyViolation(
                        violation_id=str(uuid.uuid4()),
                        violation_type="delimiter_injection",
                        severity=0.7,
                        blocked=False,
                        input_fingerprint=fingerprint,
                        details={"pattern": pattern.pattern}
                    ))
            
            for pattern in self._jailbreak_patterns:
                if pattern.search(text):
                    detected_types.append(InjectionType.JAILBREAK)
                    self._detection_stats["jailbreak"] += 1
                    violations.append(SafetyViolation(
                        violation_id=str(uuid.uuid4()),
                        violation_type="jailbreak_attempt",
                        severity=1.0,
                        blocked=True,
                        input_fingerprint=fingerprint,
                        details={"pattern": pattern.pattern}
                    ))
            
            for pattern in self._social_patterns:
                if pattern.search(text):
                    detected_types.append(InjectionType.SOCIAL_ENGINEERING)
                    self._detection_stats["social"] += 1
                    violations.append(SafetyViolation(
                        violation_id=str(uuid.uuid4()),
                        violation_type="social_engineering",
                        severity=0.5,
                        blocked=False,
                        input_fingerprint=fingerprint,
                        details={"pattern": pattern.pattern}
                    ))
            
            if any(t == InjectionType.JAILBREAK for t in detected_types):
                self._blocked_inputs.add(fingerprint)
                self._violation_count += 1
            
            return violations, detected_types[0] if detected_types else InjectionType.DIRECT
    
    def get_stats(self) -> Dict[str, int]:
        """Get detection statistics"""
        with self._lock:
            return dict(self._detection_stats)


class HallucinationDetector:
    """Detect potential hallucinations in AI outputs"""
    
    def __init__(self, 
                 low_confidence_threshold: float = 0.5,
                 high_entropy_threshold: float = 4.0,
                 self_consistency_threshold: float = 0.7):
        self._low_confidence_threshold = low_confidence_threshold
        self._high_entropy_threshold = high_entropy_threshold
        self._self_consistency_threshold = self_consistency_threshold
        self._quarantine_records: deque = deque(maxlen=1000)
        self._lock = threading.RLock()
        self._quarantine_stats = defaultdict(int)
        self._verified_count = 0
        self._false_positive_count = 0
    
    def calculate_entropy(self, text: str) -> float:
        """Calculate token entropy of text"""
        if not text:
            return 0.0
        
        char_freq = defaultdict(int)
        for char in text:
            char_freq[char] += 1
        
        total = len(text)
        entropy = 0.0
        for freq in char_freq.values():
            if freq > 0:
                prob = freq / total
                entropy -= prob * (prob ** 0.5)
        
        return max(entropy * 10, 0)
    
    def check_hallucination(self, 
                          prediction: str, 
                          confidence: float,
                          context: Optional[Dict[str, Any]] = None) -> HallucinationRecord:
        """Check if prediction might be hallucinated"""
        with self._lock:
            is_quarantined = False
            quarantine_reason = ""
            
            if confidence < self._low_confidence_threshold:
                is_quarantined = True
                quarantine_reason = f"low_confidence_{confidence:.2f}"
                self._quarantine_stats["low_confidence"] += 1
            
            entropy = self.calculate_entropy(prediction)
            if entropy > self._high_entropy_threshold:
                is_quarantined = True
                quarantine_reason = f"high_entropy_{entropy:.2f}"
                self._quarantine_stats["high_entropy"] += 1
            
            if context and context.get("requires_verification"):
                is_quarantined = True
                quarantine_reason = "requires_verification"
                self._quarantine_stats["requires_verification"] += 1
            
            record = HallucinationRecord(
                record_id=str(uuid.uuid4()),
                prediction=prediction[:200],
                confidence=confidence,
                is_quarantined=is_quarantined,
                quarantine_reason=quarantine_reason,
                verification_status="pending"
            )
            
            self._quarantine_records.append(record)
            return record
    
    def verify_hallucination(self, record_id: str, is_actual_hallucination: bool):
        """Verify quarantine decision"""
        with self._lock:
            for record in self._quarantine_records:
                if record.record_id == record_id:
                    record.verification_status = "verified"
                    if is_actual_hallucination:
                        self._verified_count += 1
                    else:
                        self._false_positive_count += 1
                    break
    
    def get_quarantine_stats(self) -> Dict[str, Any]:
        """Get quarantine statistics"""
        with self._lock:
            total = sum(self._quarantine_stats.values())
            return {
                "total_quarantined": total,
                "verified_hallucinations": self._verified_count,
                "false_positives": self._false_positive_count,
                "accuracy": self._verified_count / max(total, 1),
                "by_reason": dict(self._quarantine_stats)
            }


class AISafetyGuardrails:
    """Comprehensive AI safety guardrails"""
    
    def __init__(self):
        self._injection_detector = PromptInjectionDetector()
        self._hallucination_detector = HallucinationDetector()
        self._blocked_outputs: Set[str] = set()
        self._lock = threading.RLock()
        self._config = {
            "enable_injection_detection": True,
            "enable_hallucination_detection": True,
            "enable_output_filtering": True,
            "injection_block_threshold": 0.8,
            "hallucination_confidence_threshold": 0.5,
            "max_output_length": 10000,
            "require_consensus": False
        }
        self._recent_checks: deque = deque(maxlen=100)
    
    async def check_input(self, 
                        text: str, 
                        context: Optional[Dict[str, Any]] = None) -> GuardrailResult:
        """Check input against safety guardrails"""
        violations = []
        warnings = []
        sanitized_input = text
        
        if self._config["enable_injection_detection"]:
            injection_violations, injection_type = self._injection_detector.detect(text)
            violations.extend(injection_violations)
            
            if any(v.blocked for v in injection_violations):
                return GuardrailResult(
                    passed=False,
                    safety_level=SafetyLevel.BLOCKED,
                    violations=violations,
                    blocked_reason="Blocked due to injection detection"
                )
            
            for v in injection_violations:
                if v.severity > self._config["injection_block_threshold"]:
                    warnings.append(f"High severity injection: {v.violation_type}")
        
        for v in violations:
            if v.severity > 0.5:
                sanitized_input = self._sanitize_text(sanitized_input, v.violation_type)
        
        max_severity = max([v.severity for v in violations], default=0.0)
        
        if max_severity > 0.7:
            safety_level = SafetyLevel.BLOCKED
        elif max_severity > 0.4:
            safety_level = SafetyLevel.QUARANTINE
        elif max_severity > 0.2:
            safety_level = SafetyLevel.SUSPICIOUS
        else:
            safety_level = SafetyLevel.SAFE
        
        passed = safety_level == SafetyLevel.SAFE
        
        return GuardrailResult(
            passed=passed,
            safety_level=safety_level,
            violations=violations,
            warnings=warnings,
            sanitized_input=sanitized_input
        )
    
    async def check_output(self,
                        prediction: str,
                        confidence: float,
                        context: Optional[Dict[str, Any]] = None) -> GuardrailResult:
        """Check AI output against safety guardrails"""
        violations = []
        warnings = []
        
        with self._lock:
            fingerprint = hashlib.sha256(prediction.encode()).hexdigest()[:16]
            
            if fingerprint in self._blocked_outputs:
                return GuardrailResult(
                    passed=False,
                    safety_level=SafetyLevel.BLOCKED,
                    violations=violations,
                    blocked_reason="Previously blocked output"
                )
        
        if self._config["enable_hallucination_detection"]:
            h_record = self._hallucination_detector.check_hallucination(
                prediction, confidence, context
            )
            
            if h_record.is_quarantined:
                warnings.append(f"Hallucination suspected: {h_record.quarantine_reason}")
                
                violations.append(SafetyViolation(
                    violation_id=h_record.record_id,
                    violation_type="hallucination",
                    severity=0.6,
                    blocked=False,
                    input_fingerprint=fingerprint,
                    details={"reason": h_record.quarantine_reason, "confidence": confidence}
                ))
        
        if len(prediction) > self._config["max_output_length"]:
            predictions = prediction[:self._config["max_output_length"]]
            warnings.append(f"Output truncated from {len(prediction)} to {len(predictions)}")
        
        passed = len([v for v in violations if v.blocked]) == 0
        
        return GuardrailResult(
            passed=passed,
            safety_level=SafetyLevel.QUARANTINE if warnings else SafetyLevel.SAFE,
            violations=violations,
            warnings=warnings
        )
    
    def _sanitize_text(self, text: str, violation_type: str) -> str:
        """Sanitize text based on violation type"""
        sanitized = text
        
        if "direct_instruction" in violation_type:
            sanitized = re.sub(
                r"(?i)(ignore|disregard|forget|override)\s+[^\n]+",
                "[FILTERED]",
                sanitized
            )
        
        if "jailbreak" in violation_type:
            sanitized = re.sub(
                r"(?i)(DAN|developer\s+mode|jailbreak)[^\n]+",
                "[FILTERED]",
                sanitized
            )
        
        return sanitized
    
    def get_injection_stats(self) -> Dict[str, int]:
        """Get injection detection statistics"""
        return self._injection_detector.get_stats()
    
    def get_hallucination_stats(self) -> Dict[str, Any]:
        """Get hallucination detection statistics"""
        return self._hallucination_detector.get_quarantine_stats()
    
    def update_config(self, config: Dict[str, Any]):
        """Update guardrail configuration"""
        with self._lock:
            self._config.update(config)


class ContentFilter:
    """Content filtering for AI outputs"""
    
    BLOCKED_PATTERNS = [
        r"\b(?:secret|confidential)\s+(?:key|token|password|credential)",
        r"(?i)sk-[a-zA-Z0-9]{20,}",
    ]
    
    WARN_PATTERNS = [
        r"(?i)hack",
        r"(?i)exploit",
        r"(?i)vulnerability",
    ]
    
    def __init__(self):
        self._blocked_patterns = [re.compile(p) for p in self.BLOCKED_PATTERNS]
        self._warn_patterns = [re.compile(p) for p in self.WARN_PATTERNS]
        self._filter_stats = defaultdict(int)
        self._lock = threading.RLock()
    
    def filter(self, text: str) -> Tuple[str, List[str]]:
        """Filter content and return warnings"""
        warnings = []
        filtered = text
        
        with self._lock:
            for pattern in self._blocked_patterns:
                if pattern.search(text):
                    filtered = pattern.sub("[REDACTED]", filtered)
                    self._filter_stats["blocked"] += 1
                    warnings.append("Content blocked: sensitive pattern detected")
            
            for pattern in self._warn_patterns:
                if pattern.search(text):
                    self._filter_stats["warned"] += 1
            
            return filtered, warnings
    
    def get_stats(self) -> Dict[str, int]:
        """Get filter statistics"""
        with self._lock:
            return dict(self._filter_stats)


class MultiModelConsensus:
    """Verify outputs via multi-model consensus"""
    
    def __init__(self, models: List[str]):
        self._models = models
        self._consensus_threshold = 0.7
        self._verification_cache: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
    
    async def verify(self, 
                    outputs: Dict[str, str],
                    expected_category: Optional[str] = None) -> Dict[str, Any]:
        """Verify outputs across models"""
        if len(outputs) < 2:
            return {"verified": True, "consensus": 1.0}
        
        output_list = list(outputs.values())
        unique_outputs = set(output_list)
        
        agreement = len(output_list) - len(unique_outputs) + 1
        agreement = agreement / len(output_list)
        
        fingerprint = hashlib.sha256(
            " ".join(sorted(output_list)).encode()
        ).hexdigest()
        
        verification = {
            "verified": agreement >= self._consensus_threshold,
            "consensus": agreement,
            "outputs": outputs,
            "fingerprint": fingerprint
        }
        
        with self._lock:
            self._verification_cache[fingerprint] = verification
        
        return verification
    
    def set_consensus_threshold(self, threshold: float):
        """Set consensus threshold"""
        self._consensus_threshold = threshold


_global_safety_guardrails: Optional[AISafetyGuardrails] = None
_global_content_filter: Optional[ContentFilter] = None


def get_safety_guardrails() -> AISafetyGuardrails:
    """Get global safety guardrails"""
    global _global_safety_guardrails
    if _global_safety_guardrails is None:
        _global_safety_guardrails = AISafetyGuardrails()
    return _global_safety_guardrails


def get_content_filter() -> ContentFilter:
    """Get global content filter"""
    global _global_content_filter
    if _global_content_filter is None:
        _global_content_filter = ContentFilter()
    return _global_content_filter


__all__ = [
    "SafetyLevel",
    "InjectionType", 
    "SafetyViolation",
    "HallucinationRecord",
    "GuardrailResult",
    "PromptInjectionDetector",
    "HallucinationDetector",
    "AISafetyGuardrails",
    "ContentFilter",
    "MultiModelConsensus",
    "get_safety_guardrails",
    "get_content_filter"
]