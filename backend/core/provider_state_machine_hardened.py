"""
Provider State Machine - Enterprise Hardened

Additional states:
- COOLDOWN (temporary backoff)
- DEGRADED (limited functionality)
- BACKPRESSURE (throttled)
- RECOVERING (auto-healing)

With validation engine to prevent invalid transitions.
"""

import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from enum import Enum

logger = logging.getLogger("statemachine.provider")


class ProviderState(Enum):
    # Normal states
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AUTHENTICATING = "authenticating"
    CONNECTED = "connected"
    SYNCING = "syncing"
    IDLE = "idle"
    PAUSED = "paused"
    
    # Error states
    RATE_LIMITED = "rate_limited"
    EXPIRED = "expired"
    FAILED = "failed"
    RECONNECTING = "reconnecting"
    
    # Additional states
    COOLDOWN = "cooldown"          # Temporary backoff
    DEGRADED = "degraded"          # Limited functionality
    BACKPRESSURE = "backpressure"  # Throttled
    RECOVERING = "recovering"      # Auto-healing
    REFRESHING = "refreshing"     # Token refresh


@dataclass
class StateTransition:
    """A state transition with validation"""
    from_state: ProviderState
    to_state: ProviderState
    trigger: str
    handler: Optional[Callable] = None
    timeout: Optional[float] = None


@dataclass
class ProviderStateData:
    """Full state data for a provider"""
    provider: str
    account_id: int
    state: ProviderState = ProviderState.DISCONNECTED
    
    # Timing
    state_entered_at: float = field(default_factory=time.time)
    last_transition_at: float = field(default_factory=time.time)
    last_success_at: Optional[float] = None
    
    # Failure tracking
    failure_count: int = 0
    cooldown_until: Optional[float] = None
    
    # Token info
    token_expires_at: Optional[float] = None
    needs_reauth: bool = False
    
    # Queue info
    queue_size: int = 0
    backpressure_active: bool = False
    
    # Health
    health_score: float = 1.0
    degraded_reason: Optional[str] = None


class StateMachineValidator:
    """
    Validates state transitions to prevent invalid states.
    """
    
    # Valid transitions map
    VALID_TRANSITIONS = {
        # Normal flow
        ProviderState.DISCONNECTED: [
            ProviderState.CONNECTING
        ],
        ProviderState.CONNECTING: [
            ProviderState.AUTHENTICATING,
            ProviderState.FAILED,
            ProviderState.COOLDOWN
        ],
        ProviderState.AUTHENTICATING: [
            ProviderState.CONNECTED,
            ProviderState.FAILED,
            ProviderState.COOLDOWN
        ],
        ProviderState.CONNECTED: [
            ProviderState.SYNCING,
            ProviderState.IDLE,
            ProviderState.EXPIRED,
            ProviderState.FAILED,
            ProviderState.DEGRADED
        ],
        ProviderState.SYNCING: [
            ProviderState.IDLE,
            ProviderState.RATE_LIMITED,
            ProviderState.FAILED
        ],
        ProviderState.IDLE: [
            ProviderState.SYNCING,
            ProviderState.PAUSED,
            ProviderState.EXPIRED,
            ProviderState.RATE_LIMITED,
            ProviderState.BACKPRESSURE,
            ProviderState.DEGRADED,
            ProviderState.DISCONNECTED
        ],
        ProviderState.PAUSED: [
            ProviderState.RECONNECTING,
            ProviderState.IDLE,
            ProviderState.DISCONNECTED
        ],
        
        # Error recovery
        ProviderState.RATE_LIMITED: [
            ProviderState.COOLDOWN,
            ProviderState.CONNECTED,
            ProviderState.RECONNECTING
        ],
        ProviderState.EXPIRED: [
            ProviderState.REFRESHING,
            ProviderState.RECONNECTING
        ],
        ProviderState.REFRESHING: [
            ProviderState.CONNECTED,
            ProviderState.RECONNECTING,
            ProviderState.FAILED
        ],
        ProviderState.FAILED: [
            ProviderState.RECONNECTING,
            ProviderState.DISCONNECTED
        ],
        ProviderState.RECONNECTING: [
            ProviderState.CONNECTING,
            ProviderState.AUTHENTICATING,
            ProviderState.COOLDOWN,
            ProviderState.FAILED
        ],
        
        # Additional states
        ProviderState.COOLDOWN: [
            ProviderState.CONNECTING,
            ProviderState.RECONNECTING,
            ProviderState.FAILED
        ],
        ProviderState.DEGRADED: [
            ProviderState.CONNECTED,
            ProviderState.RECONNECTING,
            ProviderState.FAILED
        ],
        ProviderState.BACKPRESSURE: [
            ProviderState.IDLE,
            ProviderState.COOLDOWN
        ],
        ProviderState.RECOVERING: [
            ProviderState.CONNECTED,
            ProviderState.IDLE,
            ProviderState.FAILED
        ]
    }
    
    @classmethod
    def can_transition(cls, from_state: ProviderState, to_state: ProviderState) -> bool:
        """Check if transition is valid"""
        if from_state not in cls.VALID_TRANSITIONS:
            return False
        
        return to_state in cls.VALID_TRANSITIONS[from_state]
    
    @classmethod
    def get_allowed_transitions(cls, from_state: ProviderState) -> List[ProviderState]:
        """Get list of allowed transitions"""
        return cls.VALID_TRANSITIONS.get(from_state, [])


class ProviderStateMachine:
    """
    Enterprise provider state machine with validation and auto-recovery.
    """
    
    def __init__(self, provider: str, account_id: int):
        self.provider = provider
        self.account_id = account_id
        
        self._state_data = ProviderStateData(
            provider=provider,
            account_id=account_id
        )
        
        self._lock = threading.RLock()
        
        # Transition handlers
        self._on_state_change: Optional[Callable] = None
        self._on_connect: Optional[Callable] = None
        self._on_disconnect: Optional[Callable] = None
        self._on_error: Optional[Callable] = None
        self._on_recovery: Optional[Callable] = None
        
        # Configuration
        self.cooldown_duration = 30.0  # seconds
        self.max_failures = 5
        self.backpressure_threshold = 100
        
        logger.info(f"State machine created for {provider}:{account_id}")
    
    def transition_to(self, new_state: ProviderState, reason: str = "") -> bool:
        """
        Attempt to transition to a new state.
        
        Returns:
            True if transition successful
        """
        with self._lock:
            current_state = self._state_data.state
            
            # Validate transition
            if not StateMachineValidator.can_transition(current_state, new_state):
                logger.warning(
                    f"Invalid transition: {current_state.value} -> {new_state.value} "
                    f"(triggered by: {reason})"
                )
                return False
            
            # Execute transition
            logger.info(
                f"State transition: {current_state.value} -> {new_state.value} "
                f"(reason: {reason})"
            )
            
            old_state = current_state
            self._state_data.state = new_state
            self._state_data.last_transition_at = time.time()
            self._state_data.state_entered_at = time.time()
            
            # Update failure count
            if new_state in [ProviderState.FAILED, ProviderState.COOLDOWN]:
                self._state_data.failure_count += 1
            elif new_state == ProviderState.CONNECTED:
                self._state_data.failure_count = 0
                self._state_data.last_success_at = time.time()
            
            # Handle special states
            if new_state == ProviderState.COOLDOWN:
                self._state_data.cooldown_until = time.time() + self.cooldown_duration
            
            # Fire callbacks
            if self._on_state_change:
                self._on_state_change(old_state, new_state, reason)
            
            if new_state == ProviderState.CONNECTED and self._on_connect:
                self._on_connect()
            
            if new_state == ProviderState.DISCONNECTED and self._on_disconnect:
                self._on_disconnect()
            
            if new_state in [ProviderState.FAILED, ProviderState.DEGRADED]:
                if self._on_error:
                    self._on_error(new_state, reason)
            
            return True
    
    def set_backpressure(self, active: bool):
        """Set backpressure state"""
        with self._lock:
            if active and self._state_data.state not in [ProviderState.BACKPRESSURE, ProviderState.COOLDOWN]:
                self.transition_to(ProviderState.BACKPRESSURE, "queue overflow")
            elif not active and self._state_data.state == ProviderState.BACKPRESSURE:
                self.transition_to(ProviderState.IDLE, "pressure relieved")
            
            self._state_data.backpressure_active = active
    
    def set_queue_size(self, size: int):
        """Update queue size and potentially trigger backpressure"""
        with self._lock:
            self._state_data.queue_size = size
            
            if size >= self.backpressure_threshold:
                self.set_backpressure(True)
            elif self._state_data.state == ProviderState.BACKPRESSURE:
                self.set_backpressure(False)
    
    def mark_degraded(self, reason: str):
        """Mark provider as degraded"""
        self.transition_to(ProviderState.DEGRADED, reason)
        self._state_data.degraded_reason = reason
    
    def recover_from_degraded(self):
        """Attempt to recover from degraded state"""
        if self._state_data.state == ProviderState.DEGRADED:
            self.transition_to(ProviderState.RECOVERING, "recovery started")
            # In real implementation, would attempt actual recovery
            time.sleep(1)  # Simulated recovery
            self.transition_to(ProviderState.CONNECTED, "recovery complete")
    
    def check_token_expiry(self) -> bool:
        """Check if token is expiring soon"""
        if not self._state_data.token_expires_at:
            return False
        
        # Refresh if expiring within 5 minutes
        return time.time() > (self._state_data.token_expires_at - 300)
    
    def can_connect(self) -> bool:
        """Check if can attempt connection"""
        # Check cooldown
        if self._state_data.cooldown_until:
            if time.time() < self._state_data.cooldown_until:
                return False
        
        # Check failure count
        if self._state_data.failure_count >= self.max_failures:
            return False
        
        return True
    
    def get_status(self) -> Dict:
        """Get current status"""
        return {
            "provider": self.provider,
            "account_id": self.account_id,
            "state": self._state_data.state.value,
            "state_entered_at": self._state_data.state_entered_at,
            "failure_count": self._state_data.failure_count,
            "health_score": self._state_data.health_score,
            "queue_size": self._state_data.queue_size,
            "backpressure_active": self._state_data.backpressure_active,
            "degraded_reason": self._state_data.degraded_reason,
            "can_connect": self.can_connect()
        }
    
    def set_on_state_change(self, callback: Callable):
        """Set state change callback"""
        self._on_state_change = callback
    
    def set_on_connect(self, callback: Callable):
        """Set connect callback"""
        self._on_connect = callback
    
    def set_on_disconnect(self, callback: Callable):
        """Set disconnect callback"""
        self._on_disconnect = callback
    
    def set_on_error(self, callback: Callable):
        """Set error callback"""
        self._on_error = callback


# Global state machines
_state_machines: Dict[str, ProviderStateMachine] = {}


def get_state_machine(provider: str, account_id: int) -> ProviderStateMachine:
    """Get or create state machine for a provider"""
    key = f"{provider}:{account_id}"
    
    if key not in _state_machines:
        _state_machines[key] = ProviderStateMachine(provider, account_id)
    
    return _state_machines[key]