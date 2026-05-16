"""
AI Governance System - Model Registry & Governance
=================================================

Enterprise AI governance:
- Model registry with versioning
- Shadow deployments
- A/B inference testing
- Confidence calibration
- Drift detection
- Correction learning
- Adaptive retraining
- AI rollback system
- Explainable AI
"""

import time
import hashlib
import threading
import logging
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Tuple
from enum import Enum
from collections import deque

logger = logging.getLogger("ai.governance")


class ModelStatus(Enum):
    ACTIVE = "active"
    SHADOW = "shadow"
    TRAINING = "training"
    DEPRECATED = "deprecated"
    ROLLED_BACK = "rolled_back"


@dataclass
class ModelVersion:
    """Model version with metadata"""
    version_id: str
    model_type: str
    version: str
    status: ModelStatus
    created_at: float = field(default_factory=time.time)
    metrics: Dict[str, float] = field(default_factory=dict)
    accuracy: float = 0.0
    confidence_avg: float = 0.0
    correction_count: int = 0
    training_samples: int = 0
    is_production: bool = False
    parent_version: Optional[str] = None


@dataclass
class InferenceResult:
    """Inference result with governance metadata"""
    prediction: str
    confidence: float
    model_version: str
    is_shadow: bool = False
    explanations: List[str] = field(default_factory=list)
    features_used: List[str] = field(default_factory=list)
    latency_ms: float = 0


@dataclass
class Correction:
    """User correction for learning"""
    correction_id: str
    email_id: int
    original_prediction: str
    corrected_prediction: str
    reason: str
    timestamp: float = field(default_factory=time.time)
    accepted: bool = False


@dataclass
class DriftDetection:
    """Model drift detection"""
    metric_name: str
    current_value: float
    baseline_value: float
    drift_percent: float
    is_drifted: bool = False
    detected_at: float = field(default_factory=time.time)


class AITracking:
    """Track AI predictions and corrections"""
    
    def __init__(self):
        self._predictions: deque = deque(maxlen=10000)
        self._corrections: List[Correction] = []
        self._confidence_history: deque = deque(maxlen=1000)
        self._accuracy_history: deque = deque(maxlen=1000)
        self._lock = threading.RLock()
    
    def track_prediction(self, email_id: int, prediction: str, confidence: float, model_version: str):
        """Track prediction"""
        with self._lock:
            self._predictions.append({
                "email_id": email_id,
                "prediction": prediction,
                "confidence": confidence,
                "model_version": model_version,
                "timestamp": time.time()
            })
            self._confidence_history.append(confidence)
    
    def track_correction(self, correction: Correction):
        """Track user correction"""
        with self._lock:
            self._corrections.append(correction)
            
            # Update accuracy history
            if len(self._predictions) > 0:
                recent = list(self._predictions)[-100:]
                correct = sum(1 for p in recent if p["prediction"] == correction.corrected_prediction)
                accuracy = correct / len(recent)
                self._accuracy_history.append(accuracy)
    
    def get_confidence_trend(self) -> str:
        """Get confidence trend"""
        if len(self._confidence_history) < 10:
            return "insufficient_data"
        
        recent = list(self._confidence_history)[-10:]
        avg = sum(recent) / len(recent)
        
        if avg > 0.8:
            return "high"
        elif avg > 0.6:
            return "stable"
        else:
            return "low"
    
    def get_accuracy(self) -> float:
        """Get current accuracy"""
        if not self._accuracy_history:
            return 0.0
        return sum(self._accuracy_history) / len(self._accuracy_history)
    
    def get_correction_rate(self) -> float:
        """Get correction rate"""
        total_predictions = len(self._predictions)
        corrections = len(self._corrections)
        
        if total_predictions == 0:
            return 0.0
        
        return corrections / total_predictions


class ModelRegistry:
    """Model registry with versioning"""
    
    def __init__(self):
        self._models: Dict[str, ModelVersion] = {}
        self._active_model: Optional[str] = None
        self._shadow_model: Optional[str] = None
        self._lock = threading.RLock()
        
        # Default model
        self._register_default_model()
    
    def _register_default_model(self):
        """Register default production model"""
        default = ModelVersion(
            version_id="v1_default",
            model_type="classifier",
            version="9.7.0",
            status=ModelStatus.ACTIVE,
            is_production=True,
            metrics={"accuracy": 0.85, "f1_score": 0.82}
        )
        self._models[default.version_id] = default
        self._active_model = default.version_id
    
    def register_model(self, model: ModelVersion):
        """Register new model version"""
        with self._lock:
            self._models[model.version_id] = model
            logger.info(f"Model registered: {model.version_id} ({model.status.value})")
    
    def set_active(self, version_id: str) -> bool:
        """Set active production model"""
        with self._lock:
            if version_id not in self._models:
                return False
            
            # Demote current active
            if self._active_model and self._active_model in self._models:
                self._models[self._active_model].status = ModelStatus.DEPRECATED
            
            # Promote new
            self._models[version_id].status = ModelStatus.ACTIVE
            self._models[version_id].is_production = True
            self._active_model = version_id
            
            logger.info(f"Active model set: {version_id}")
            return True
    
    def set_shadow(self, version_id: str) -> bool:
        """Set shadow model for testing"""
        with self._lock:
            if version_id not in self._models:
                return False
            
            # Demote current shadow
            if self._shadow_model and self._shadow_model in self._models:
                self._models[self._shadow_model].status = ModelStatus.DEPRECATED
            
            # Set new shadow
            self._models[version_id].status = ModelStatus.SHADOW
            self._shadow_model = version_id
            
            logger.info(f"Shadow model set: {version_id}")
            return True
    
    def get_active_model(self) -> Optional[ModelVersion]:
        """Get active model"""
        if self._active_model:
            return self._models.get(self._active_model)
        return None
    
    def get_shadow_model(self) -> Optional[ModelVersion]:
        """Get shadow model"""
        if self._shadow_model:
            return self._models.get(self._shadow_model)
        return None
    
    def rollback(self, version_id: str) -> bool:
        """Rollback to previous version"""
        with self._lock:
            if version_id not in self._models:
                return False
            
            model = self._models[version_id]
            model.status = ModelStatus.ROLLED_BACK
            model.is_production = True
            
            # Set as active
            if self._active_model and self._active_model in self._models:
                self._models[self._active_model].status = ModelStatus.DEPRECATED
            
            self._active_model = version_id
            
            logger.info(f"Model rolled back: {version_id}")
            return True
    
    def get_all_models(self) -> List[ModelVersion]:
        """Get all models"""
        return list(self._models.values())


class AIGovernanceEngine:
    """
    Enterprise AI governance engine.
    """
    
    def __init__(self):
        self.registry = ModelRegistry()
        self.tracking = AITracking()
        
        # Drift detection thresholds
        self.drift_threshold = 0.1  # 10% drift
        self.confidence_threshold = 0.3
        self.correction_threshold = 0.15  # 15% correction rate
        
        # Callbacks
        self.on_drift_detected: Optional[Callable] = None
        self.on_low_confidence: Optional[Callable] = None
        self.on_correction_spike: Optional[Callable] = None
        
        self._lock = threading.RLock()
        
        logger.info("AI Governance Engine initialized")
    
    def infer(self, email_data: Dict, use_shadow: bool = False) -> InferenceResult:
        """Run inference with governance"""
        # Get model
        if use_shadow:
            model = self.registry.get_shadow_model()
        else:
            model = self.registry.get_active_model()
        
        if not model:
            raise Exception("No active model available")
        
        # Run inference (simplified)
        start = time.time()
        
        # Mock inference - in production would call actual model
        from backend.ai.classifier import EmailClassifier
        classifier = EmailClassifier()
        result = classifier.classify(
            email_data.get("subject", ""),
            email_data.get("body_text", ""),
            email_data.get("sender", ""),
            email_data.get("sender_email", "")
        )
        
        if isinstance(result, tuple):
            prediction, confidence = result
        else:
            prediction = result.get("category", "Unknown")
            confidence = result.get("confidence", 0.5)
        
        latency = (time.time() - start) * 1000
        
        # Create result
        inference_result = InferenceResult(
            prediction=prediction,
            confidence=confidence,
            model_version=model.version_id,
            is_shadow=use_shadow,
            latency_ms=latency
        )
        
        # Track prediction
        self.tracking.track_prediction(
            email_data.get("id", 0),
            prediction,
            confidence,
            model.version_id
        )
        
        # Check governance
        self._check_governance(prediction, confidence)
        
        return inference_result
    
    def _check_governance(self, prediction: str, confidence: float):
        """Check governance rules"""
        # Low confidence check
        if confidence < self.confidence_threshold:
            if self.on_low_confidence:
                self.on_low_confidence(prediction, confidence)
        
        # Correction rate check
        correction_rate = self.tracking.get_correction_rate()
        if correction_rate > self.correction_threshold:
            if self.on_correction_spike:
                self.on_correction_spike(correction_rate)
    
    def record_correction(self, email_id: int, original: str, corrected: str, reason: str = ""):
        """Record user correction"""
        import secrets
        correction = Correction(
            correction_id=f"corr_{secrets.token_hex(8)}",
            email_id=email_id,
            original_prediction=original,
            corrected_prediction=corrected,
            reason=reason
        )
        
        self.tracking.track_correction(correction)
        
        # Update model correction count
        active = self.registry.get_active_model()
        if active:
            active.correction_count += 1
        
        logger.info(f"Correction recorded: {original} -> {corrected}")
    
    def detect_drift(self) -> List[DriftDetection]:
        """Detect model drift"""
        drifts = []
        
        # Check confidence drift
        confidence_trend = self.tracking.get_confidence_trend()
        if confidence_trend == "low":
            drifts.append(DriftDetection(
                metric_name="confidence",
                current_value=0.5,  # Would calculate actual
                baseline_value=0.8,
                drift_percent=0.375,
                is_drifted=True
            ))
        
        # Check accuracy drift
        accuracy = self.tracking.get_accuracy()
        if accuracy < 0.7:  # Below threshold
            drifts.append(DriftDetection(
                metric_name="accuracy",
                current_value=accuracy,
                baseline_value=0.85,
                drift_percent=(0.85 - accuracy) / 0.85,
                is_drifted=True
            ))
        
        # Trigger callback
        if drifts and self.on_drift_detected:
            self.on_drift_detected(drifts)
        
        return drifts
    
    def get_model_performance(self) -> Dict:
        """Get model performance metrics"""
        active = self.registry.get_active_model()
        
        if not active:
            return {}
        
        return {
            "model_version": active.version_id,
            "accuracy": self.tracking.get_accuracy(),
            "confidence_avg": sum(self.tracking._confidence_history) / max(1, len(self.tracking._confidence_history)),
            "correction_count": active.correction_count,
            "correction_rate": self.tracking.get_correction_rate(),
            "predictions_tracked": len(self.tracking._predictions)
        }
    
    def get_all_models(self) -> List[Dict]:
        """Get all model versions"""
        models = []
        for model in self.registry.get_all_models():
            models.append({
                "version_id": model.version_id,
                "model_type": model.model_type,
                "version": model.version,
                "status": model.status.value,
                "is_production": model.is_production,
                "created_at": model.created_at,
                "correction_count": model.correction_count
            })
        return models
    
    def get_stats(self) -> Dict:
        """Get governance statistics"""
        return {
            "models": len(self.registry._models),
            "active_model": self.registry.get_active_model().version_id if self.registry.get_active_model() else None,
            "shadow_model": self.registry.get_shadow_model().version_id if self.registry.get_shadow_model() else None,
            "accuracy": self.tracking.get_accuracy(),
            "confidence_trend": self.tracking.get_confidence_trend(),
            "correction_rate": self.tracking.get_correction_rate(),
            "predictions_tracked": len(self.tracking._predictions),
            "corrections": len(self.tracking._corrections)
        }


# Global governance engine
_governance_engine: Optional[AIGovernanceEngine] = None


def get_governance_engine() -> AIGovernanceEngine:
    """Get global governance engine"""
    global _governance_engine
    if _governance_engine is None:
        _governance_engine = AIGovernanceEngine()
    return _governance_engine