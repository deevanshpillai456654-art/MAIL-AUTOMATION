"""
WebSocket Backpressure Handler
===============================

Features:
- Client send rate limiting
- Server push rate limiting per client
- Queue depth monitoring
- Backpressure signaling to client
- Client-side backpressure handling
- Buffer overflow protection
- Adaptive UI sync (priority-based, batching, debouncing)
- Offline replay with conflict detection

"""

import asyncio
import logging
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional, Set

logger = logging.getLogger("realtime.backpressure")


class BackpressureState(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    BLOCKED = "blocked"


class Priority(Enum):
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BATCH = 4


@dataclass
class QueueItem:
    """Queue item with priority"""
    item_id: str
    topic: str
    data: Any
    priority: Priority
    timestamp: float
    sequence: int = 0
    retries: int = 0
    metadata: Dict = field(default_factory=dict)


@dataclass
class ClientBackpressure:
    """Client backpressure state"""
    client_id: str
    send_queue_size: int
    receive_queue_size: int
    send_rate: float
    receive_rate: float
    state: BackpressureState
    last_update: float
    blocked_topics: Set[str] = field(default_factory=set)


@dataclass
class RateLimit:
    """Rate limit configuration"""
    max_requests_per_second: float = 100
    max_queue_size: int = 1000
    burst_allowance: int = 50
    backpressure_threshold: float = 0.8


@dataclass
class OfflineMutation:
    """Offline mutation queued for replay"""
    mutation_id: str
    topic: str
    action: str
    payload: Dict
    timestamp: float
    local_id: str
    version: int = 1


@dataclass
class ConflictInfo:
    """Conflict information for merge"""
    local_mutation: OfflineMutation
    remote_version: Dict
    conflict_type: str
    detected_at: float


class SendRateLimiter:
    """Rate limiter for client sends"""

    def __init__(self, rate_limit: RateLimit):
        self.rate_limit = rate_limit
        self._tokens = rate_limit.burst_allowance
        self._last_refill = time.time()
        self._lock = threading.Lock()

    def _refill_tokens(self):
        """Refill tokens based on time"""
        now = time.time()
        elapsed = now - self._last_refill

        tokens_to_add = elapsed * self.rate_limit.max_requests_per_second
        self._tokens = min(
            self.rate_limit.burst_allowance,
            self._tokens + tokens_to_add
        )
        self._last_refill = now

    def try_acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens"""
        with self._lock:
            self._refill_tokens()

            if self._tokens >= tokens:
                self._tokens -= tokens
                return True

            return False

    def get_wait_time(self) -> float:
        """Get wait time for tokens"""
        with self._lock:
            self._refill_tokens()

            if self._tokens >= 1:
                return 0

            tokens_needed = 1 - self._tokens
            return tokens_needed / self.rate_limit.max_requests_per_second


class PriorityQueueManager:
    """Manage priority queues for different priorities"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._queues: Dict[Priority, Deque[QueueItem]] = {
            Priority.HIGH: deque(maxlen=max_size),
            Priority.NORMAL: deque(maxlen=max_size),
            Priority.LOW: deque(maxlen=max_size),
            Priority.BATCH: deque(maxlen=max_size)
        }
        self._lock = threading.RLock()

    def enqueue(self, item: QueueItem) -> bool:
        """Enqueue item with priority"""
        with self._lock:
            queue = self._queues[item.priority]

            if len(queue) >= self.max_size:
                return False

            queue.append(item)
            return True

    def dequeue(self) -> Optional[QueueItem]:
        """Dequeue highest priority item"""
        with self._lock:
            for priority in [Priority.HIGH, Priority.NORMAL, Priority.LOW, Priority.BATCH]:
                queue = self._queues[priority]
                if queue:
                    return queue.popleft()

            return None

    def dequeue_batch(self, max_count: int = 50) -> List[QueueItem]:
        """Dequeue batch of items"""
        items = []

        with self._lock:
            for priority in [Priority.HIGH, Priority.NORMAL, Priority.LOW, Priority.BATCH]:
                queue = self._queues[priority]

                while queue and len(items) < max_count:
                    items.append(queue.popleft())

                if len(items) >= max_count:
                    break

        return items

    def get_size(self) -> int:
        """Get total queue size"""
        with self._lock:
            return sum(len(q) for q in self._queues.values())

    def clear(self):
        """Clear all queues"""
        with self._lock:
            for queue in self._queues.values():
                queue.clear()


class BackpressureMonitor:
    """Monitor and manage backpressure state"""

    def __init__(self, rate_limit: RateLimit):
        self.rate_limit = rate_limit
        self._client_states: Dict[str, ClientBackpressure] = {}
        self._lock = threading.RLock()
        self._history: deque = deque(maxlen=1000)

    def update_client(self, client_id: str, send_queue: int, receive_queue: int,
                     send_rate: float, receive_rate: float):
        """Update client backpressure state"""
        with self._lock:
            current = self._client_states.get(client_id)

            if current:
                old_state = current.state
            else:
                old_state = BackpressureState.NORMAL

            threshold = self.rate_limit.backpressure_threshold
            max_queue = self.rate_limit.max_queue_size

            if send_queue > max_queue or receive_queue > max_queue:
                state = BackpressureState.BLOCKED
            elif send_queue > max_queue * threshold or receive_queue > max_queue * threshold:
                state = BackpressureState.CRITICAL
            elif send_queue > max_queue * threshold * 0.7 or receive_queue > max_queue * threshold * 0.7:
                state = BackpressureState.WARNING
            else:
                state = BackpressureState.NORMAL

            self._client_states[client_id] = ClientBackpressure(
                client_id=client_id,
                send_queue_size=send_queue,
                receive_queue_size=receive_queue,
                send_rate=send_rate,
                receive_rate=receive_rate,
                state=state,
                last_update=time.time(),
                blocked_topics=current.blocked_topics if current else set()
            )

            self._history.append({
                "client_id": client_id,
                "state": state,
                "timestamp": time.time()
            })

            return state != old_state

    def get_client_state(self, client_id: str) -> Optional[ClientBackpressure]:
        """Get client backpressure state"""
        with self._lock:
            return self._client_states.get(client_id)

    def get_all_states(self) -> Dict[str, BackpressureState]:
        """Get all client states"""
        with self._lock:
            return {
                client_id: state.state
                for client_id, state in self._client_states.items()
            }

    def get_clients_by_state(self, state: BackpressureState) -> List[str]:
        """Get clients in specific state"""
        with self._lock:
            return [
                client_id for client_id, s in self._client_states.items()
                if s.state == state
            ]

    def block_topic(self, client_id: str, topic: str):
        """Block topic for client"""
        with self._lock:
            if client_id in self._client_states:
                self._client_states[client_id].blocked_topics.add(topic)

    def unblock_topic(self, client_id: str, topic: str):
        """Unblock topic for client"""
        with self._lock:
            if client_id in self._client_states:
                self._client_states[client_id].blocked_topics.discard(topic)


class Debouncer:
    """Debounce rapid changes"""

    def __init__(self, delay: float = 0.1):
        self.delay = delay
        self._pending: Dict[str, Any] = {}
        self._timers: Dict[str, asyncio.Task] = {}
        self._lock = threading.Lock()

    async def debounce(self, key: str, callback: Callable, *args, **kwargs):
        """Debounce a call"""
        async with self._lock:
            if key in self._timers:
                self._timers[key].cancel()

            async def delayed_call():
                await asyncio.sleep(self.delay)
                async with self._lock:
                    if key in self._timers:
                        del self._timers[key]
                await callback(*args, **kwargs)

            self._timers[key] = asyncio.create_task(delayed_call())

    def cancel(self, key: str):
        """Cancel pending debounce"""
        with self._lock:
            if key in self._timers:
                self._timers[key].cancel()
                del self._timers[key]


class Batcher:
    """Batch multiple updates"""

    def __init__(self, batch_size: int = 10, max_delay: float = 0.2):
        self.batch_size = batch_size
        self.max_delay = max_delay
        self._pending: Dict[str, List[Any]] = {}
        self._timers: Dict[str, asyncio.Task] = {}
        self._lock = threading.Lock()

    async def add(self, key: str, item: Any, callback: Callable):
        """Add item to batch"""
        async with self._lock:
            if key not in self._pending:
                self._pending[key] = []

            self._pending[key].append(item)

            if len(self._pending[key]) >= self.batch_size:
                items = self._pending.pop(key, [])
                if key in self._timers:
                    self._timers[key].cancel()
                    del self._timers[key]
                await callback(items)
            else:
                if key not in self._timers:
                    async def delayed_flush():
                        await asyncio.sleep(self.max_delay)
                        async with self._lock:
                            items = self._pending.pop(key, [])
                        if items and key in self._timers:
                            del self._timers[key]
                        if items:
                            await callback(items)

                    self._timers[key] = asyncio.create_task(delayed_flush())


class OfflineMutationQueue:
    """Queue mutations for offline replay"""

    def __init__(self, max_size: int = 500):
        self.max_size = max_size
        self._queue: deque = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def add(self, topic: str, action: str, payload: Dict, local_id: str) -> str:
        """Add mutation to queue"""
        mutation = OfflineMutation(
            mutation_id=f"mut_{secrets.token_hex(8)}",
            topic=topic,
            action=action,
            payload=payload,
            timestamp=time.time(),
            local_id=local_id
        )

        with self._lock:
            self._queue.append(mutation)

        return mutation.mutation_id

    def get_all(self) -> List[OfflineMutation]:
        """Get all pending mutations"""
        with self._lock:
            return list(self._queue)

    def get_since(self, timestamp: float) -> List[OfflineMutation]:
        """Get mutations since timestamp"""
        with self._lock:
            return [m for m in self._queue if m.timestamp > timestamp]

    def remove(self, mutation_id: str) -> bool:
        """Remove mutation from queue"""
        with self._lock:
            for i, m in enumerate(self._queue):
                if m.mutation_id == mutation_id:
                    del self._queue[i]
                    return True
            return False

    def clear(self):
        """Clear queue"""
        with self._lock:
            self._queue.clear()


class ConflictResolver:
    """Resolve conflicts between offline and online data"""

    def __init__(self):
        self._strategy = "last_write_wins"

    def set_strategy(self, strategy: str):
        """Set merge strategy"""
        self._strategy = strategy

    def detect_conflict(self, local: OfflineMutation, remote: Dict) -> Optional[ConflictInfo]:
        """Detect conflict between local and remote"""
        remote_version = remote.get("version", 0)

        if local.version > remote_version:
            return ConflictInfo(
                local_mutation=local,
                remote_version=remote,
                conflict_type="version_mismatch",
                detected_at=time.time()
            )

        if local.topic in remote:
            remote_data = remote[local.topic]
            local_payload = local.payload

            for key in local_payload:
                if key in remote_data and remote_data[key] != local_payload[key]:
                    return ConflictInfo(
                        local_mutation=local,
                        remote_version=remote_data,
                        conflict_type="value_changed",
                        detected_at=time.time()
                    )

        return None

    def resolve(self, conflict: ConflictInfo, strategy: str = None) -> Dict:
        """Resolve conflict based on strategy"""
        strategy = strategy or self._strategy

        if strategy == "last_write_wins":
            return {
                "action": "apply_local",
                "payload": conflict.local_mutation.payload
            }
        elif strategy == "remote_wins":
            return {
                "action": "discard_local",
                "payload": conflict.remote_version
            }
        elif strategy == "merge":
            return {
                "action": "merge",
                "payload": {**conflict.remote_version, **conflict.local_mutation.payload}
            }
        else:
            return {
                "action": "prompt_user",
                "local": conflict.local_mutation.payload,
                "remote": conflict.remote_version
            }


class WebSocketBackpressureHandler:
    """
    Main backpressure handler with rate limiting, queuing, and offline support.
    """

    def __init__(self, rate_limit: RateLimit = None):
        self.rate_limit = rate_limit or RateLimit()

        self._rate_limiters: Dict[str, SendRateLimiter] = {}
        self._queue_managers: Dict[str, PriorityQueueManager] = {}
        self._monitor = BackpressureMonitor(self.rate_limit)

        self._debouncer = Debouncer(0.1)
        self._batcher = Batcher(10, 0.2)

        self._offline_queue = OfflineMutationQueue()
        self._conflict_resolver = ConflictResolver()

        self._is_online = True
        self._last_sync = time.time()

        self.on_backpressure_change: Optional[Callable] = None
        self.on_queue_full: Optional[Callable] = None

        logger.info("WebSocketBackpressureHandler initialized")

    def _get_rate_limiter(self, client_id: str) -> SendRateLimiter:
        """Get or create rate limiter for client"""
        if client_id not in self._rate_limiters:
            self._rate_limiters[client_id] = SendRateLimiter(self.rate_limit)
        return self._rate_limiters[client_id]

    def _get_queue_manager(self, client_id: str) -> PriorityQueueManager:
        """Get or create queue manager for client"""
        if client_id not in self._queue_managers:
            self._queue_managers[client_id] = PriorityQueueManager(self.rate_limit.max_queue_size)
        return self._queue_managers[client_id]

    def can_send(self, client_id: str) -> bool:
        """Check if client can send"""
        limiter = self._get_rate_limiter(client_id)
        return limiter.try_acquire()

    def wait_time(self, client_id: str) -> float:
        """Get wait time for client"""
        limiter = self._get_rate_limiter(client_id)
        return limiter.get_wait_time()

    def enqueue(self, client_id: str, topic: str, data: Any,
                priority: Priority = Priority.NORMAL) -> bool:
        """Enqueue data for client"""
        queue_manager = self._get_queue_manager(client_id)

        item = QueueItem(
            item_id=f"item_{secrets.token_hex(8)}",
            topic=topic,
            data=data,
            priority=priority,
            timestamp=time.time()
        )

        success = queue_manager.enqueue(item)

        if not success:
            if self.on_queue_full:
                self.on_queue_full(client_id, topic)

        self._update_backpressure(client_id)

        return success

    def dequeue(self, client_id: str) -> Optional[QueueItem]:
        """Dequeue next item for client"""
        queue_manager = self._get_queue_manager(client_id)
        item = queue_manager.dequeue()

        if item:
            self._update_backpressure(client_id)

        return item

    def dequeue_batch(self, client_id: str, max_count: int = 50) -> List[QueueItem]:
        """Dequeue batch for client"""
        queue_manager = self._get_queue_manager(client_id)
        items = queue_manager.dequeue_batch(max_count)

        if items:
            self._update_backpressure(client_id)

        return items

    def _update_backpressure(self, client_id: str):
        """Update backpressure state"""
        queue_manager = self._get_queue_manager(client_id)

        queue_size = queue_manager.get_size()
        rate_limiter = self._get_rate_limiter(client_id)

        state_changed = self._monitor.update_client(
            client_id=client_id,
            send_queue=queue_size,
            receive_queue=0,
            send_rate=1.0 / max(rate_limiter.get_wait_time(), 0.001),
            receive_rate=0
        )

        if state_changed:
            state = self._monitor.get_client_state(client_id)
            if state and self.on_backpressure_change:
                self.on_backpressure_change(client_id, state.state)

    def get_queue_depth(self, client_id: str) -> int:
        """Get queue depth for client"""
        queue_manager = self._get_queue_manager(client_id)
        return queue_manager.get_size()

    def get_backpressure_state(self, client_id: str) -> Optional[BackpressureState]:
        """Get backpressure state for client"""
        state = self._monitor.get_client_state(client_id)
        return state.state if state else None

    def set_online(self, online: bool):
        """Set online status"""
        was_online = self._is_online
        self._is_online = online

        if not was_online and online:
            logger.info("Back online - triggering sync")

    def queue_offline_mutation(self, topic: str, action: str,
                               payload: Dict, local_id: str) -> str:
        """Queue mutation for offline replay"""
        return self._offline_queue.add(topic, action, payload, local_id)

    def get_offline_mutations(self) -> List[OfflineMutation]:
        """Get pending offline mutations"""
        return self._offline_queue.get_all()

    def clear_offline_mutation(self, mutation_id: str):
        """Clear processed mutation"""
        self._offline_queue.remove(mutation_id)

    async def debounce_update(self, key: str, callback: Callable, *args, **kwargs):
        """Debounce an update"""
        await self._debouncer.debounce(key, callback, *args, **kwargs)

    async def batch_update(self, key: str, item: Any, callback: Callable):
        """Batch an update"""
        await self._batcher.add(key, item, callback)

    def detect_conflict(self, mutation: OfflineMutation, remote: Dict) -> Optional[ConflictInfo]:
        """Detect conflict"""
        return self._conflict_resolver.detect_conflict(mutation, remote)

    def resolve_conflict(self, conflict: ConflictInfo, strategy: str = None) -> Dict:
        """Resolve conflict"""
        return self._conflict_resolver.resolve(conflict, strategy)

    def get_stats(self) -> Dict:
        """Get handler statistics"""
        return {
            "clients": len(self._queue_managers),
            "total_queues": sum(qm.get_size() for qm in self._queue_managers.values()),
            "offline_mutations": len(self._offline_queue.get_all()),
            "backpressure_states": {
                state.value: count
                for state, count in self._monitor.get_all_states().items()
            },
            "is_online": self._is_online,
            "last_sync": self._last_sync
        }

    def cleanup_client(self, client_id: str):
        """Clean up client data"""
        self._rate_limiters.pop(client_id, None)
        self._queue_managers.pop(client_id, None)

        logger.debug(f"Cleaned up client: {client_id}")


_global_handler: Optional[WebSocketBackpressureHandler] = None


def get_backpressure_handler() -> WebSocketBackpressureHandler:
    """Get global backpressure handler"""
    global _global_handler
    if _global_handler is None:
        _global_handler = WebSocketBackpressureHandler()
    return _global_handler
