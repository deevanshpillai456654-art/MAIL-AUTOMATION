"""
Adaptive Learning Engine - Core System
========================================

Transforms static AI classifier into self-learning adaptive AI email intelligence.

Submodules:
- Behavioral Learning Engine
- Priority Learning Engine
- Semantic Preference Engine
- Personalization Engine
- Reinforcement Learning Engine
- Confidence Calibration Engine
- AI Memory Engine
- Notification Learning Engine
- Thread Learning Engine
- Search Learning Engine
- Workflow Learning Engine
- Auto-Suggestion Engine
"""

import time
import json
import hashlib
import threading
import logging
import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set, Tuple
from enum import Enum
from collections import deque, defaultdict
from datetime import datetime, timedelta
from backend import config
from backend.db.database import Database

logger = logging.getLogger("ai.learning")


class LearningSignal(Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class MemoryType(Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    BEHAVIORAL = "behavioral"
    SEMANTIC = "semantic"


@dataclass
class LearningFeedback:
    """Learning feedback from user interactions"""
    email_id: int
    sender_email: str
    signal: LearningSignal
    action: str
    category: Optional[str] = None
    priority: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    response_time_ms: Optional[int] = None


@dataclass
class SenderProfile:
    """Learned profile for a sender"""
    email: str
    importance_score: float = 0.5
    reply_likelihood: float = 0.5
    avg_response_time_ms: int = 0
    interaction_count: int = 0
    last_interaction: float = 0
    behavioral_features: Dict[str, float] = field(default_factory=dict)
    category_affinity: Dict[str, float] = field(default_factory=dict)


@dataclass
class UserPreferences:
    """Personalized user preferences learned over time"""
    user_id: int
    confidence_threshold_high: float = 0.85
    confidence_threshold_low: float = 0.3
    notification_enabled: bool = True
    smart_views: List[str] = field(default_factory=list)
    ignored_categories: List[str] = field(default_factory=list)
    vip_senders: Set[str] = field(default_factory=set)
    muted_senders: Set[str] = field(default_factory=set)
    preferred_categories: Dict[str, float] = field(default_factory=dict)
    notification_timing: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BehavioralPattern:
    """Detected behavioral pattern"""
    pattern_id: str
    pattern_type: str
    features: Dict[str, float]
    confidence: float
    last_detected: float
    occurrence_count: int


class AdaptiveLearningEngine:
    """
    Core adaptive learning engine that transforms static AI into self-learning system.
    """

    def __init__(self, db: Database = None, user_id: int = 1):
        self.db = db or Database(config.DB_PATH)
        self.user_id = user_id
        
        # Memory systems
        self.short_term_memory: deque = deque(maxlen=1000)
        self.long_term_memory: Dict[str, SenderProfile] = {}
        self.behavioral_profiles: Dict[str, SenderProfile] = {}
        
        # Learning components
        self.behavioral_engine = BehavioralLearningEngine(self)
        self.priority_engine = PriorityLearningEngine(self)
        self.semantic_engine = SemanticPreferenceEngine(self)
        self.personalization_engine = PersonalizationEngine(self)
        self.reinforcement_engine = ReinforcementEngine(self)
        self.confidence_engine = ConfidenceCalibrationEngine(self)
        self.notification_engine = NotificationLearningEngine(self)
        self.thread_engine = ThreadLearningEngine(self)
        self.search_engine = SearchLearningEngine(self)
        self.workflow_engine = WorkflowLearningEngine(self)
        self.suggestion_engine = AutoSuggestionEngine(self)
        
        # Memory engine
        self.memory_engine = AIMemoryEngine(self)
        
        # Learning configuration
        self.learning_enabled = True
        self.adaptation_rate = 0.1
        self.decay_rate = 0.01
        self.reinforcement_learning_rate = 0.05
        
        # Observability
        self.learning_stats = {
            "total_feedback": 0,
            "positive_signals": 0,
            "negative_signals": 0,
            "adaptations": 0,
            "confidence_recalibrations": 0,
            "pattern_detections": 0
        }
        
        # Lock for thread safety
        self._lock = threading.RLock()
        
        # Load existing memory
        self._load_memory()
        
        logger.info(f"Adaptive Learning Engine initialized for user {user_id}")

    def _load_memory(self):
        """Load existing learning memory from database"""
        try:
            memory_data = self.db.fetch_all(
                "SELECT * FROM ai_memory WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1000",
                (self.user_id,)
            )
            for row in memory_data:
                memory_type = row.get("memory_type")
                key = row.get("memory_key")
                value_json = row.get("memory_value")
                
                if value_json:
                    try:
                        value = json.loads(value_json)
                        if memory_type == "sender_profile":
                            profile = SenderProfile(
                                email=value.get("email", key),
                                importance_score=value.get("importance_score", 0.5),
                                reply_likelihood=value.get("reply_likelihood", 0.5),
                                avg_response_time_ms=value.get("avg_response_time_ms", 0),
                                interaction_count=value.get("interaction_count", 0),
                                last_interaction=value.get("last_interaction", 0),
                                behavioral_features=value.get("behavioral_features", {}),
                                category_affinity=value.get("category_affinity", {})
                            )
                            self.long_term_memory[key] = profile
                            self.behavioral_profiles[key] = profile
                        elif memory_type == "user_preferences":
                            prefs = UserPreferences(
                                user_id=self.user_id,
                                confidence_threshold_high=value.get("confidence_threshold_high", 0.85),
                                confidence_threshold_low=value.get("confidence_threshold_low", 0.3),
                                notification_enabled=value.get("notification_enabled", True),
                                smart_views=value.get("smart_views", []),
                                ignored_categories=value.get("ignored_categories", []),
                                vip_senders=set(value.get("vip_senders", [])),
                                muted_senders=set(value.get("muted_senders", [])),
                                preferred_categories=value.get("preferred_categories", {}),
                                notification_timing=value.get("notification_timing", {})
                            )
                            self.personalization_engine.preferences = prefs
                    except json.JSONDecodeError:
                        pass
            logger.info(f"Loaded {len(self.long_term_memory)} sender profiles from memory")
        except Exception as e:
            logger.warning(f"Could not load AI memory: {e}")

    def process_feedback(self, feedback: LearningFeedback):
        """Process learning feedback from user interactions"""
        with self._lock:
            if not self.learning_enabled:
                return
            
            self.learning_stats["total_feedback"] += 1
            
            if feedback.signal == LearningSignal.POSITIVE:
                self.learning_stats["positive_signals"] += 1
            elif feedback.signal == LearningSignal.NEGATIVE:
                self.learning_stats["negative_signals"] += 1
            
            # Store in short-term memory
            self.short_term_memory.append(feedback)
            
            # Process through all learning engines
            self.behavioral_engine.process_feedback(feedback)
            self.priority_engine.process_feedback(feedback)
            self.semantic_engine.process_feedback(feedback)
            self.notification_engine.process_feedback(feedback)
            self.thread_engine.process_feedback(feedback)
            self.search_engine.process_feedback(feedback)
            self.workflow_engine.process_feedback(feedback)
            
            # Apply reinforcement learning
            self.reinforcement_engine.process_feedback(feedback)
            
            # Update memory
            self.memory_engine.store_feedback(feedback)
            
            self.learning_stats["adaptations"] += 1
            
            logger.debug(f"Processed feedback: {feedback.signal.value} - {feedback.action}")

    def get_sender_profile(self, sender_email: str) -> SenderProfile:
        """Get or create sender profile"""
        with self._lock:
            if sender_email not in self.long_term_memory:
                self.long_term_memory[sender_email] = SenderProfile(email=sender_email)
            return self.long_term_memory[sender_email]

    def get_personalization(self) -> UserPreferences:
        """Get user personalization settings"""
        return self.personalization_engine.get_preferences()

    def get_priority_boost(self, sender_email: str, category: str) -> float:
        """Get priority boost based on learned behavior"""
        return self.priority_engine.get_priority_boost(sender_email, category)

    def get_category_importance(self, category: str) -> float:
        """Get learned category importance"""
        return self.semantic_engine.get_category_importance(category)

    def should_notify(self, email_data: Dict) -> bool:
        """Determine if notification should be sent based on learning"""
        return self.notification_engine.should_notify(email_data, self.get_personalization())

    def get_suggestions(self) -> List[Dict]:
        """Get AI-generated suggestions based on learning"""
        return self.suggestion_engine.generate_suggestions()

    def get_explainability(self, email_id: int, reason: str) -> Dict:
        """Get explainability for AI decision"""
        return {
            "email_id": email_id,
            "reason": reason,
            "factors": self._get_decision_factors(email_id),
            "confidence": self.confidence_engine.get_adjusted_confidence(email_id),
            "learned_from": self._get_learned_factors(email_id)
        }

    def _get_decision_factors(self, email_id: int) -> List[Dict]:
        """Get factors that influenced the decision"""
        factors = []
        email = self.db.get_email_by_id(email_id)
        if email:
            sender = email.get("sender_email", "")
            profile = self.get_sender_profile(sender)
            
            if profile.importance_score > 0.7:
                factors.append({
                    "factor": "high_sender_importance",
                    "weight": profile.importance_score,
                    "description": f"Sender {sender} is frequently interacted with"
                })
            
            if sender in self.personalization_engine.preferences.vip_senders:
                factors.append({
                    "factor": "vip_sender",
                    "weight": 1.0,
                    "description": "Sender is in VIP list"
                })
            
            category = email.get("category")
            if category:
                importance = self.semantic_engine.get_category_importance(category)
                if importance > 0.7:
                    factors.append({
                        "factor": "important_category",
                        "weight": importance,
                        "description": f"Category '{category}' is often important"
                    })
        
        return factors

    def _get_learned_factors(self, email_id: int) -> List[str]:
        """Get factors learned from user behavior"""
        factors = []
        email = self.db.get_email_by_id(email_id)
        if email:
            sender = email.get("sender_email", "")
            profile = self.get_sender_profile(sender)
            
            if profile.interaction_count > 10:
                factors.append(f"Frequent interaction ({profile.interaction_count} times)")
            
            if profile.reply_likelihood > 0.7:
                factors.append("High reply likelihood")
            
            if profile.avg_response_time_ms < 60000:
                factors.append("Quick response pattern")
            
            if profile.importance_score > 0.8:
                factors.append("Sustained positive interaction")
        
        return factors

    def reset_learning(self, user_id: int = None):
        """Reset learning memory for a user"""
        with self._lock:
            target_user = user_id or self.user_id
            
            self.long_term_memory.clear()
            self.behavioral_profiles.clear()
            self.short_term_memory.clear()
            
            self.db.execute(
                "DELETE FROM ai_memory WHERE user_id = ?",
                (target_user,)
            )
            
            self.personalization_engine.reset()
            self.confidence_engine.reset()
            
            logger.info(f"Reset learning for user {target_user}")

    def get_learning_stats(self) -> Dict:
        """Get learning statistics"""
        return {
            **self.learning_stats,
            "memory_size": len(self.long_term_memory),
            "behavioral_profiles": len(self.behavioral_profiles),
            "short_term_memory": len(self.short_term_memory)
        }


class AIMemoryEngine:
    """AI Memory system with short-term and long-term memory"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        self.user_id = learning_engine.user_id
        
        # Memory configuration
        self.short_term_decay = 0.1
        self.long_term_threshold = 100
        self.importance_weight = 0.3
        self.recency_weight = 0.4
        self.consistency_weight = 0.3

    def store_feedback(self, feedback: LearningFeedback):
        """Store feedback in appropriate memory layer"""
        sender = feedback.sender_email
        
        # Get or create sender profile
        profile = self.learning_engine.get_sender_profile(sender)
        
        # Update profile based on signal
        if feedback.signal == LearningSignal.POSITIVE:
            profile.importance_score = min(1.0, profile.importance_score + 0.05)
            profile.interaction_count += 1
        elif feedback.signal == LearningSignal.NEGATIVE:
            profile.importance_score = max(0.0, profile.importance_score - 0.1)
        
        # Update response time
        if feedback.response_time_ms:
            if profile.avg_response_time_ms == 0:
                profile.avg_response_time_ms = feedback.response_time_ms
            else:
                profile.avg_response_time_ms = int(
                    0.7 * profile.avg_response_time_ms + 0.3 * feedback.response_time_ms
                )
        
        profile.last_interaction = feedback.timestamp
        
        # Store category affinity
        if feedback.category:
            if feedback.category not in profile.category_affinity:
                profile.category_affinity[feedback.category] = 0.0
            
            if feedback.signal == LearningSignal.POSITIVE:
                profile.category_affinity[feedback.category] = min(
                    1.0, profile.category_affinity[feedback.category] + 0.1
                )
            elif feedback.signal == LearningSignal.NEGATIVE:
                profile.category_affinity[feedback.category] = max(
                    0.0, profile.category_affinity[feedback.category] - 0.15
                )
        
        # Persist to database
        self._persist_profile(profile)

    def _persist_profile(self, profile: SenderProfile):
        """Persist sender profile to database"""
        value = {
            "email": profile.email,
            "importance_score": profile.importance_score,
            "reply_likelihood": profile.reply_likelihood,
            "avg_response_time_ms": profile.avg_response_time_ms,
            "interaction_count": profile.interaction_count,
            "last_interaction": profile.last_interaction,
            "behavioral_features": profile.behavioral_features,
            "category_affinity": profile.category_affinity
        }
        
        self.db.execute("""
            INSERT OR REPLACE INTO ai_memory 
            (user_id, memory_type, memory_key, memory_value, updated_at)
            VALUES (?, ?, ?, ?, ?)
        """, (
            self.user_id,
            "sender_profile",
            profile.email,
            json.dumps(value),
            datetime.now().isoformat()
        ))


class BehavioralLearningEngine:
    """Learns from user behavioral patterns"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        
        # Behavioral tracking
        self.open_times: Dict[str, List[float]] = defaultdict(list)
        self.reply_times: Dict[str, List[int]] = defaultdict(list)
        self.ignored_senders: Set[str] = set()
        self.quick_reply_senders: Set[str] = set()

    def process_feedback(self, feedback: LearningFeedback):
        """Process behavioral feedback"""
        sender = feedback.sender_email
        
        if feedback.action == "opened":
            if feedback.response_time_ms:
                self.open_times[sender].append(feedback.response_time_ms)
                if feedback.response_time_ms < 30000:  # < 30 seconds
                    self.quick_reply_senders.add(sender)
        
        elif feedback.action == "replied":
            if feedback.response_time_ms:
                self.reply_times[sender].append(feedback.response_time_ms)
        
        elif feedback.action in ["deleted", "ignored"]:
            self.ignored_senders.add(sender)
        
        # Update sender profile
        profile = self.learning_engine.get_sender_profile(sender)
        
        # Calculate behavioral features
        if sender in self.open_times:
            avg_open_time = np.mean(self.open_times[sender])
            profile.behavioral_features["avg_open_time"] = avg_open_time
            
            if avg_open_time < 60000:
                profile.behavioral_features["quick_open"] = 1.0
            else:
                profile.behavioral_features["quick_open"] = max(0, 1.0 - (avg_open_time / 300000))
        
        # Update reply likelihood
        if sender in self.reply_times:
            avg_reply = np.mean(self.reply_times[sender])
            profile.reply_likelihood = 1.0 if avg_reply < 300000 else max(0, 1.0 - (avg_reply / 600000))


class PriorityLearningEngine:
    """Learns and adapts priority scoring"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        
        # Priority learning
        self.vip_senders: Set[str] = set()
        self.urgent_patterns: Dict[str, float] = {}
        self.category_priority: Dict[str, float] = {
            "Finance": 0.8,
            "OTP": 0.9,
            "Clients": 0.85,
            "Urgent": 0.95,
            "Security": 0.9,
            "Promotions": 0.3,
            "Newsletters": 0.2,
            "Personal": 0.5,
            "Bills": 0.8
        }

    def process_feedback(self, feedback: LearningFeedback):
        """Process priority-related feedback"""
        sender = feedback.sender_email
        
        # Update VIP senders based on positive interactions
        if feedback.signal == LearningSignal.POSITIVE:
            if feedback.action in ["starred", "replied", "moved_to_vip"]:
                self.vip_senders.add(sender)
                
                profile = self.learning_engine.get_sender_profile(sender)
                profile.importance_score = min(1.0, profile.importance_score + 0.2)
        
        # Update category priority based on user behavior
        if feedback.category:
            if feedback.signal == LearningSignal.POSITIVE:
                current = self.category_priority.get(feedback.category, 0.5)
                self.category_priority[feedback.category] = min(1.0, current + 0.1)
            elif feedback.signal == LearningSignal.NEGATIVE:
                if feedback.action in ["moved_to_spam", "deleted"]:
                    current = self.category_priority.get(feedback.category, 0.5)
                    self.category_priority[feedback.category] = max(0.1, current - 0.15)

    def get_priority_boost(self, sender_email: str, category: str) -> float:
        """Calculate priority boost based on learned behavior"""
        boost = 1.0
        
        # VIP boost
        if sender_email in self.vip_senders:
            boost += 0.5
        
        # Sender importance boost
        profile = self.learning_engine.get_sender_profile(sender_email)
        boost += (profile.importance_score - 0.5) * 0.5
        
        # Category boost
        if category in self.category_priority:
            boost *= self.category_priority[category]
        
        return min(2.0, max(0.5, boost))


class SemanticPreferenceEngine:
    """Learns user-specific semantic preferences"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        
        # Semantic preferences per user
        self.category_importance: Dict[str, Dict[str, float]] = defaultdict(dict)
        self.word_importance: Dict[str, Dict[str, float]] = defaultdict(dict)
        self.topic_preferences: Dict[str, float] = {}

    def process_feedback(self, feedback: LearningFeedback):
        """Process semantic preference feedback"""
        sender = feedback.sender_email
        
        # Learn from category overrides
        if feedback.category:
            if feedback.signal == LearningSignal.POSITIVE:
                self.category_importance[self.learning_engine.user_id][feedback.category] = min(
                    1.0,
                    self.category_importance[self.learning_engine.user_id].get(feedback.category, 0.5) + 0.1
                )
            elif feedback.signal == LearningSignal.NEGATIVE:
                self.category_importance[self.learning_engine.user_id][feedback.category] = max(
                    0.1,
                    self.category_importance[self.learning_engine.user_id].get(feedback.category, 0.5) - 0.15
                )

    def get_category_importance(self, category: str) -> float:
        """Get learned category importance for user"""
        return self.category_importance[self.learning_engine.user_id].get(
            category, 
            self._get_default_importance(category)
        )

    def _get_default_importance(self, category: str) -> float:
        defaults = {
            "Finance": 0.7, "OTP": 0.8, "Clients": 0.75, "Urgent": 0.9,
            "Security": 0.85, "Promotions": 0.3, "Newsletters": 0.2,
            "Personal": 0.5, "Bills": 0.75, "Orders": 0.7
        }
        return defaults.get(category, 0.5)


class PersonalizationEngine:
    """Full personalization system for user preferences"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        self.preferences = UserPreferences(user_id=learning_engine.user_id)
        
        self._load_preferences()

    def _load_preferences(self):
        """Load preferences from database"""
        prefs_data = self.db.fetch_all(
            "SELECT * FROM user_preferences WHERE user_id = ?",
            (self.learning_engine.user_id,)
        )
        
        if prefs_data:
            data = prefs_data[0]
            self.preferences.confidence_threshold_high = data.get(
                "confidence_threshold_high", 0.85
            )
            self.preferences.confidence_threshold_low = data.get(
                "confidence_threshold_low", 0.3
            )
            self.preferences.notification_enabled = data.get(
                "notification_enabled", True
            )
            self.preferences.vip_senders = set(json.loads(
                data.get("vip_senders", "[]")
            ))
            self.preferences.muted_senders = set(json.loads(
                data.get("muted_senders", "[]")
            ))

    def get_preferences(self) -> UserPreferences:
        """Get current user preferences"""
        return self.preferences

    def process_feedback(self, feedback: LearningFeedback):
        """Update preferences based on feedback"""
        sender = feedback.sender_email
        
        if feedback.action == "starred" or feedback.signal == LearningSignal.POSITIVE:
            self.preferences.vip_senders.add(sender)
        elif feedback.action == "muted" or feedback.action == "ignored":
            self.preferences.muted_senders.add(sender)
        
        if feedback.category:
            self.preferences.preferred_categories[feedback.category] = (
                self.preferences.preferred_categories.get(feedback.category, 0.5) + 0.1
            )

    def reset(self):
        """Reset preferences to defaults"""
        self.preferences = UserPreferences(user_id=self.learning_engine.user_id)


class ReinforcementEngine:
    """Lightweight reinforcement learning for continuous improvement"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        
        # Q-learning parameters
        self.learning_rate = 0.1
        self.discount_factor = 0.9
        self.exploration_rate = 0.1
        
        # Q-table for actions
        self.q_table: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    def process_feedback(self, feedback: LearningFeedback):
        """Apply reinforcement learning"""
        state = self._get_state(feedback)
        action = feedback.action
        
        # Calculate reward
        reward = self._calculate_reward(feedback)
        
        # Update Q-value
        old_q = self.q_table[state][action]
        max_next_q = max(self.q_table[state].values()) if self.q_table[state] else 0
        
        new_q = old_q + self.learning_rate * (reward + self.discount_factor * max_next_q - old_q)
        self.q_table[state][action] = new_q

    def _get_state(self, feedback: LearningFeedback) -> str:
        """Get state representation"""
        profile = self.learning_engine.get_sender_profile(feedback.sender_email)
        
        if profile.importance_score > 0.7:
            importance = "high"
        elif profile.importance_score < 0.3:
            importance = "low"
        else:
            importance = "medium"
        
        category = feedback.category or "unknown"
        
        return f"{importance}_{category}"

    def _calculate_reward(self, feedback: LearningFeedback) -> float:
        """Calculate reward for action"""
        if feedback.signal == LearningSignal.POSITIVE:
            return 1.0
        elif feedback.signal == LearningSignal.NEGATIVE:
            return -1.0
        return 0.0


class ConfidenceCalibrationEngine:
    """Dynamically adjusts confidence thresholds"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        
        # Override tracking
        self.overrides: Dict[str, int] = defaultdict(int)
        self.correct_predictions: Dict[str, int] = defaultdict(int)
        
        # Confidence adjustments
        self.category_confidence: Dict[str, float] = {}

    def process_feedback(self, feedback: LearningFeedback):
        """Calibrate confidence based on user overrides"""
        if feedback.category:
            self.overrides[feedback.category] += 1
            
            # Track if prediction was correct
            # This would need to compare with actual classification
        
        # Adjust confidence based on override patterns
        for category, override_count in self.overrides.items():
            total = override_count
            if total > 10:
                override_rate = override_count / total
                
                if override_rate > 0.5:
                    # Low confidence - user often disagrees
                    self.category_confidence[category] = max(0.3, 
                        self.category_confidence.get(category, 0.7) - 0.1)
                elif override_rate < 0.1:
                    # High confidence - user agrees
                    self.category_confidence[category] = min(1.0,
                        self.category_confidence.get(category, 0.7) + 0.05)

    def get_adjusted_confidence(self, email_id: int) -> float:
        """Get confidence adjusted based on learning"""
        # For email_id 0, just return default
        if email_id == 0:
            return 0.7
        
        email = self.db.fetch_one("SELECT * FROM emails WHERE id = ?", (email_id,))
        if email and email.get("category"):
            return self.category_confidence.get(email["category"], 0.7)
        return 0.7

    def reset(self):
        """Reset calibration"""
        self.overrides.clear()
        self.correct_predictions.clear()
        self.category_confidence.clear()


class NotificationLearningEngine:
    """Learns notification preferences and timing"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        
        # Notification patterns
        self.notified_senders: Dict[str, int] = defaultdict(int)
        self.dismissed_notifications: Set[str] = set()
        self.acted_notifications: Dict[str, int] = defaultdict(int)
        self.notification_timing: Dict[str, List[int]] = defaultdict(list)

    def process_feedback(self, feedback: LearningFeedback):
        """Learn from notification interactions"""
        sender = feedback.sender_email
        
        if feedback.action == "notification_dismissed":
            self.dismissed_notifications.add(sender)
            self.notified_senders[sender] -= 1
        
        elif feedback.action in ["opened", "replied", "starred"]:
            if sender in self.notified_senders:
                self.acted_notifications[sender] += 1

    def should_notify(self, email_data: Dict, preferences: UserPreferences) -> bool:
        """Determine if notification should be sent"""
        sender = email_data.get("sender_email", "")
        
        # Don't notify for muted senders
        if sender in preferences.muted_senders:
            return False
        
        # Don't notify for ignored categories
        category = email_data.get("category")
        if category and category in preferences.ignored_categories:
            return False
        
        # Check sender notification history
        if sender in self.dismissed_notifications:
            # Only notify for high importance
            profile = self.learning_engine.get_sender_profile(sender)
            return profile.importance_score > 0.8
        
        # Check acted ratio
        if sender in self.notified_senders and sender in self.acted_notifications:
            total = self.notified_senders[sender]
            acted = self.acted_notifications[sender]
            if total > 5:
                return (acted / total) > 0.3
        
        return True


class ThreadLearningEngine:
    """Learns from email thread patterns"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        
        # Thread patterns
        self.important_threads: Set[str] = set()
        self.thread_participants: Dict[str, Set[str]] = defaultdict(set)

    def process_feedback(self, feedback: LearningFeedback):
        """Learn from thread interactions"""
        # This would require thread_id from email
        pass


class SearchLearningEngine:
    """Learns from search behavior"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        
        # Search patterns
        self.search_queries: List[Tuple[str, int, float]] = []
        self.clicked_results: Dict[str, int] = defaultdict(int)
        self.query_refinements: List[Tuple[str, str, float]] = []

    def process_feedback(self, feedback: LearningFeedback):
        """Learn from search behavior"""
        if feedback.action == "searched":
            self.search_queries.append((
                feedback.email_id,  # Using as query proxy
                1,
                feedback.timestamp
            ))
        
        elif feedback.action == "clicked_result":
            self.clicked_results[str(feedback.email_id)] += 1


class WorkflowLearningEngine:
    """Learns user automation workflows"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        self.db = learning_engine.db
        
        # Workflow patterns
        self.action_sequences: List[Tuple[str, str, int]] = []
        self.automation_suggestions: List[Dict] = []

    def process_feedback(self, feedback: LearningFeedback):
        """Learn workflow patterns"""
        if feedback.action in ["moved", "categorized", "starred"]:
            # Detect patterns for automation suggestions
            pass

    def detect_automations(self) -> List[Dict]:
        """Detect potential automations"""
        suggestions = []
        
        # Analyze move patterns
        # If user consistently moves certain category to certain folder
        # suggest automation
        
        return suggestions


class AutoSuggestionEngine:
    """Generates intelligent AI suggestions"""

    def __init__(self, learning_engine: AdaptiveLearningEngine):
        self.learning_engine = learning_engine
        
    def generate_suggestions(self) -> List[Dict]:
        """Generate AI-powered suggestions"""
        suggestions = []
        
        # Suggest VIP senders
        prefs = self.learning_engine.personalization_engine.preferences
        for email, profile in self.learning_engine.long_term_memory.items():
            if profile.importance_score > 0.8 and email not in prefs.vip_senders:
                suggestions.append({
                    "type": "vip_suggestion",
                    "title": f"Add {email} to VIP?",
                    "description": f"Frequently interacts with this sender ({profile.interaction_count} times)",
                    "action": "add_vip",
                    "data": {"email": email}
                })
        
        # Suggest category refinements
        for category, count in self.learning_engine.behavioral_engine.ignored_senders:
            suggestions.append({
                "type": "category_suggestion",
                "title": f"Reduce '{category}' notifications?",
                "description": "Frequently ignoring this category",
                "action": "mute_category",
                "data": {"category": category}
            })
        
        # Suggest rule creation
        suggestions.append({
            "type": "rule_suggestion",
            "title": "Create automation for important senders?",
            "description": "Automatically categorize emails from VIP senders",
            "action": "create_rule",
            "data": {"condition": "sender_in_vip", "action": "label_important"}
        })
        
        return suggestions[:10]


def get_learning_engine(user_id: int = 1) -> AdaptiveLearningEngine:
    """Get or create learning engine for user"""
    global _learning_engines
    
    if '_learning_engines' not in globals():
        _learning_engines = {}
    
    if user_id not in _learning_engines:
        _learning_engines[user_id] = AdaptiveLearningEngine(user_id=user_id)
    
    return _learning_engines[user_id]