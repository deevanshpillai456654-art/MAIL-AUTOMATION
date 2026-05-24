"""
WebSocket Storm Protection System
=============================

Enterprise WebSocket storm protection:
- Reconnect governor with exponential backoff
- Client connection throttling
- Message rate limiting per client
- Storm detection and mitigation
- Circuit breaker pattern
- Message batching and coalescing
- Priority-based message queuing
- Adaptive backpressure
- Connection health scoring
"""

import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("ws.storm_protection")


class StormState(Enum):
    NORMAL = "normal"
    ELEVATED = "elevated"
    CRITICAL = "critical"
    PROTECTING = "protecting"


class ConnectionDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    THROTTLE = "throttle"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class ConnectionRequest:
    """Connection request with metadata"""
    request_id: str
    client_id: str
    ip_address: str
    timestamp: float
    user_agent: str = ""
    requested_protocols: List[str] = field(default_factory=list)


@dataclass
class ThrottlePolicy:
    """Throttle policy configuration"""
    max_connections_per_ip: int = 100
    max_connections_per_client: int = 10
    max_messages_per_second: int = 100
    max_messages_per_minute: int = 1000
    connection_burst_window: float = 1.0
    message_burst_window: float = 1.0
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    circuit_failure_threshold: int = 50
    circuit_timeout: float = 60.0


@dataclass
class ClientMetrics:
    """Client metrics for rate limiting"""
    client_id: str
    connection_count: int = 0
    message_count: int = 0
    last_message_time: float = 0
    message_timestamps: List[float] = field(default_factory=list)
    connection_attempts: List[float] = field(default_factory=list)
    denied_count: int = 0
    throttle_count: int = 0
    health_score: float = 1.0


@dataclass
class StormEvent:
    """Storm detection event"""
    event_id: str
    event_type: str
    severity: float
    client_id: str
    ip_address: str
    details: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    resolved: bool = False


class ReconnectGovernor:
    """Control reconnection frequency"""

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0):
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._attempts: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()

    def should_allow(self, client_id: str) -> Tuple[bool, float]:
        """Check if reconnection should be allowed"""
        with self._lock:
            now = time.time()
            window = 60.0

            self._attempts[client_id] = [
                ts for ts in self._attempts[client_id]
                if now - ts < window
            ]

            if len(self._attempts[client_id]) >= 10:
                return False, self._calculate_backoff(client_id)

            self._attempts[client_id].append(now)
            return True, 0.0

    def _calculate_backoff(self, client_id: str) -> float:
        """Calculate exponential backoff delay"""
        attempts = len(self._attempts.get(client_id, []))
        delay = min(
            self._base_delay * (2 ** min(attempts, 6)),
            self._max_delay
        )
        return delay

    def record_success(self, client_id: str):
        """Record successful connection"""
        with self._lock:
            if client_id in self._attempts:
                self._attempts[client_id].clear()

    def get_attempt_count(self, client_id: str) -> int:
        """Get recent attempt count"""
        with self._lock:
            now = time.time()
            return len([
                ts for ts in self._attempts.get(client_id, [])
                if now - ts < 60.0
            ])


class MessageRateLimiter:
    """Rate limit messages per client"""

    def __init__(self,
                 rate: int = 100,
                 burst: int = 50,
                 window: float = 1.0):
        self._rate = rate
        self._burst = burst
        self._window = window
        self._message_counts: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()

    def check_rate(self, client_id: str) -> Tuple[bool, float]:
        """Check if message should be allowed"""
        with self._lock:
            now = time.time()

            self._message_counts[client_id] = [
                ts for ts in self._message_counts[client_id]
                if now - ts < self._window
            ]

            if len(self._message_counts[client_id]) >= self._burst:
                oldest = self._message_counts[client_id][0]
                wait_time = self._window - (now - oldest)
                return False, max(wait_time, 0.0)

            self._message_counts[client_id].append(now)
            return True, 0.0

    def get_current_rate(self, client_id: str) -> float:
        """Get current messages per second"""
        with self._lock:
            now = time.time()
            recent = [
                ts for ts in self._message_counts.get(client_id, [])
                if now - ts < self._window
            ]
            return len(recent) / self._window


class CircuitBreaker:
    """Circuit breaker for connection protection"""

    def __init__(self,
                 failure_threshold: int = 50,
                 timeout: float = 60.0,
                 half_open_max: int = 3):
        self._failure_threshold = failure_threshold
        self._timeout = timeout
        self._half_open_max = half_open_max
        self._state = "closed"
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_requests = 0
        self._lock = threading.RLock()

    def can_connect(self) -> Tuple[bool, str]:
        """Check if connection is allowed"""
        with self._lock:
            if self._state == "closed":
                return True, "closed"

            if self._state == "open":
                if time.time() - self._last_failure_time > self._timeout:
                    self._state = "half_open"
                    self._half_open_requests = 0
                    return True, "half_open"
                return False, "open"

            if self._state == "half_open":
                if self._half_open_requests < self._half_open_max:
                    self._half_open_requests += 1
                    return True, "half_open"
                return False, "half_open_maxed"

            return False, "unknown"

    def record_success(self):
        """Record successful operation"""
        with self._lock:
            if self._state == "half_open":
                self._state = "closed"
                self._failure_count = 0
            self._half_open_requests = 0

    def record_failure(self):
        """Record failed operation"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._failure_count >= self._failure_threshold:
                self._state = "open"
                logger.warning(f"Circuit breaker opened after {self._failure_count} failures")

    def get_state(self) -> str:
        """Get circuit breaker state"""
        with self._lock:
            return self._state

    def reset(self):
        """Reset circuit breaker"""
        with self._lock:
            self._state = "closed"
            self._failure_count = 0
            self._half_open_requests = 0


class StormDetector:
    """Detect WebSocket storms"""

    def __init__(self):
        self._ip_counts: Dict[str, List[float]] = defaultdict(list)
        self._client_spikes: Dict[str, List[float]] = defaultdict(list)
        self._events: List[StormEvent] = []
        self._lock = threading.RLock()
        self._threshold_high = 30
        self._threshold_critical = 50

    def check_connection_rate(self, ip_address: str) -> Tuple[bool, float, str]:
        """Check connection rate from IP"""
        with self._lock:
            now = time.time()
            window = 10.0

            self._ip_counts[ip_address] = [
                ts for ts in self._ip_counts[ip_address]
                if now - ts < window
            ]

            count = len(self._ip_counts[ip_address])

            if count >= self._threshold_critical:
                self._events.append(StormEvent(
                    event_id=str(uuid.uuid4()),
                    event_type="critical_connection_rate",
                    severity=1.0,
                    client_id="",
                    ip_address=ip_address,
                    details={"count": count, "window": window}
                ))
                return False, 0.0, "critical"
            elif count >= self._threshold_high:
                return True, 0.5, "elevated"

            self._ip_counts[ip_address].append(now)
            return True, 0.0, "normal"

    def detect_spike(self, client_id: str, message_count: int) -> bool:
        """Detect message spike"""
        with self._lock:
            now = time.time()
            self._client_spikes[client_id].append(now)

            recent = [
                ts for ts in self._client_spikes[client_id]
                if now - ts < 5.0
            ]

            self._client_spikes[client_id] = recent

            if len(recent) > message_count * 3:
                self._events.append(StormEvent(
                    event_id=str(uuid.uuid4()),
                    event_type="message_spike",
                    severity=0.8,
                    client_id=client_id,
                    ip_address="",
                    details={"count": len(recent), "threshold": message_count * 3}
                ))
                return True

            return False

    def get_recent_events(self) -> List[StormEvent]:
        """Get recent storm events"""
        with self._lock:
            now = time.time()
            return [e for e in self._events if now - e.timestamp < 300]


class MessageBatcher:
    """Batch messages for efficiency"""

    def __init__(self, max_batch_size: int = 10, flush_interval: float = 0.1):
        self._max_batch_size = max_batch_size
        self._flush_interval = flush_interval
        self._pending: Dict[str, List[Any]] = defaultdict(list)
        self._last_flush: Dict[str, float] = {}
        self._lock = threading.RLock()

    def add_message(self, topic: str, message: Any) -> Optional[List[Any]]:
        """Add message to batch, return batch if ready"""
        with self._lock:
            key = topic
            now = time.time()

            self._pending[key].append(message)
            self._last_flush[key] = now

            should_flush = (
                len(self._pending[key]) >= self._max_batch_size or
                (key in self._last_flush and now - self._last_flush[key] > self._flush_interval)
            )

            if should_flush:
                batch = self._pending[key]
                self._pending[key] = []
                return batch

            return None

    def flush_topic(self, topic: str) -> List[Any]:
        """Flush all pending messages for topic"""
        with self._lock:
            key = topic
            batch = self._pending[key]
            self._pending[key] = []
            return batch

    def get_pending_count(self, topic: str) -> int:
        """Get pending message count"""
        with self._lock:
            return len(self._pending.get(topic, []))


class PriorityMessageQueue:
    """Priority-based message queue"""

    HIGH_PRIORITY_TOPICS = {"email:new", "email:urgent", "alert", "notification:high"}
    LOW_PRIORITY_TOPICS = {"sync:status", "heartbeat", "ping"}

    def __init__(self, max_size: int = 10000):
        self._max_size = max_size
        self._high_priority: deque = deque(maxlen=max_size)
        self._normal_priority: deque = deque(maxlen=max_size)
        self._low_priority: deque = deque(maxlen=max_size)
        self._lock = threading.RLock()

    def enqueue(self, topic: str, message: Any, priority: int = 2):
        """Enqueue message with priority"""
        with self._lock:
            queue = self._get_queue(priority)

            if len(queue) >= self._max_size:
                queue.popleft()

            queue.append({
                "topic": topic,
                "message": message,
                "timestamp": time.time()
            })

    def dequeue(self) -> Optional[Dict[str, Any]]:
        """Dequeue highest priority message"""
        with self._lock:
            if self._high_priority:
                return self._high_priority.popleft()
            elif self._normal_priority:
                return self._normal_priority.popleft()
            elif self._low_priority:
                return self._low_priority.popleft()
            return None

    def _get_queue(self, priority: int):
        """Get queue for priority level"""
        if priority <= 1:
            return self._high_priority
        elif priority >= 3:
            return self._low_priority
        return self._normal_priority

    def size(self) -> int:
        """Get total queue size"""
        with self._lock:
            return len(self._high_priority) + len(self._normal_priority) + len(self._low_priority)


class AdaptiveBackpressure:
    """Adaptive backpressure management"""

    def __init__(self,
                 normal_threshold: float = 0.7,
                 warning_threshold: float = 0.85,
                 critical_threshold: float = 0.95):
        self._normal = normal_threshold
        self._warning = warning_threshold
        self._critical = critical_threshold
        self._current_state = StormState.NORMAL
        self._lock = threading.RLock()

    def calculate_delay(self, queue_utilization: float) -> float:
        """Calculate adaptive delay based on queue usage"""
        with self._lock:
            if queue_utilization >= self._critical:
                self._current_state = StormState.CRITICAL
                return 0.5
            elif queue_utilization >= self._warning:
                self._current_state = StormState.ELEVATED
                return 0.2
            elif queue_utilization >= self._normal:
                self._current_state = StormState.NORMAL
                return 0.05

            self._current_state = StormState.NORMAL
            return 0.0

    def get_state(self) -> StormState:
        """Get current backpressure state"""
        with self._lock:
            return self._current_state

    def should_drop(self, topic: str, queue_utilization: float) -> bool:
        """Determine if low priority message should be dropped"""
        with self._lock:
            if queue_utilization >= self._critical:
                return topic in PriorityMessageQueue.LOW_PRIORITY_TOPICS
            return False


class ConnectionHealthScorer:
    """Score connection health"""

    def __init__(self):
        self._client_metrics: Dict[str, ClientMetrics] = {}
        self._lock = threading.RLock()

    def record_message(self, client_id: str):
        """Record message for health scoring"""
        with self._lock:
            if client_id not in self._client_metrics:
                self._client_metrics[client_id] = ClientMetrics(client_id=client_id)

            m = self._client_metrics[client_id]
            m.message_count += 1
            m.message_timestamps.append(time.time())

            if len(m.message_timestamps) > 100:
                m.message_timestamps = m.message_timestamps[-100:]

    def record_denial(self, client_id: str):
        """Record denial for health scoring"""
        with self._lock:
            if client_id not in self._client_metrics:
                self._client_metrics[client_id] = ClientMetrics(client_id=client_id)

            self._client_metrics[client_id].denied_count += 1

    def calculate_health(self, client_id: str) -> float:
        """Calculate health score (0-1)"""
        with self._lock:
            if client_id not in self._client_metrics:
                return 1.0

            m = self._client_metrics[client_id]

            now = time.time()
            recent_messages = [
                ts for ts in m.message_timestamps
                if now - ts < 60.0
            ]

            message_score = 1.0 - (len(recent_messages) / 1000)
            denial_score = 1.0 - (m.denied_count / 100)

            health = (message_score * 0.5) + (denial_score * 0.5)
            return max(0.0, min(1.0, health))

    def get_metrics(self, client_id: str) -> Optional[ClientMetrics]:
        """Get client metrics"""
        with self._lock:
            return self._client_metrics.get(client_id)


class WebSocketStormProtector:
    """Main storm protection orchestrator"""

    def __init__(self, policy: Optional[ThrottlePolicy] = None):
        self._policy = policy or ThrottlePolicy()
        self._reconnect_governor = ReconnectGovernor(
            base_delay=self._policy.backoff_base,
            max_delay=self._policy.backoff_max
        )
        self._rate_limiter = MessageRateLimiter(
            rate=self._policy.max_messages_per_second,
            burst=self._policy.message_burst_window
        )
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=self._policy.circuit_failure_threshold,
            timeout=self._policy.circuit_timeout
        )
        self._storm_detector = StormDetector()
        self._message_batcher = MessageBatcher()
        self._message_queue = PriorityMessageQueue()
        self._backpressure = AdaptiveBackpressure()
        self._health_scorer = ConnectionHealthScorer()
        self._active_connections: Set[str] = set()
        self._connection_ips: Dict[str, str] = {}
        self._lock = threading.RLock()

        self._config = {
            "enable_rate_limiting": True,
            "enable_circuit_breaker": True,
            "enable_storm_detection": True,
            "enable_message_batching": True,
            "enable_priority_queue": True
        }

    async def check_connection(self,
                        client_id: str,
                        ip_address: str) -> Tuple[ConnectionDecision, str]:
        """Check if connection should be allowed"""
        with self._lock:
            can_connect, state = self._circuit_breaker.can_connect()
            if not can_connect:
                self._health_scorer.record_denial(client_id)
                return ConnectionDecision.DENY, f"Circuit breaker {state}"

            allowed, backoff = self._reconnect_governor.should_allow(client_id)
            if not allowed:
                self._health_scorer.record_denial(client_id)
                return ConnectionDecision.THROTTLE, f"Reconnect backoff {backoff:.1f}s"

            is_allowed, severity, state = self._storm_detector.check_connection_rate(ip_address)
            if not is_allowed:
                self._health_scorer.record_denial(client_id)
                return ConnectionDecision.DENY, f"Critical connection rate from {ip_address}"

            if client_id in self._active_connections:
                if self._policy.max_connections_per_client <= len([
                    c for c in self._active_connections if c == client_id
                ]):
                    self._health_scorer.record_denial(client_id)
                    return ConnectionDecision.THROTTLE, "Max connections per client"

            self._active_connections.add(client_id)
            self._connection_ips[client_id] = ip_address
            return ConnectionDecision.ALLOW, "Allowed"

    async def check_message(self,
                        client_id: str,
                        topic: str,
                        message: Any) -> Tuple[bool, Optional[float]]:
        """Check if message should be allowed"""
        if self._config["enable_rate_limiting"]:
            allowed, wait = self._rate_limiter.check_rate(client_id)
            if not allowed:
                self._health_scorer.record_denial(client_id)
                return False, wait

        self._health_scorer.record_message(client_id)

        if self._config["enable_message_batching"]:
            batch = self._message_batcher.add_message(topic, message)
            if batch:
                return True, None

        if self._config["enable_priority_queue"]:
            self._message_queue.enqueue(topic, message)

        return True, None

    def record_failure(self):
        """Record connection failure"""
        self._circuit_breaker.record_failure()

    def record_success(self):
        """Record successful operation"""
        self._circuit_breaker.record_success()
        self._reconnect_governor.record_success("")

    def remove_connection(self, client_id: str):
        """Remove active connection"""
        with self._lock:
            self._active_connections.discard(client_id)
            self._connection_ips.pop(client_id, None)

    def get_stats(self) -> Dict[str, Any]:
        """Get protection statistics"""
        return {
            "active_connections": len(self._active_connections),
            "circuit_state": self._circuit_breaker.get_state(),
            "queue_size": self._message_queue.size(),
            "storm_events": len(self._storm_detector.get_recent_events()),
            "batcher_pending": self._message_batcher.get_pending_count("default"),
            "backpressure_state": self._backpressure.get_state().value
        }

    def update_config(self, config: Dict[str, Any]):
        """Update configuration"""
        self._config.update(config)


_global_protector: Optional["WebSocketStormProtector"] = None


def get_storm_protector() -> WebSocketStormProtector:
    """Get global storm protector"""
    global _global_protector
    if _global_protector is None:
        _global_protector = WebSocketStormProtector()
    return _global_protector


__all__ = [
    "StormState",
    "ConnectionDecision",
    "ThrottlePolicy",
    "ClientMetrics",
    "StormEvent",
    "ReconnectGovernor",
    "MessageRateLimiter",
    "CircuitBreaker",
    "StormDetector",
    "MessageBatcher",
    "PriorityMessageQueue",
    "AdaptiveBackpressure",
    "ConnectionHealthScorer",
    "WebSocketStormProtector",
    "get_storm_protector"
]
