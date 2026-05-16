"""
Production EventBus for the MailPilot Connector & Plugin Panel.

The EventBus provides:
- Persistent event storage via ConnectorPanelDB
- In-memory subscriber callbacks (async)
- Thread-safe publish/subscribe with asyncio locks
- Statistics tracking
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

EventHandler = Callable[[str, str, str, dict], Coroutine[Any, Any, None]]
"""Async callback: (event_type, source_connector_id, tenant_id, payload) -> None"""


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------

class EventBus:
    """
    Singleton async event bus.

    Usage::

        bus = EventBus.instance()

        # Subscribe
        async def my_handler(event_type, source, tenant_id, payload):
            print(event_type, payload)

        bus.subscribe("my_connector", ["invoice.created"], my_handler)

        # Publish
        await bus.publish("invoice.created", "erp_sync", "tenant_1", {"id": "INV-001"})
    """

    _instance: "EventBus | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        # subscriber_id -> list of event_types  (None means "all events")
        self._subscriptions: dict[str, list[str] | None] = {}
        # event_type -> list of (subscriber_id, handler)
        self._handlers: dict[str, list[tuple[str, EventHandler]]] = defaultdict(list)
        # subscriber_id -> handler (for "all events" subscriptions)
        self._wildcard_handlers: dict[str, EventHandler] = {}
        # statistics
        self._published_count: int = 0
        self._handler_errors: int = 0
        # asyncio lock — created lazily when first needed inside an event loop
        self._lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "EventBus":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _persist_event(
        self,
        event_id: str,
        event_type: str,
        source_connector_id: str,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Store the event in the database (best-effort, non-blocking)."""
        try:
            from platform.connectors_panel.backend.db import get_panel_db  # type: ignore
        except ImportError:
            try:
                # Allow import when running from the package directory
                import importlib, sys
                module = importlib.import_module("backend.db")
                db = module.get_panel_db()
            except Exception:
                logger.debug("EventBus: could not persist event — DB not available")
                return
        else:
            db = get_panel_db()

        try:
            now = datetime.now(tz=timezone.utc).isoformat()
            db.execute(
                """
                INSERT INTO events
                    (id, event_type, source_connector_id, tenant_id, payload_json, published_at, processed_by_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, event_type, source_connector_id, tenant_id, json.dumps(payload), now, "[]"),
            )
        except Exception as exc:
            logger.warning("EventBus: failed to persist event %s: %s", event_id, exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def publish(
        self,
        event_type: str,
        source: str,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> str:
        """
        Publish an event.

        Persists the event to the database and fires all matching async
        subscriber callbacks concurrently.

        Returns the event_id.
        """
        event_id = f"evt_{uuid.uuid4().hex}"

        # Persist (synchronous, but fast)
        self._persist_event(event_id, event_type, source, tenant_id, payload)

        # Collect handlers to call
        handlers_to_call: list[tuple[str, EventHandler]] = []

        async with self._get_lock():
            self._published_count += 1
            # Type-specific handlers
            for sub_id, handler in self._handlers.get(event_type, []):
                handlers_to_call.append((sub_id, handler))
            # Wildcard handlers
            for sub_id, handler in self._wildcard_handlers.items():
                handlers_to_call.append((sub_id, handler))

        # Fire handlers concurrently
        if handlers_to_call:
            tasks = []
            for sub_id, handler in handlers_to_call:
                tasks.append(
                    asyncio.ensure_future(
                        self._safe_call(handler, event_type, source, tenant_id, payload, sub_id)
                    )
                )
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.debug(
            "EventBus: published %s from %s (tenant=%s, handlers=%d)",
            event_type, source, tenant_id, len(handlers_to_call),
        )
        return event_id

    async def _safe_call(
        self,
        handler: EventHandler,
        event_type: str,
        source: str,
        tenant_id: str,
        payload: dict[str, Any],
        subscriber_id: str,
    ) -> None:
        try:
            await handler(event_type, source, tenant_id, payload)
        except Exception as exc:
            self._handler_errors += 1
            logger.error(
                "EventBus: handler for subscriber '%s' raised: %s",
                subscriber_id, exc, exc_info=True,
            )

    def subscribe(
        self,
        subscriber_id: str,
        event_types: list[str] | None,
        callback: EventHandler,
    ) -> None:
        """
        Register an async callback for one or more event types.

        If *event_types* is None or empty, the callback receives ALL events.
        """
        if not event_types:
            self._subscriptions[subscriber_id] = None
            self._wildcard_handlers[subscriber_id] = callback
            logger.debug("EventBus: %s subscribed to ALL events", subscriber_id)
            return

        self._subscriptions[subscriber_id] = event_types
        for et in event_types:
            # Avoid duplicate registration
            existing_ids = [s for s, _ in self._handlers[et]]
            if subscriber_id not in existing_ids:
                self._handlers[et].append((subscriber_id, callback))
        logger.debug(
            "EventBus: %s subscribed to %s", subscriber_id, event_types
        )

    def unsubscribe(self, subscriber_id: str) -> None:
        """Remove all subscriptions for a given subscriber_id."""
        event_types = self._subscriptions.pop(subscriber_id, None)
        self._wildcard_handlers.pop(subscriber_id, None)

        if event_types:
            for et in event_types:
                self._handlers[et] = [
                    (s, h) for s, h in self._handlers[et] if s != subscriber_id
                ]
        else:
            # Wildcard — iterate all types
            for et in list(self._handlers.keys()):
                self._handlers[et] = [
                    (s, h) for s, h in self._handlers[et] if s != subscriber_id
                ]
        logger.debug("EventBus: %s unsubscribed", subscriber_id)

    def get_subscribers(self, event_type: str) -> list[str]:
        """Return subscriber IDs that will receive *event_type*."""
        specific = [s for s, _ in self._handlers.get(event_type, [])]
        wildcards = list(self._wildcard_handlers.keys())
        return list(set(specific + wildcards))

    def get_stats(self) -> dict[str, Any]:
        """Return current subscription and publish statistics."""
        subscription_counts: dict[str, int] = {}
        for et, handlers in self._handlers.items():
            subscription_counts[et] = len(handlers)

        return {
            "total_subscribers": len(self._subscriptions),
            "wildcard_subscribers": len(self._wildcard_handlers),
            "event_type_subscriptions": subscription_counts,
            "published_count": self._published_count,
            "handler_errors": self._handler_errors,
            "subscriptions": {
                sub_id: types if types else "ALL"
                for sub_id, types in self._subscriptions.items()
            },
        }

    def clear(self) -> None:
        """Clear all subscriptions (useful for testing)."""
        self._subscriptions.clear()
        self._handlers.clear()
        self._wildcard_handlers.clear()


# Module-level convenience accessor
def get_event_bus() -> EventBus:
    return EventBus.instance()
