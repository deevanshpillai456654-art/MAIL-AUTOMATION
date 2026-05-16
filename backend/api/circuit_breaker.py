"""
Circuit Breaker - Fault Tolerance
================================

Circuit breaker pattern for provider resilience:
- Failure detection
- Automatic recovery
- Half-open state
- State callbacks
"""

import time
import threading
import logging
from typing import Callable, Optional
from enum import Enum

logger = logging.getLogger("circuit.breaker")


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"        # Failing - reject calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """
    Circuit breaker for fault tolerance.
    """
    
    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 3
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0
        self._lock = threading.Lock()
        
        # Callbacks
        self.on_open: Optional[Callable] = None
        self.on_close: Optional[Callable] = None
        self.on_half_open: Optional[Callable] = None
        
        logger.info(f"CircuitBreaker '{name}' initialized")
    
    @property
    def state(self) -> CircuitState:
        """Get current state"""
        with self._lock:
            # Check for auto-recovery
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    logger.info(f"CircuitBreaker '{self.name}' half-open")
                    if self.on_half_open:
                        self.on_half_open()
            return self._state
    
    def call(self, func: Callable, *args, **kwargs):
        """Execute function through circuit breaker"""
        if self.state == CircuitState.OPEN:
            raise CircuitOpenError(f"Circuit '{self.name}' is open")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        """Handle success"""
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._success_count = 0
                    logger.info(f"CircuitBreaker '{self.name}' closed")
                    if self.on_close:
                        self.on_close()
    
    def _on_failure(self):
        """Handle failure"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(f"CircuitBreaker '{self.name}' open after half-open failure")
            elif self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(f"CircuitBreaker '{self.name}' open after {self._failure_count} failures")
                if self.on_open:
                    self.on_open()
    
    def reset(self):
        """Manually reset circuit breaker"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            logger.info(f"CircuitBreaker '{self.name}' manually reset")
    
    def get_stats(self) -> dict:
        """Get circuit breaker stats"""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failure": self._last_failure_time
        }


class CircuitOpenError(Exception):
    """Circuit is open"""
    pass


# Global circuit breakers
_circuits: dict = {}


def get_circuit(name: str) -> CircuitBreaker:
    """Get or create circuit breaker"""
    global _circuits
    if name not in _circuits:
        _circuits[name] = CircuitBreaker(name)
    return _circuits[name]


__all__ = ["CircuitBreaker", "CircuitState", "CircuitOpenError", "get_circuit"]