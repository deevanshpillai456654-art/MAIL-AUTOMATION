"""Scam and phishing classification helpers.

The classifier remains local-first and deterministic.  User/admin feedback is
stored as a sender override, then lightweight scam heuristics handle new mail
before the broader category classifier runs.

v2: integrated with DomainIntelligenceEngine for lookalike / homograph /
typosquatting detection and confidence scoring (0-100 scale).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SCAM_CATEGORY = "Scam"
PENDING_REVIEW_CATEGORY = "Pending Review"
NORMAL_CATEGORY = "Normal"
FEEDBACK_CATEGORIES = {SCAM_CATEGORY, NORMAL_CATEGORY}

# Confidence score thresholds (0-100)
_THRESHOLD_TRUSTED = 20
_THRESHOLD_REVIEW = 55
_THRESHOLD_SUSPICIOUS = 80


def normalize_feedback_category(category: str) -> str:
    text = str(category or "").strip().lower()
    if text in {"scam", "fraud", "phishing", "malicious", "suspicious"}:
        return SCAM_CATEGORY
    if text in {"normal", "not scam", "safe", "legit", "legitimate", "trusted"}:
        return NORMAL_CATEGORY
    return str(category or "").strip()


@dataclass(frozen=True)
class ScamSignal:
    phrase: str
    weight: float
    reason: str


class ScamFilter:
    """Manual override and heuristic scam detector with domain intelligence."""

    SIGNALS: List[ScamSignal] = [
        ScamSignal("verify your account", 2.0, "asks to verify account"),
        ScamSignal("confirm your account", 2.0, "asks to confirm account"),
        ScamSignal("account will be suspended", 3.0, "threatens account suspension"),
        ScamSignal("account suspended", 2.5, "mentions account suspension"),
        ScamSignal("password expires", 2.0, "password-expiry pressure"),
        ScamSignal("unauthorized transaction", 2.0, "unauthorized transaction claim"),
        ScamSignal("wire release", 2.5, "wire/payment release pressure"),
        ScamSignal("wire transfer", 1.6, "wire transfer request"),
        ScamSignal("new bank details", 2.5, "bank detail change request"),
        ScamSignal("bank details", 2.0, "bank detail request"),
        ScamSignal("gift card", 3.2, "gift card payment request"),
        ScamSignal("itunes card", 3.0, "gift card payment request"),
        ScamSignal("google play card", 3.0, "gift card payment request"),
        ScamSignal("amazon gift card", 3.0, "gift card payment request"),
        ScamSignal("seed phrase", 4.0, "crypto seed phrase request"),
        ScamSignal("private key", 3.5, "crypto private key request"),
        ScamSignal("recovery phrase", 3.5, "crypto recovery phrase request"),
        ScamSignal("crypto wallet", 2.5, "crypto wallet request"),
        ScamSignal("send bitcoin", 3.0, "bitcoin payment request"),
        ScamSignal("send ethereum", 3.0, "ethereum payment request"),
        ScamSignal("claim your prize", 3.0, "prize claim language"),
        ScamSignal("you have won", 2.8, "lottery/prize claim language"),
        ScamSignal("lottery", 2.5, "lottery claim language"),
        ScamSignal("inheritance", 2.2, "inheritance scam language"),
        ScamSignal("million dollars", 2.0, "advance-fee scam language"),
        ScamSignal("act immediately", 1.4, "urgent pressure language"),
        ScamSignal("respond within 24", 1.6, "time-pressure tactic"),
        ScamSignal("click the link", 1.5, "click-link instruction"),
        ScamSignal("click this link", 1.5, "click-link instruction"),
        ScamSignal("click here to", 1.5, "click-link instruction"),
        ScamSignal("payment pending", 1.4, "payment pending pressure"),
        ScamSignal("outstanding invoice", 1.8, "invoice fraud pressure"),
        ScamSignal("credential", 2.0, "credential harvesting attempt"),
        ScamSignal("enter your password", 2.5, "credential harvesting"),
        ScamSignal("confirm your password", 2.5, "credential harvesting"),
        ScamSignal("your account has been compromised", 2.8, "account compromise alarm"),
        ScamSignal("unusual sign-in", 2.0, "fake security alert"),
        ScamSignal("update your payment", 2.0, "payment detail phishing"),
        ScamSignal("validate your identity", 2.0, "identity validation phishing"),
        ScamSignal("your package could not be delivered", 2.0, "fake delivery phishing"),
        ScamSignal("qr code", 1.2, "QR phishing attempt"),
    ]

    URL_SHORTENER_RE = re.compile(
        r"https?://(?:bit\.ly|tinyurl\.com|t\.co|is\.gd|cutt\.ly|ow\.ly|rb\.gy|"
        r"short\.link|tiny\.cc|tr\.im|snip\.ly|qr\.ae|dlvr\.it|buff\.ly)/",
        re.I,
    )
    IMPERSONATION_RE = re.compile(
        r"(paypa[1l]|micr[o0]soft|g[o0]{2}gle|secure[-.]?login|account[-.]?verify|"
        r"login[-.]?verify|amaz[o0]n|app[1l]e|faceb[o0]{2}k|netfl[i1]x|"
        r"dropb[o0]x|tw[i1]tter|[i1]nstagram|l[i1]nked[i1]n)",
        re.I,
    )
    URGENT_RE = re.compile(
        r"\b(urgent|immediately|critical|final notice|last warning|"
        r"action required|your account will be|expires today|within 24 hours)\b",
        re.I,
    )
    EXECUTABLE_ATTACHMENT_RE = re.compile(
        r"\.(exe|bat|cmd|vbs|ps1|jar|apk|msi|scr|pif|com|lnk)\b",
        re.I,
    )
    CREDENTIAL_HARVEST_RE = re.compile(
        r"(enter\s+your\s+(password|username|credentials|login)|"
        r"confirm\s+your\s+(password|identity|account)|"
        r"verify\s+your\s+(credentials|account|identity|email))",
        re.I,
    )

    def __init__(self, db: Any = None):
        self.db = db
        self._domain_engine = None

    def _get_domain_engine(self):
        if self._domain_engine is None:
            try:
                from backend.ai.domain_intelligence import get_engine
                self._domain_engine = get_engine()
            except Exception as exc:
                logger.warning("DomainIntelligenceEngine unavailable: %s", exc)
        return self._domain_engine

    def _manual_override(self, sender_email: str, user_id: int = 0) -> Optional[Dict[str, Any]]:
        if not self.db or not sender_email:
            return None
        getter = getattr(self.db, "get_classification_override", None)
        if not getter:
            return None
        return getter(sender_email, user_id=user_id)

    def classify(
        self,
        subject: str,
        sender: str,
        sender_email: str,
        body: str = "",
        user_id: int = 0,
        spf_valid: Optional[bool] = None,
        dkim_valid: Optional[bool] = None,
        attachment_names: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        subject = subject or ""
        sender = sender or ""
        sender_email = (sender_email or "").strip().lower()
        body = body or ""
        attachment_names = attachment_names or []

        # --- 1. Manual override (user trust/block decisions) ---
        override = self._manual_override(sender_email, user_id=user_id)
        if override:
            category = normalize_feedback_category(override.get("category"))
            return {
                "category": category,
                "confidence": 1.0,
                "priority": "Critical" if category == SCAM_CATEGORY else "Medium",
                "source": "manual_override",
                "scam_reasons": [f"Manual sender decision: {category}"],
                "domain_threat": None,
                "impersonation_warning": None,
            }

        text = f"{subject} {sender} {sender_email} {body}".lower()
        if not text.strip():
            return None

        score = 0.0
        reasons: List[str] = []

        # --- 2. Heuristic signal scoring ---
        for signal in self.SIGNALS:
            if signal.phrase in text:
                score += signal.weight
                reasons.append(signal.reason)

        if self.URL_SHORTENER_RE.search(text):
            score += 2.0
            reasons.append("uses a shortened URL")

        if self.IMPERSONATION_RE.search(sender_email) or self.IMPERSONATION_RE.search(text):
            score += 2.0
            reasons.append("uses impersonation-style wording or sender domain")

        if self.URGENT_RE.search(text):
            score += 0.8
            reasons.append("uses urgency pressure language")

        if self.CREDENTIAL_HARVEST_RE.search(text):
            score += 2.5
            reasons.append("credential harvesting pattern detected")

        # Executable attachment detection
        for name in attachment_names:
            if self.EXECUTABLE_ATTACHMENT_RE.search(name):
                score += 4.0
                reasons.append(f"executable attachment: {name}")
                break

        # --- 3. Domain intelligence — lookalike / homograph / typosquatting ---
        domain_threat_data: Optional[Dict] = None
        impersonation_warning: Optional[str] = None

        domain_engine = self._get_domain_engine()
        if domain_engine and sender_email and "@" in sender_email:
            try:
                sender_result = domain_engine.analyse_sender(
                    sender_email,
                    spf_valid=spf_valid,
                    dkim_valid=dkim_valid,
                )
                dt = sender_result.domain_threat
                domain_threat_data = {
                    "domain": dt.domain,
                    "is_lookalike": dt.is_lookalike,
                    "impersonated_brand": dt.impersonated_brand,
                    "impersonated_domain": dt.impersonated_domain,
                    "confidence_score": dt.confidence_score,
                    "threat_type": dt.threat_type,
                    "reasons": dt.reasons,
                    "levenshtein_distance": dt.levenshtein_distance,
                    "visual_score": dt.visual_score,
                    "overall_threat_score": sender_result.overall_threat_score,
                    "classification": sender_result.classification,
                }

                if dt.is_lookalike:
                    # Convert domain confidence (0–100) to heuristic score contribution
                    domain_score_contribution = dt.confidence_score * 0.08
                    score += domain_score_contribution
                    reasons.extend(dt.reasons)
                    if dt.impersonated_brand:
                        impersonation_warning = (
                            f"This email appears to impersonate {dt.impersonated_brand} "
                            f"using a deceptive domain variation: '{dt.domain}'"
                        )

                elif sender_result.classification in ("suspicious", "scam"):
                    score += sender_result.overall_threat_score * 0.05
                    reasons.extend(dt.reasons)

            except Exception as exc:
                logger.debug("Domain intelligence error for %s: %s", sender_email, exc)

        # --- 4. Apply SPF/DKIM directly if not handled by domain engine ---
        if domain_threat_data is None:
            if spf_valid is False:
                score += 1.5
                reasons.append("SPF validation failed")
            if dkim_valid is False:
                score += 1.0
                reasons.append("DKIM validation failed")

        # Require a meaningful combined score
        if score < 4.0:
            return None

        confidence = round(min(0.98, 0.70 + (score * 0.035)), 2)
        priority = "Critical" if score >= 7.0 else "High"

        # Route to Pending Review if score is moderate (4–5.5) and no strong signals
        category = SCAM_CATEGORY
        if 4.0 <= score < 5.5 and not impersonation_warning:
            category = PENDING_REVIEW_CATEGORY
            priority = "Medium"

        return {
            "category": category,
            "confidence": confidence,
            "priority": priority,
            "source": "scam_filter",
            "scam_reasons": sorted(set(reasons)),
            "domain_threat": domain_threat_data,
            "impersonation_warning": impersonation_warning,
        }
