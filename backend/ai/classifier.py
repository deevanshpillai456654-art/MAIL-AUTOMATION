import re
import json
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime
from functools import lru_cache
import numpy as np

from backend.core.scam_filter import ScamFilter

logger = logging.getLogger(__name__)


class RulesEngine:
    """Layer 1 - Fast Rules Engine with pre-compiled patterns"""

    # Pre-compile patterns for performance
    PATTERNS = {
        "OTP": [
            r"one[\s-]?time\s*password",
            r"otp\s*(code|number)?",
            r"verification\s*code",
            r"security\s*code",
            r"confirm\s*your\s*identity",
            r"login\s*code",
            r"access\s*code",
            r"enter\s*this\s*code",
            r"your\s*verification\s*code",
            r"password\s*reset\s*code",
            r"2[\s-]?fa",
            r"two[\s-]?factor",
            r"one[\s-]?time\s*code",
            r"verify\s*your\s*identity",
        ],
        "Finance": [
            r"invoice\s*#?\d",
            r"bill\s*(payment)?",
            r"payment\s*receipt",
            r"amount\s*due",
            r"statement\s*of\s*account",
            r"tax\s*invoice",
            r"receipt\s*#",
            r"total\s*amount",
            r"\$\d+[\.,]\d{2}",
            r"credit\s*card",
            r"bank\s*statement",
            r"transaction\s*history",
            r"payment\s*received",
            r"amount\s*paid",
        ],
        "Promotions": [
            r"limited\s*time\s*offer",
            r"special\s*deal",
            r"%[\s-]?off",
            r"flash\s*sale",
            r"best\s*price",
            r"exclusive\s*offer",
            r"shop\s*now",
            r"free\s*shipping",
            r"buy\s*one\s*get",
            r"discount\s*code",
            r"coupon\s*code",
            r"save\s*\d+%\s*now",
        ],
        "Newsletters": [
            r"newsletter",
            r"weekly\s*update",
            r"monthly\s*digest",
            r"subscribe\s*to",
            r"view\s*in\s*browser",
            r"unsubscribe",
            r"email\s*not\s*displaying",
            r"view\s*online",
        ],
        "Spam": [
            r"click\s*here\s*to\s*win",
            r"congratulations\s*you\s*won",
            r"claim\s*your\s*prize",
            r"urgent\s*business\s*proposal",
            r"inheritance",
            r"lottery\s*winner",
            r"you\s*won\s*\d+",
            r"won\s*(the\s*)?lottery",
            r"prize\s*(winner|claim)",
            r"viagra",
            r"weight\s*loss",
            r"make\s*money\s*fast",
            r"work\s*from\s*home",
            r"click\s*below\s*now",
            r"act\s*now\s*limited",
        ],
        "Logistics": [
            r"order\s*shipped",
            r"tracking\s*number",
            r"delivery\s*date",
            r"out\s*for\s*delivery",
            r"package\s*arrived",
            r"shipping\s*update",
            r"fedex|ups|dhl|usps",
            r"carrier\s*tracking",
            r"estimated\s*delivery",
            r"order\s*confirmation",
            r"delivered\s*successfully",
            r"your\s*order\s*is\s*on\s*its\s*way",
        ],
        "Bills": [
            r"utility\s*bill",
            r"electricity\s*bill",
            r"gas\s*bill",
            r"water\s*bill",
            r"internet\s*bill",
            r"phone\s*bill",
            r"monthly\s*bill",
            r"bill\s*is\s*due",
            r"amount\s*due",
            r"payment\s*due\s*date",
            r"overdue\s*payment",
            r"account\s*balance",
            r"past\s*due",
        ],
        "Security": [
            r"security\s*alert",
            r"suspicious\s*activity",
            r"unauthorized\s*access",
            r"password\s*changed",
            r"account\s*locked",
            r"security\s*warning",
            r"breach\s*notification",
            r"two[\s-]?step\s*verification",
            r"verify\s*your\s*account",
            r"unusual\s*sign\s*in",
        ],
        "Marketing": [
            r"marketing\s*campaign",
            r"campaign\s*brief",
            r"brand\s*campaign",
            r"product\s*launch",
            r"webinar",
            r"case\s*study",
            r"press\s*release",
            r"content\s*calendar",
        ],
        "Sales": [
            r"demo\s*request",
            r"pricing\s*request",
            r"quote\s*request",
            r"sales\s*proposal",
            r"purchase\s*intent",
            r"book\s*a\s*demo",
            r"request\s*for\s*proposal",
        ],
        "Social Media": [
            r"new\s*follower",
            r"mentioned\s*you",
            r"social\s*media",
            r"linkedin|instagram|facebook|twitter|youtube",
            r"new\s*comment",
            r"direct\s*message",
        ],
        "Investor": [
            r"investor\s*update",
            r"funding\s*round",
            r"term\s*sheet",
            r"pitch\s*deck",
            r"cap\s*table",
            r"due\s*diligence",
        ],
        "Leads": [
            r"new\s*lead",
            r"inbound\s*lead",
            r"contact\s*form",
            r"website\s*inquiry",
            r"interested\s*in",
            r"request\s*demo",
        ],
        "Support": [
            r"support\s*request",
            r"help\s*desk",
            r"ticket\s*#?",
            r"technical\s*issue",
            r"customer\s*complaint",
        ],
    }

    SENDER_PATTERNS = {
        "Finance": [
            r".*@paypal\.com",
            r".*@stripe\.com",
            r".*@square\.com",
            r".*@venmo\.com",
            r".*@amazon\.com.*aws",
            r".*@chase\.com",
            r".*@bankofamerica\.com",
            r".*invoice.*",
            r"billing@(?!(utility|electric|water|gas))",
            r".*@billing.*",
        ],
        "Clients": [
            r".*@company\.com",
            r".*@client.*",
            r".*@business.*",
            r".*@partner.*",
        ],
        "HR": [
            r".*@.*HR.*",
            r".*@recruiter.*",
            r".*@hiring.*",
            r".*@employment.*",
            r".*@careers.*",
        ],
        "Support": [
            r".*support@",
            r".*help@",
            r".*@helpdesk.*",
            r".*@support.*",
        ],
        "Bills": [
            r".*@utility\.",
            r".*@.*utility.*",
            r".*@electric.*",
            r".*@water.*",
            r".*@gas.*",
        ],
    }

    def __init__(self):
        # Pre-compile all patterns for performance
        self._compiled_patterns = {}
        for category, patterns in self.PATTERNS.items():
            self._compiled_patterns[category] = [
                re.compile(pattern, re.IGNORECASE) for pattern in patterns
            ]
        
        self._compiled_sender = {}
        for category, patterns in self.SENDER_PATTERNS.items():
            self._compiled_sender[category] = [
                re.compile(pattern, re.IGNORECASE) for pattern in patterns
            ]

    def classify(self, subject: str, sender: str, sender_email: str, body: str = "") -> Tuple[str, float]:
        # Null safety
        subject = subject or ""
        sender = sender or ""
        sender_email = sender_email or ""
        body = body or ""

        try:
            text = f"{subject} {sender} {sender_email} {body}".lower()
            
            if not text.strip():
                return None, 0.0

            category_scores = {}

            # Check patterns
            for category, patterns in self._compiled_patterns.items():
                score = 0
                for pattern in patterns:
                    if pattern.search(text):
                        score += 1
                if score > 0:
                    category_scores[category] = score

            # Check sender patterns
            for category, patterns in self._compiled_sender.items():
                for pattern in patterns:
                    if sender_email and pattern.match(sender_email):
                        category_scores[category] = category_scores.get(category, 0) + 2
                        break

            if category_scores:
                max_score = max(category_scores.values())
                if max_score >= 1:
                    category = max(category_scores, key=category_scores.get)
                    confidence = min(0.95, 0.55 + (max_score * 0.15))
                    return category, confidence

            return None, 0.0
            
        except Exception as e:
            logger.error(f"RulesEngine classification error: {e}")
            return None, 0.0


class MLClassifier:
    """Layer 2 - Lightweight ML Classification"""

    def __init__(self, model_path: str = None):
        self.model_path = model_path
        self.categories = [
            "Finance", "OTP", "Clients", "Personal", "Promotions",
            "Spam", "Newsletters", "Trading", "Logistics", "Purchases",
            "HR", "Support", "Bills", "Security", "Scam", "Normal",
            "Marketing", "Sales", "Social Media", "Investor", "Leads"
        ]
        self._initialized = False
        self._model = None

        # Pre-compute keywords
        self._keywords = {
            "Finance": ["invoice", "payment", "bill", "amount", "transaction", "bank", "receipt", "charged"],
            "OTP": ["otp", "code", "verify", "password", "login", "security", "verification", "confirm"],
            "Clients": ["client", "project", "deal", "proposal", "meeting", "contract", "proposal"],
            "Personal": ["personal", "family", "friend", "home", "vacation", "birthday", "holiday"],
            "Promotions": ["sale", "discount", "offer", "shop", "buy", "deal", "save", "limited"],
            "Newsletters": ["newsletter", "update", "subscribe", "weekly", "monthly", "digest"],
            "Trading": ["trade", "stock", "crypto", "invest", "portfolio", "market", "trading"],
            "Logistics": ["shipping", "delivery", "order", "tracking", "package", "carrier", "delivered"],
            "Purchases": ["order", "purchase", "bought", "item", "cart", "checkout", "order"],
            "HR": ["job", "interview", "hiring", "resume", "position", "career", "application"],
            "Support": ["support", "help", "issue", "problem", "ticket", "complaint", "assist"],
            "Bills": ["due", "utility", "monthly", "overdue", "balance", "payment", "past"],
            "Security": ["alert", "warning", "suspicious", "breach", "unauthorized", "security", "compromised"],
            "Marketing": ["campaign", "marketing", "brand", "webinar", "launch", "case study", "content"],
            "Sales": ["demo", "pricing", "quote", "proposal", "sales", "purchase intent", "book a demo"],
            "Social Media": ["linkedin", "instagram", "facebook", "twitter", "youtube", "follower", "mention", "comment"],
            "Investor": ["investor", "funding", "term sheet", "pitch deck", "cap table", "due diligence"],
            "Leads": ["new lead", "inbound lead", "contact form", "website inquiry", "interested", "request demo"],
        }

    def initialize(self):
        if self._initialized:
            return
        self._initialized = True

    def classify(self, subject: str, body: str, sender: str = "") -> Tuple[str, float]:
        # Null safety
        subject = subject or ""
        body = body or ""
        sender = sender or ""

        try:
            self.initialize()

            text = f"{subject} {body[:500]}".lower()

            if not text.strip():
                return "Personal", 0.40

            scores = {}
            for category, words in self._keywords.items():
                score = sum(1 for word in words if word in text)
                if score > 0:
                    scores[category] = score

            if scores:
                max_score = max(scores.values())
                category = max(scores, key=scores.get)
                confidence = min(0.90, 0.50 + (max_score * 0.15))
                return category, confidence

            return "Personal", 0.40
            
        except Exception as e:
            logger.error(f"ML classification error: {e}")
            return "Personal", 0.40

    def get_embedding(self, text: str) -> Optional[np.ndarray]:
        return None


class PriorityScorer:
    """Priority scoring for emails"""

    # Pre-compile keywords
    _critical_keywords = re.compile(r"\b(urgent|emergency|critical|deadline|immediately)\b", re.I)
    _high_keywords = re.compile(r"\b(important|priority|review|approval|needed|required|asap)\b", re.I)
    _low_keywords = re.compile(r"\b(newsletter|promotion|update|digest|weekly|monthly)\b", re.I)

    def score(self, subject: str, sender: str, category: str, body: str = "") -> str:
        # Null safety
        subject = subject or ""
        body = body or ""
        category = category or "Personal"

        try:
            text = f"{subject} {body}".lower()

            # Category-based priority
            if category == "Scam":
                return "Critical"
            if category in ["Security", "OTP"]:
                return "High"

            # Critical keywords
            if self._critical_keywords.search(text):
                return "Critical"

            # High priority keywords
            if self._high_keywords.search(text):
                return "High"

            # Low priority keywords
            if self._low_keywords.search(text):
                return "Low"

            return "Medium"
            
        except Exception as e:
            logger.error(f"Priority scoring error: {e}")
            return "Medium"


class EmailClassifier:
    """Main classifier combining all layers with error handling"""

    def __init__(self, model_path: str = None, db=None):
        self.rules_engine = RulesEngine()
        self.ml_classifier = MLClassifier(model_path)
        self.priority_scorer = PriorityScorer()
        self.db = db
        self.scam_filter = ScamFilter(db=db)
        self._learned_categories = {}
        self._stats = {
            "total_classifications": 0,
            "rules_engine_hits": 0,
            "ml_fallback_hits": 0,
            "scam_filter_hits": 0,
            "errors": 0
        }

    def classify(self, subject: str, sender: str, sender_email: str, body: str = "") -> Dict:
        # Null safety with defaults
        subject = subject or ""
        sender = sender or ""
        sender_email = sender_email or ""
        body = body or ""

        try:
            self._stats["total_classifications"] += 1

            scam_result = self.scam_filter.classify(subject, sender, sender_email, body)
            if scam_result:
                self._stats["scam_filter_hits"] += 1
                return {
                    "category": scam_result["category"],
                    "confidence": round(float(scam_result.get("confidence", 0.0)), 2),
                    "priority": scam_result.get("priority") or self.priority_scorer.score(subject, sender, scam_result["category"], body),
                    "timestamp": datetime.now().isoformat(),
                    "source": scam_result.get("source", "scam_filter"),
                    "scam_reasons": scam_result.get("scam_reasons", []),
                }

            # Layer 1: Rules Engine
            category, confidence = self.rules_engine.classify(subject, sender, sender_email, body)

            # Layer 2: ML Classifier fallback
            if confidence < 0.70:
                ml_category, ml_confidence = self.ml_classifier.classify(subject, body, sender)
                if ml_confidence > confidence:
                    category = ml_category
                    confidence = ml_confidence
                    self._stats["ml_fallback_hits"] += 1
                else:
                    self._stats["rules_engine_hits"] += 1
            else:
                self._stats["rules_engine_hits"] += 1

            # Default fallback
            if category is None:
                category = "Personal"
                confidence = 0.50

            # Priority scoring
            priority = self.priority_scorer.score(subject, sender, category, body)

            return {
                "category": category,
                "confidence": round(confidence, 2),
                "priority": priority,
                "timestamp": datetime.now().isoformat(),
                "source": "rules_engine" if confidence >= 0.70 else "ml_classifier",
            }
            
        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Classification error: {e}")
            return {
                "category": "Personal",
                "confidence": 0.0,
                "priority": "Medium",
                "timestamp": datetime.now().isoformat(),
                "error": str(e)
            }

    def learn_from_feedback(self, predicted_category: str, actual_category: str, sender: str = None):
        try:
            if sender:
                if sender not in self._learned_categories:
                    self._learned_categories[sender] = {}
                
                # Track correction
                if actual_category not in self._learned_categories[sender]:
                    self._learned_categories[sender][actual_category] = 0
                self._learned_categories[sender][actual_category] += 1
        except Exception as e:
            logger.error(f"Learning error: {e}")

    def get_smart_views(self) -> List[str]:
        return [
            "Scam", "Normal", "Urgent", "Waiting Reply", "Finance", "Security",
            "Clients", "Orders", "Trading", "Promotions", "Marketing",
            "Sales", "Social Media", "Investor", "Support", "Leads"
        ]

    def get_stats(self) -> Dict:
        return self._stats.copy()

    def reset_stats(self):
        self._stats = {
            "total_classifications": 0,
            "rules_engine_hits": 0,
            "ml_fallback_hits": 0,
            "scam_filter_hits": 0,
            "errors": 0
        }
