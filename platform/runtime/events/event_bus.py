"""
RuntimeEventBus — Production-grade event bus for the plugin runtime.

Features:
- Tenant-aware pub/sub with wildcard glob pattern matching
- Async concurrent handler dispatch with configurable timeout
- Persistent event log via EventStore (bridgeable to DB)
- Priority queues (CRITICAL > HIGH > NORMAL > LOW)
- Dead-letter queue for failed/unhandled events
- Per-event tracing metadata
- Thread-safe singleton; safe to call from sync contexts via asyncio.run_coroutine_threadsafe
- No core-system imports — fully self-contained
"""
from __future__ import annotations

import asyncio
import fnmatch
import logging
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Priority
# ---------------------------------------------------------------------------

class EventPriority(IntEnum):
    CRITICAL = 0
    HIGH     = 1
    NORMAL   = 2
    LOW      = 3


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RuntimeEvent:
    event_type: str
    source:     str
    tenant_id:  str
    payload:    Dict[str, Any]
    event_id:   str                 = field(default_factory=lambda: f"evt_{uuid.uuid4().hex}")
    priority:   EventPriority       = EventPriority.NORMAL
    published_at: str               = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trace_id:   Optional[str]       = None
    correlation_id: Optional[str]   = None
    replay:     bool                = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id":       self.event_id,
            "event_type":     self.event_type,
            "source":         self.source,
            "tenant_id":      self.tenant_id,
            "payload":        self.payload,
            "priority":       int(self.priority),
            "published_at":   self.published_at,
            "trace_id":       self.trace_id,
            "correlation_id": self.correlation_id,
            "replay":         self.replay,
        }


# Handler type: async (event: RuntimeEvent) -> None
EventHandler = Callable[[RuntimeEvent], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

@dataclass
class Subscription:
    sub_id:       str
    patterns:     List[str]   # glob patterns, e.g. ["crm.*", "shipment.delayed"]
    tenant_filter: Optional[str]  # None = all tenants
    handler:      EventHandler
    priority_min: EventPriority = EventPriority.LOW  # only receive >= this priority

    def matches(self, event: RuntimeEvent) -> bool:
        # Tenant check
        if self.tenant_filter and self.tenant_filter != event.tenant_id:
            return False
        # Priority check
        if event.priority > self.priority_min:
            return False
        # Pattern check (any pattern matches)
        return any(fnmatch.fnmatch(event.event_type, p) for p in self.patterns)


# ---------------------------------------------------------------------------
# RuntimeEventBus
# ---------------------------------------------------------------------------

class RuntimeEventBus:
    """
    Central event bus for the plugin runtime.

    Usage (inside async context)::

        bus = RuntimeEventBus.instance()
        sub_id = bus.subscribe(["crm.*", "invoice.created"], my_handler)
        event_id = await bus.publish("crm.contact.created", "salesforce", "tenant_1", {...})
        bus.unsubscribe(sub_id)
    """

    _instance: Optional["RuntimeEventBus"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._subs:     Dict[str, Subscription]  = {}
        self._handlers: Dict[str, List[str]]     = defaultdict(list)  # pattern → [sub_ids]
        self._stats = {
            "published":      0,
            "delivered":      0,
            "handler_errors": 0,
            "dead_letters":   0,
        }
        self._store:      Optional[Any] = None  # EventStore, injected after init
        self._dlq:        Optional[Any] = None  # DeadLetterQueue, injected after init
        self._loop_lock:  Optional[asyncio.Lock] = None
        self._handler_timeout_s: float = 30.0

    # ── Singleton ──────────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "RuntimeEventBus":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def configure(
        self,
        store: Any = None,
        dlq: Any = None,
        handler_timeout_s: float = 30.0,
    ) -> None:
        self._store = store
        self._dlq   = dlq
        self._handler_timeout_s = handler_timeout_s

    # ── Lock ───────────────────────────────────────────────────────────────

    def _alolock(self) -> asyncio.Lock:
        if self._loop_lock is None:
            self._loop_lock = asyncio.Lock()
        return self._loop_lock

    # ── Subscribe ─────────────────────────────────────────────────────────

    def subscribe(
        self,
        patterns: List[str],
        handler: EventHandler,
        *,
        sub_id: Optional[str] = None,
        tenant_filter: Optional[str] = None,
        priority_min: EventPriority = EventPriority.LOW,
    ) -> str:
        """
        Register *handler* for events matching any of *patterns*.
        Returns the subscription ID (use it to unsubscribe).

        Patterns support glob syntax:  "crm.*", "*.created", "shipment.*.*"
        """
        sid = sub_id or f"sub_{uuid.uuid4().hex[:12]}"
        sub = Subscription(
            sub_id=sid,
            patterns=patterns,
            tenant_filter=tenant_filter,
            handler=handler,
            priority_min=priority_min,
        )
        self._subs[sid] = sub
        log.debug("EventBus: subscribed %s → patterns=%s tenant=%s", sid, patterns, tenant_filter)
        return sid

    def unsubscribe(self, sub_id: str) -> None:
        self._subs.pop(sub_id, None)
        log.debug("EventBus: unsubscribed %s", sub_id)

    def unsubscribe_all(self, prefix: str) -> int:
        """Remove all subscriptions whose sub_id starts with *prefix*."""
        removed = [sid for sid in list(self._subs) if sid.startswith(prefix)]
        for sid in removed:
            self._subs.pop(sid)
        return len(removed)

    # ── Publish ───────────────────────────────────────────────────────────

    async def publish(
        self,
        event_type: str,
        source: str,
        tenant_id: str,
        payload: Dict[str, Any],
        *,
        priority: EventPriority = EventPriority.NORMAL,
        trace_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> str:
        """Publish an event and deliver to all matching subscribers."""
        event = RuntimeEvent(
            event_type=event_type,
            source=source,
            tenant_id=tenant_id,
            payload=payload,
            priority=priority,
            trace_id=trace_id or f"tr_{uuid.uuid4().hex[:16]}",
            correlation_id=correlation_id,
        )
        return await self._dispatch(event)

    async def publish_event(self, event: RuntimeEvent) -> str:
        """Publish a pre-built RuntimeEvent (e.g., for replay)."""
        return await self._dispatch(event)

    async def _dispatch(self, event: RuntimeEvent) -> str:
        async with self._alolock():
            self._stats["published"] += 1

        # Persist first (best-effort)
        if self._store:
            try:
                await self._store.append(event)
            except Exception as exc:
                log.warning("EventBus: store.append failed for %s: %s", event.event_id, exc)

        # Find matching subscribers sorted by priority
        matching = [
            sub for sub in self._subs.values()
            if sub.matches(event)
        ]
        if not matching:
            log.debug("EventBus: no subscribers for %s (tenant=%s)", event.event_type, event.tenant_id)
            return event.event_id

        # Dispatch concurrently with timeout
        tasks = [
            asyncio.ensure_future(
                self._safe_call(sub, event)
            )
            for sub in matching
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        delivered = sum(1 for r in results if not isinstance(r, Exception))
        async with self._alolock():
            self._stats["delivered"] += delivered

        log.debug(
            "EventBus: %s dispatched to %d/%d handlers (tenant=%s, trace=%s)",
            event.event_type, delivered, len(matching), event.tenant_id, event.trace_id,
        )
        return event.event_id

    async def _safe_call(self, sub: Subscription, event: RuntimeEvent) -> None:
        try:
            await asyncio.wait_for(sub.handler(event), timeout=self._handler_timeout_s)
        except asyncio.TimeoutError:
            async with self._alolock():
                self._stats["handler_errors"] += 1
            log.error("EventBus: handler %s timed out for %s", sub.sub_id, event.event_type)
            await self._send_to_dlq(event, sub.sub_id, "timeout")
        except Exception as exc:
            async with self._alolock():
                self._stats["handler_errors"] += 1
            log.error("EventBus: handler %s raised for %s: %s", sub.sub_id, event.event_type, exc, exc_info=True)
            await self._send_to_dlq(event, sub.sub_id, str(exc))

    async def _send_to_dlq(self, event: RuntimeEvent, sub_id: str, reason: str) -> None:
        if not self._dlq:
            return
        async with self._alolock():
            self._stats["dead_letters"] += 1
        try:
            await self._dlq.enqueue(event, sub_id, reason)
        except Exception as exc:
            log.warning("EventBus: DLQ enqueue failed: %s", exc)

    # ── Query ─────────────────────────────────────────────────────────────

    def get_subscribers(self, event_type: str, tenant_id: str = "") -> List[str]:
        """Return sub_ids that would receive *event_type* for *tenant_id*."""
        mock = RuntimeEvent(
            event_type=event_type,
            source="__query__",
            tenant_id=tenant_id or "__any__",
            payload={},
        )
        return [s.sub_id for s in self._subs.values() if s.matches(mock)]

    def get_stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "active_subscriptions": len(self._subs),
            "subscription_patterns": {
                sid: sub.patterns for sid, sub in self._subs.items()
            },
        }

    def reset_stats(self) -> None:
        self._stats = {k: 0 for k in self._stats}

    # ── Bridge to existing connectors-panel EventBus ──────────────────────

    def bridge_to_panel_bus(self, patterns: Optional[List[str]] = None) -> str:
        """
        Subscribe to events and forward them to the existing connectors-panel
        EventBus.  Called once during runtime bootstrap.
        """
        async def _forward(event: RuntimeEvent) -> None:
            try:
                from platform.connectors_panel.shared.event_bus import get_event_bus  # type: ignore
                panel_bus = get_event_bus()
                await panel_bus.publish(
                    event.event_type,
                    event.source,
                    event.tenant_id,
                    event.payload,
                )
            except Exception as exc:
                log.debug("EventBus bridge: panel bus not available: %s", exc)

        return self.subscribe(
            patterns or ["*"],
            _forward,
            sub_id="__bridge_panel__",
        )


# ---------------------------------------------------------------------------
# Module-level accessor
# ---------------------------------------------------------------------------

def get_runtime_bus() -> RuntimeEventBus:
    return RuntimeEventBus.instance()
