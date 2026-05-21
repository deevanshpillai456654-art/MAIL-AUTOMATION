"""
Adaptive Learning API Endpoints
=================================

API routes for adaptive AI learning system.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from backend.auth.local_auth import require_local_auth_or_localhost
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from datetime import datetime
import json

from backend.db.database import Database
from backend.ai.adaptive_pipeline import get_adaptive_ai, AdaptiveAI
from backend.ai.learning_engine import LearningSignal
from backend import config

router = APIRouter(prefix="/learning", tags=["Adaptive Learning"], dependencies=[Depends(require_local_auth_or_localhost)])


class FeedbackRequest(BaseModel):
    email_id: int
    action: str
    signal: str = Field(..., description="positive, negative, or neutral")
    category: Optional[str] = None
    priority: Optional[str] = None
    response_time_ms: Optional[int] = None


class ClassificationOverride(BaseModel):
    email_id: int
    category: str


class PreferenceUpdate(BaseModel):
    confidence_threshold_high: Optional[float] = Field(None, ge=0.0, le=1.0)
    confidence_threshold_low: Optional[float] = Field(None, ge=0.0, le=1.0)
    notification_enabled: Optional[bool] = None
    add_vip: Optional[str] = None
    remove_vip: Optional[str] = None
    add_muted: Optional[str] = None
    remove_muted: Optional[str] = None


def get_db() -> Database:
    return Database(config.DB_PATH)


def get_user_id(request: Request) -> int:
    """Get user ID from request - default to 1 for now"""
    return 1


@router.post("/feedback")
async def submit_feedback(request: Request, feedback: FeedbackRequest):
    """Submit user feedback for learning"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    # Validate signal
    try:
        signal = LearningSignal(feedback.signal)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid signal value")
    
    # Process feedback
    adaptive_ai.process_feedback(
        email_id=feedback.email_id,
        action=feedback.action,
        signal=signal,
        category=feedback.category,
        priority=feedback.priority,
        response_time_ms=feedback.response_time_ms
    )
    
    return {"status": "success", "message": "Feedback recorded"}


@router.post("/feedback/classification")
async def submit_classification_override(request: Request, override: ClassificationOverride):
    """Submit manual classification override"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    # Get email to check original classification
    db = get_db()
    email = db.fetch_one("SELECT * FROM emails WHERE id = ?", (override.email_id,))
    
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    
    original_category = email.get("category")
    correct = original_category == override.category
    
    adaptive_ai.record_manual_classification(
        email_id=override.email_id,
        category=override.category,
        correct=correct
    )
    
    # Update email category
    db.execute(
        "UPDATE emails SET category = ?, confidence = 1.0 WHERE id = ?",
        (override.category, override.email_id)
    )
    
    return {"status": "success", "message": f"Classified as {override.category}"}


@router.post("/feedback/email-open/{email_id}")
async def record_email_open(request: Request, email_id: int, response_time_ms: Optional[int] = None):
    """Record email open event"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    adaptive_ai.record_email_open(email_id, response_time_ms)
    
    return {"status": "success"}


@router.post("/feedback/email-reply/{email_id}")
async def record_email_reply(request: Request, email_id: int, response_time_ms: int):
    """Record email reply event"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    adaptive_ai.record_email_reply(email_id, response_time_ms)
    
    return {"status": "success"}


@router.post("/feedback/email-move/{email_id}")
async def record_email_move(request: Request, email_id: int, to_folder: str):
    """Record email move event"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    adaptive_ai.record_email_move(email_id, to_folder)
    
    return {"status": "success"}


@router.post("/feedback/star/{email_id}")
async def record_star(request: Request, email_id: int, starred: bool = True):
    """Record star toggle"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    adaptive_ai.record_star(email_id, starred)
    
    return {"status": "success"}


@router.post("/feedback/notification-dismiss/{email_id}")
async def record_notification_dismiss(request: Request, email_id: int):
    """Record notification dismissal"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    adaptive_ai.record_notification_dismiss(email_id)
    
    return {"status": "success"}


@router.get("/stats")
async def get_learning_stats(request: Request):
    """Get learning statistics"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    stats = adaptive_ai.get_learning_stats()
    
    # Add sender profile stats
    db = get_db()
    
    sender_count = len(adaptive_ai.learning_engine.long_term_memory)
    vip_count = len(adaptive_ai.learning_engine.personalization_engine.preferences.vip_senders)
    muted_count = len(adaptive_ai.learning_engine.personalization_engine.preferences.muted_senders)
    
    stats.update({
        "sender_profiles": sender_count,
        "vip_senders": vip_count,
        "muted_senders": muted_count
    })
    
    return stats


@router.get("/suggestions")
async def get_suggestions(request: Request):
    """Get AI-generated suggestions"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    suggestions = adaptive_ai.get_adaptive_suggestions()
    
    return {"suggestions": suggestions}


@router.get("/explainability/{email_id}")
async def get_explainability(request: Request, email_id: int):
    """Get explainability for email classification"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    explanation = adaptive_ai.get_explainability(email_id)
    
    if not explanation:
        raise HTTPException(status_code=404, detail="Email not found")
    
    return explanation


@router.get("/preferences")
async def get_preferences(request: Request):
    """Get user preferences"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    prefs = adaptive_ai.learning_engine.personalization_engine.preferences
    
    return {
        "confidence_threshold_high": prefs.confidence_threshold_high,
        "confidence_threshold_low": prefs.confidence_threshold_low,
        "notification_enabled": prefs.notification_enabled,
        "vip_senders": list(prefs.vip_senders),
        "muted_senders": list(prefs.muted_senders),
        "smart_views": prefs.smart_views,
        "preferred_categories": prefs.preferred_categories
    }


@router.put("/preferences")
async def update_preferences(request: Request, prefs: PreferenceUpdate):
    """Update user preferences"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    learning_prefs = adaptive_ai.learning_engine.personalization_engine.preferences
    
    # Update preferences
    if prefs.confidence_threshold_high is not None:
        learning_prefs.confidence_threshold_high = prefs.confidence_threshold_high
    
    if prefs.confidence_threshold_low is not None:
        learning_prefs.confidence_threshold_low = prefs.confidence_threshold_low
    
    if prefs.notification_enabled is not None:
        learning_prefs.notification_enabled = prefs.notification_enabled
    
    if prefs.add_vip:
        learning_prefs.vip_senders.add(prefs.add_vip)
    
    if prefs.remove_vip:
        learning_prefs.vip_senders.discard(prefs.remove_vip)
    
    if prefs.add_muted:
        learning_prefs.muted_senders.add(prefs.add_muted)
    
    if prefs.remove_muted:
        learning_prefs.muted_senders.discard(prefs.remove_muted)
    
    # Persist preferences
    db = get_db()
    db.execute("""
        INSERT OR REPLACE INTO user_preferences 
        (user_id, confidence_threshold_high, confidence_threshold_low, 
         notification_enabled, vip_senders, muted_senders, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        learning_prefs.confidence_threshold_high,
        learning_prefs.confidence_threshold_low,
        1 if learning_prefs.notification_enabled else 0,
        json.dumps(list(learning_prefs.vip_senders)),
        json.dumps(list(learning_prefs.muted_senders)),
        datetime.now().isoformat()
    ))
    
    return {"status": "success", "message": "Preferences updated"}


@router.post("/reset")
async def reset_learning(request: Request):
    """Reset all learning for user"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    adaptive_ai.reset_learning()
    
    return {"status": "success", "message": "Learning reset complete"}


@router.get("/sender-profile/{sender_email}")
async def get_sender_profile(request: Request, sender_email: str):
    """Get learned profile for sender"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    profile = adaptive_ai.learning_engine.get_sender_profile(sender_email)
    
    return {
        "email": profile.email,
        "importance_score": profile.importance_score,
        "reply_likelihood": profile.reply_likelihood,
        "avg_response_time_ms": profile.avg_response_time_ms,
        "interaction_count": profile.interaction_count,
        "last_interaction": profile.last_interaction,
        "category_affinity": profile.category_affinity
    }


@router.get("/behavioral-trends")
async def get_behavioral_trends(request: Request):
    """Get behavioral trends over time"""
    user_id = get_user_id(request)
    db = get_db()
    
    # Get recent feedback
    feedback = db.fetch_all("""
        SELECT signal, action, created_at 
        FROM learning_feedback 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT 100
    """, (user_id,))
    
    if not feedback:
        return {"trends": [], "summary": "No learning data yet"}
    
    # Count signals
    positive = sum(1 for f in feedback if f["signal"] == "positive")
    negative = sum(1 for f in feedback if f["signal"] == "negative")
    neutral = sum(1 for f in feedback if f["signal"] == "neutral")
    
    # Count actions
    actions = {}
    for f in feedback:
        action = f.get("action", "unknown")
        actions[action] = actions.get(action, 0) + 1
    
    return {
        "trends": {
            "positive": positive,
            "negative": negative,
            "neutral": neutral
        },
        "actions": actions,
        "total": len(feedback)
    }


@router.post("/search")
async def record_search(request: Request, query: str):
    """Record search for learning"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    adaptive_ai.record_search(query)
    
    return {"status": "success"}


@router.get("/category-evolution")
async def get_category_evolution(request: Request):
    """Get how categories have evolved over time"""
    user_id = get_user_id(request)
    adaptive_ai = get_adaptive_ai(user_id)
    
    # Get category importance from semantic engine
    engine = adaptive_ai.learning_engine.semantic_engine
    category_importance = {}
    
    for user_id_key in engine.category_importance:
        category_importance = engine.category_importance[user_id_key]
    
    # Get priority engine category priorities
    priority_engine = adaptive_ai.learning_engine.priority_engine
    
    return {
        "category_importance": category_importance,
        "category_priority": priority_engine.category_priority
    }