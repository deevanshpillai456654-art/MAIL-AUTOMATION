"""
Adaptive AI Pipeline Integration
=================================

Extends existing AI pipeline with adaptive learning capabilities.

Incoming Email
→ Fast Path
→ Behavioral Weighting
→ Semantic Weighting
→ Personalized Ranking
→ Classification
→ Confidence Calibration
→ Smart Inbox
→ Learning Feedback Loop
"""

import logging
from typing import Dict, List, Optional

from backend import config
from backend.ai.classifier import EmailClassifier
from backend.ai.learning_engine import LearningFeedback, LearningSignal, get_learning_engine
from backend.db.database import Database

logger = logging.getLogger("ai.pipeline")


class AdaptiveAI:
    """
    Adaptive AI pipeline that integrates learning with classification.
    
    Extends the static classifier with:
    - Behavioral learning
    - Priority adaptation
    - Semantic personalization
    - Confidence calibration
    - Smart inbox evolution
    """

    def __init__(self, db: Database = None, user_id: int = 1):
        self.db = db or Database(config.DB_PATH)
        self.user_id = user_id

        # Base classifier
        self.classifier = EmailClassifier()

        # Adaptive learning engine
        self.learning_engine = get_learning_engine(user_id)

        logger.info(f"Adaptive AI initialized for user {user_id}")

    def classify_adaptive(self, email_data: Dict) -> Dict:
        """
        Classify email with adaptive learning integration.
        """
        sender = email_data.get("sender_email", "")
        subject = email_data.get("subject", "")
        body = email_data.get("body_text", "")

        # Step 1: Get behavioral priority boost
        priority_boost = self.learning_engine.get_priority_boost(
            sender,
            email_data.get("category", "")
        )

        # Step 2: Get semantic importance
        category = email_data.get("category")
        if category:
            category_importance = self.learning_engine.get_category_importance(category)
        else:
            category_importance = 0.5

        # Step 3: Get personalization settings
        prefs = self.learning_engine.get_personalization()

        # Step 4: Run base classification
        base_result = self.classifier.classify(
            email_data.get("subject", ""),
            email_data.get("sender", ""),
            email_data.get("sender_email", ""),
            email_data.get("body_text", "")
        )

        # Convert to dict format if needed
        if isinstance(base_result, tuple):
            base_result = {
                "category": base_result[0],
                "confidence": base_result[1],
                "priority": "Medium"
            }

        # Step 5: Apply priority adaptation
        if priority_boost > 1.2:
            if base_result.get("priority") in ["Low", "Medium"]:
                base_result["priority"] = "High"
            base_result["priority_score"] = base_result.get("priority_score", 0.5) * priority_boost

        # Step 6: Adjust confidence based on learning
        adjusted_confidence = self._adjust_confidence(
            base_result.get("category", ""),
            base_result.get("confidence", 0.5),
            sender
        )
        base_result["confidence"] = adjusted_confidence

        # Step 7: Determine action based on confidence thresholds
        action = self._determine_action(
            adjusted_confidence,
            prefs,
            sender in prefs.vip_senders
        )
        base_result["action"] = action

        # Step 8: Add adaptive metadata
        base_result["adaptive"] = {
            "priority_boost": priority_boost,
            "category_importance": category_importance,
            "is_vip": sender in prefs.vip_senders,
            "learning_enabled": self.learning_engine.learning_enabled,
            "explainability": self._generate_explainability(
                sender,
                base_result.get("category", ""),
                priority_boost
            )
        }

        return base_result

    def _adjust_confidence(self, category: str, base_confidence: float, sender: str) -> float:
        """Adjust confidence based on learning"""
        # Get confidence calibration for category
        confidence_engine = self.learning_engine.confidence_engine
        category_confidence = confidence_engine.get_adjusted_confidence(0)

        # Adjust based on sender profile
        profile = self.learning_engine.get_sender_profile(sender)

        # High interaction sender = higher confidence
        if profile.interaction_count > 20:
            sender_confidence = 1.2
        elif profile.interaction_count > 10:
            sender_confidence = 1.1
        elif profile.interaction_count == 0:
            sender_confidence = 0.9
        else:
            sender_confidence = 1.0

        # Combine adjustments
        adjusted = base_confidence * (category_confidence / 0.7) * sender_confidence

        return min(1.0, max(0.1, adjusted))

    def _determine_action(self, confidence: float, prefs, is_vip: bool) -> str:
        """Determine action based on confidence and preferences"""
        if is_vip:
            return "notify"

        if confidence >= prefs.confidence_threshold_high:
            return "auto_move"
        elif confidence >= prefs.confidence_threshold_low:
            return "suggest"
        else:
            return "ignore"

    def _generate_explainability(self, sender: str, category: str, priority_boost: float) -> Dict:
        """Generate explainability for the classification"""
        profile = self.learning_engine.get_sender_profile(sender)

        factors = []

        if priority_boost > 1.5:
            factors.append("High sender importance detected")

        if profile.interaction_count > 10:
            factors.append(f"Frequent interaction ({profile.interaction_count} times)")

        if sender in self.learning_engine.personalization_engine.preferences.vip_senders:
            factors.append("VIP sender")

        if category:
            importance = self.learning_engine.get_category_importance(category)
            if importance > 0.7:
                factors.append(f"Category '{category}' is important to user")

        return {
            "factors": factors,
            "priority_boost": priority_boost,
            "sender_importance": profile.importance_score
        }

    def _get_email_by_id(self, email_id: int) -> Optional[Dict]:
        """Get email by ID"""
        result = self.db.fetch_one("SELECT * FROM emails WHERE id = ?", (email_id,))
        return result

    def process_feedback(self, email_id: int, action: str, signal: LearningSignal,
                         category: Optional[str] = None, priority: Optional[str] = None,
                         response_time_ms: Optional[int] = None):
        """Process user feedback for learning"""
        email = self._get_email_by_id(email_id) or {}
        sender_email = email.get("sender_email") or "unknown@local"

        feedback = LearningFeedback(
            email_id=email_id,
            sender_email=sender_email,
            signal=signal,
            action=action,
            category=category or email.get("category"),
            priority=priority or email.get("priority"),
            response_time_ms=response_time_ms
        )

        # Learning should not be dropped just because the local message row was
        # pruned or the event arrived before persistence. Missing emails are
        # recorded with an explicit synthetic sender instead of silently losing
        # the feedback signal.
        self.learning_engine.process_feedback(feedback)

        self.db.execute("""
            INSERT INTO learning_feedback
            (user_id, email_id, sender_email, signal, action, category, priority, response_time_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            self.user_id,
            email_id,
            sender_email,
            signal.value,
            action,
            feedback.category,
            feedback.priority,
            response_time_ms
        ))

    def record_email_open(self, email_id: int, response_time_ms: int = None):
        """Record email open for behavioral learning"""
        self.process_feedback(
            email_id=email_id,
            action="opened",
            signal=LearningSignal.POSITIVE,
            response_time_ms=response_time_ms
        )

    def record_email_reply(self, email_id: int, response_time_ms: int):
        """Record email reply for behavioral learning"""
        self.process_feedback(
            email_id=email_id,
            action="replied",
            signal=LearningSignal.POSITIVE,
            response_time_ms=response_time_ms
        )

    def record_manual_classification(self, email_id: int, category: str, correct: bool):
        """Record manual classification override"""
        signal = LearningSignal.POSITIVE if correct else LearningSignal.NEGATIVE
        self.process_feedback(
            email_id=email_id,
            action="reclassified",
            signal=signal,
            category=category
        )

    def record_email_move(self, email_id: int, to_folder: str):
        """Record email move for workflow learning"""
        action = f"moved_to_{to_folder}"

        # Determine signal based on folder
        if to_folder in ["spam", "trash"]:
            signal = LearningSignal.NEGATIVE
        elif to_folder in ["important", "starred", "vip"]:
            signal = LearningSignal.POSITIVE
        else:
            signal = LearningSignal.NEUTRAL

        self.process_feedback(
            email_id=email_id,
            action=action,
            signal=signal
        )

    def record_star(self, email_id: int, starred: bool):
        """Record star toggle"""
        action = "starred" if starred else "unstarred"
        signal = LearningSignal.POSITIVE if starred else LearningSignal.NEUTRAL

        self.process_feedback(
            email_id=email_id,
            action=action,
            signal=signal
        )

    def record_notification_dismiss(self, email_id: int):
        """Record notification dismissal"""
        self.process_feedback(
            email_id=email_id,
            action="notification_dismissed",
            signal=LearningSignal.NEGATIVE
        )

    def record_search(self, query: str):
        """Record search for search learning"""
        self.learning_engine.search_engine.process_feedback(
            LearningFeedback(
                email_id=0,
                sender_email="",
                action="searched",
                signal=LearningSignal.NEUTRAL
            )
        )

    def get_adaptive_suggestions(self) -> List[Dict]:
        """Get AI-generated suggestions based on learning"""
        return self.learning_engine.get_suggestions()

    def get_learning_stats(self) -> Dict:
        """Get learning statistics"""
        return self.learning_engine.get_learning_stats()

    def get_explainability(self, email_id: int) -> Dict:
        """Get explainability for an email classification"""
        email = self._get_email_by_id(email_id)
        if not email:
            return {}

        sender = email.get("sender_email", "")
        category = email.get("category", "")

        profile = self.learning_engine.get_sender_profile(sender)
        priority_boost = self.learning_engine.get_priority_boost(sender, category)

        return {
            "email_id": email_id,
            "sender": sender,
            "sender_importance": profile.importance_score,
            "interaction_count": profile.interaction_count,
            "is_vip": sender in self.learning_engine.personalization_engine.preferences.vip_senders,
            "priority_boost": priority_boost,
            "category_importance": self.learning_engine.get_category_importance(category),
            "factors": self._generate_explainability(sender, category, priority_boost).get("factors", []),
            "confidence": self._adjust_confidence(category, 0.7, sender)
        }

    def reset_learning(self):
        """Reset all learning for this user"""
        self.learning_engine.reset_learning(self.user_id)


def get_adaptive_ai(user_id: int = 1) -> AdaptiveAI:
    """Get or create adaptive AI instance"""
    global _adaptive_ais

    if '_adaptive_ais' not in globals():
        _adaptive_ais = {}

    if user_id not in _adaptive_ais:
        _adaptive_ais[user_id] = AdaptiveAI(user_id=user_id)

    return _adaptive_ais[user_id]
