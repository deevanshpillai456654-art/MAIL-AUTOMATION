"""
Provider Recovery System - Automatic Reconnection with Exponential Backoff
===========================================================================

Enterprise recovery:
- Automatic reconnection with exponential backoff
- Token refresh on auth failures
- State restoration after provider restart
- Fallback provider support
- Isolated reconnect storms
"""

import time
import threading
import logging
import random
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Callable, List
from enum import Enum
from collections import deque

logger = logging.getLogger("provider.recovery")

PROVIDERS = ["gmail", "outlook", "yahoo", "zoho", "proton", "imap"]
FALLBACK_PRIORITY = {
    "gmail": ["outlook", "yahoo", "zoho", "proton"],
    "outlook": ["gmail", "yahoo", "zoho", "proton"],
    "yahoo": ["gmail", "outlook", "zoho", "proton"],
    "zoho": ["gmail", "outlook", "yahoo", "proton"],
    "proton": ["gmail", "outlook", "yahoo", "zoho"],
    "imap": ["gmail", "outlook"],
}


class RecoveryState(Enum):
    IDLE = "idle"
    RECONNECTING = "reconnecting"
    REFRESHING_TOKEN = "refreshing_token"
    RESTORING_STATE = "restoring_state"
    FAILED = "failed"
    SUCCESS = "success"


@dataclass
class RecoveryAttempt:
    attempt_id: str
    provider: str
    timestamp: float
    backoff_seconds: float
    success: bool
    error: Optional[str] = None
    method: str = "reconnect"


@dataclass
class ProviderRecoveryConfig:
    base_backoff_seconds: float = 5.0
    max_backoff_seconds: float = 300.0
    max_retries: int = 5
    token_refresh_enabled: bool = True
    state_restoration_enabled: bool = True
    fallback_enabled: bool = True
    storm_protection_threshold: int = 3
    storm_protection_window: float = 60.0


@dataclass
class RecoveryStatus:
    provider: str
    state: RecoveryState = RecoveryState.IDLE
    retry_count: int = 0
    next_retry_at: float = 0
    last_error: Optional[str] = None
    last_success: float = 0
    backoff_seconds: float = 5.0
    current_fallback: Optional[str] = None


class ProviderRecoverySystem:
    """
    Automatic recovery system with exponential backoff.
    Handles reconnection, token refresh, state restoration, and fallbacks.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._recovery_status: Dict[str, RecoveryStatus] = {}
        self._recovery_configs: Dict[str, ProviderRecoveryConfig] = {}
        self._recovery_history: Dict[str, deque] = {}
        self._reconnect_timestamps: Dict[str, deque] = {}
        self._recovery_callbacks: Dict[str, List[Callable]] = {}
        self._pending_recoveries: Dict[str, threading.Event] = {}
        self._recovery_threads: Dict[str, threading.Thread] = {}
        self._global_lock = threading.RLock()

        for provider in PROVIDERS:
            self._recovery_status[provider] = RecoveryStatus(provider=provider)
            self._recovery_configs[provider] = ProviderRecoveryConfig()
            self._recovery_history[provider] = deque(maxlen=50)
            self._reconnect_timestamps[provider] = deque(maxlen=20)

        self._initialized = True
        logger.info("ProviderRecoverySystem initialized for %d providers", len(PROVIDERS))

    def schedule_recovery(
        self, provider: str, error: str,
        reconnect_func: Callable = None,
        token_refresh_func: Callable = None,
        state_restore_func: Callable = None
    ) -> bool:
        """
        Schedule an automatic recovery attempt for a provider.
        """
        with self._global_lock:
            status = self._recovery_status[provider]
            config = self._recovery_configs[provider]

            self._record_reconnect_attempt(provider)

            if self._is_reconnect_storm(provider):
                logger.warning("Reconnect storm blocked for provider %s", provider)
                status.state = RecoveryState.FAILED
                status.last_error = "Reconnect storm protection triggered"
                return False

            if status.retry_count >= config.max_retries:
                logger.error("Max retries exceeded for provider %s", provider)
                status.state = RecoveryState.FAILED
                status.last_error = "Max retries exceeded"
                return False

            status.retry_count += 1
            status.last_error = error
            status.state = RecoveryState.RECONNECTING

            status.backoff_seconds = min(
                config.base_backoff_seconds * (2 ** (status.retry_count - 1)) + random.uniform(0, 2),
                config.max_backoff_seconds
            )
            status.next_retry_at = time.time() + status.backoff_seconds

            thread = threading.Thread(
                target=self._recovery_loop,
                args=(provider, reconnect_func, token_refresh_func, state_restore_func),
                daemon=True,
                name=f"recovery-{provider}"
            )
            self._recovery_threads[provider] = thread
            thread.start()

            logger.info("Recovery scheduled for %s (attempt %d, backoff %.1fs)",
                        provider, status.retry_count, status.backoff_seconds)
            return True

    def _recovery_loop(
        self, provider: str,
        reconnect_func: Callable,
        token_refresh_func: Callable,
        state_restore_func: Callable
    ):
        config = self._recovery_configs[provider]
        status = self._recovery_status[provider]

        time.sleep(status.backoff_seconds)

        if token_refresh_func and config.token_refresh_enabled:
            status.state = RecoveryState.REFRESHING_TOKEN
            if self._try_token_refresh(provider, token_refresh_func):
                self._record_recovery(provider, "token_refresh", True)
                status.state = RecoveryState.SUCCESS
                status.retry_count = 0
                status.last_success = time.time()
                self._notify_callbacks(provider, "recovery_success", {"method": "token_refresh"})
                return

        if reconnect_func:
            status.state = RecoveryState.RECONNECTING
            if self._try_reconnect(provider, reconnect_func):
                if state_restore_func and config.state_restoration_enabled:
                    status.state = RecoveryState.RESTORING_STATE
                    self._try_state_restoration(provider, state_restore_func)

                self._record_recovery(provider, "reconnect", True)
                status.state = RecoveryState.SUCCESS
                status.retry_count = 0
                status.last_success = time.time()
                self._notify_callbacks(provider, "recovery_success", {"method": "reconnect"})
                return
            else:
                self._record_recovery(provider, "reconnect", False, status.last_error)
                status.state = RecoveryState.FAILED

        if config.fallback_enabled:
            fallback = self._get_fallback_provider(provider)
            if fallback:
                status.current_fallback = fallback
                logger.info("Falling back to %s for provider %s", fallback, provider)
                self._notify_callbacks(provider, "fallback_activated", {"fallback": fallback})

    def _try_token_refresh(self, provider: str, token_refresh_func: Callable) -> bool:
        try:
            result = token_refresh_func()
            if result:
                logger.info("Token refresh successful for %s", provider)
                return True
        except Exception as e:
            logger.warning("Token refresh failed for %s: %s", provider, e)
            return False
        return False

    def _try_reconnect(self, provider: str, reconnect_func: Callable) -> bool:
        try:
            reconnect_func()
            logger.info("Reconnect successful for %s", provider)
            return True
        except Exception as e:
            logger.warning("Reconnect failed for %s: %s", provider, e)
            with self._global_lock:
                self._recovery_status[provider].last_error = str(e)
            return False

    def _try_state_restoration(self, provider: str, state_restore_func: Callable) -> bool:
        try:
            state_restore_func()
            logger.info("State restoration successful for %s", provider)
            return True
        except Exception as e:
            logger.warning("State restoration failed for %s: %s", provider, e)
            return False

    def _get_fallback_provider(self, provider: str) -> Optional[str]:
        fallbacks = FALLBACK_PRIORITY.get(provider, [])
        for fallback in fallbacks:
            if self._is_provider_healthy(fallback):
                return fallback
        return None

    def _is_provider_healthy(self, provider: str) -> bool:
        return True

    def _is_reconnect_storm(self, provider: str) -> bool:
        config = self._recovery_configs[provider]
        current_time = time.time()
        timestamps = self._reconnect_timestamps.get(provider, deque())

        recent_count = sum(
            1 for ts in timestamps
            if current_time - ts < config.storm_protection_window
        )

        return recent_count >= config.storm_protection_threshold

    def _record_reconnect_attempt(self, provider: str):
        with self._global_lock:
            if provider in self._reconnect_timestamps:
                self._reconnect_timestamps[provider].append(time.time())

    def _record_recovery(
        self, provider: str, method: str, success: bool, error: str = None
    ):
        with self._global_lock:
            attempt = RecoveryAttempt(
                attempt_id=f"{provider}-{int(time.time())}",
                provider=provider,
                timestamp=time.time(),
                backoff_seconds=self._recovery_status[provider].backoff_seconds,
                success=success,
                error=error,
                method=method,
            )
            self._recovery_history[provider].append(attempt)

    def register_callback(self, provider: str, callback: Callable):
        with self._global_lock:
            if provider not in self._recovery_callbacks:
                self._recovery_callbacks[provider] = []
            self._recovery_callbacks[provider].append(callback)

    def _notify_callbacks(self, provider: str, event: str, data: Dict[str, Any] = None):
        callbacks = self._recovery_callbacks.get(provider, [])
        for callback in callbacks:
            try:
                callback(provider, event, data or {})
            except Exception as e:
                logger.error("Recovery callback error for %s: %s", provider, e)

    def get_recovery_status(self, provider: str) -> RecoveryStatus:
        return self._recovery_status.get(provider, RecoveryStatus(provider=provider))

    def get_all_status(self) -> Dict[str, RecoveryStatus]:
        return dict(self._recovery_status)

    def get_recovery_history(self, provider: str) -> List[RecoveryAttempt]:
        with self._global_lock:
            return list(self._recovery_history.get(provider, []))

    def force_recovery(self, provider: str) -> bool:
        with self._global_lock:
            status = self._recovery_status[provider]
            if status.state == RecoveryState.FAILED:
                status.retry_count = 0
                status.state = RecoveryState.IDLE
                logger.info("Recovery force-reset for %s", provider)
                return True
        return False

    def set_config(self, provider: str, config: ProviderRecoveryConfig):
        with self._global_lock:
            self._recovery_configs[provider] = config
            logger.info("Recovery config updated for %s", provider)

    def get_config(self, provider: str) -> ProviderRecoveryConfig:
        return self._recovery_configs.get(provider, ProviderRecoveryConfig())

    def get_summary(self) -> Dict[str, Any]:
        with self._global_lock:
            states = {}
            for provider, status in self._recovery_status.items():
                states[provider] = status.state.value

            return {
                "total_providers": len(PROVIDERS),
                "failed_providers": sum(
                    1 for s in self._recovery_status.values()
                    if s.state == RecoveryState.FAILED
                ),
                "active_recoveries": sum(
                    1 for s in self._recovery_status.values()
                    if s.state == RecoveryState.RECONNECTING
                ),
                "states": states,
            }


def get_recovery_system() -> ProviderRecoverySystem:
    return ProviderRecoverySystem()
