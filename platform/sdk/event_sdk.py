"""
EventSDK — fluent event publishing and subscription API for plugins.

Usage::

    sdk = EventSDK(context)
    await sdk.emit("crm.contact.created", {"id": "C1", "name": "Alice"})
    sdk.on("invoice.*", handle_invoice)
    sdk.on_all(log_all_events)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

log = logging.getLogger(__name__)


class EventSDK:
    """
    Fluent event API surface for plugins.

    All methods are proxied through ConnectorContext.event_bus so
    plugins never import the bus directly.
    """

    def __init__(self, context: Any) -> None:
        self._ctx  = context
        self._subs: List[str] = []

    @property
    def _bus(self) -> Optional[Any]:
        return getattr(self._ctx, "event_bus", None)

    # ── Emit ──────────────────────────────────────────────────────────────

    async def emit(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        tenant_id: Optional[str] = None,
        priority: int = 2,
        correlation_id: Optional[str] = None,
    ) -> Optional[str]:
        """Publish an event. Returns event_id."""
        if not self._bus:
            return None
        tid = tenant_id or getattr(self._ctx, "tenant_id", "__system__")
        from ..runtime.events.event_bus import EventPriority
        return await self._bus.publish(
            event_type,
            source=getattr(self._ctx, "plugin_id", "unknown"),
            tenant_id=tid,
            payload=payload,
            priority=EventPriority(priority),
            correlation_id=correlation_id,
        )

    async def emit_batch(
        self,
        events: List[Dict[str, Any]],
        tenant_id: Optional[str] = None,
    ) -> List[str]:
        """Emit multiple events. Returns list of event_ids."""
        ids = []
        for evt in events:
            eid = await self.emit(
                evt["event_type"],
                evt.get("payload", {}),
                tenant_id=tenant_id,
            )
            if eid:
                ids.append(eid)
        return ids

    # ── Subscribe ─────────────────────────────────────────────────────────

    def on(
        self,
        pattern: str,
        handler: Callable[[Any], Coroutine[Any, Any, None]],
        *,
        tenant_id: Optional[str] = None,
    ) -> str:
        """Subscribe to events matching *pattern*. Returns subscription ID."""
        if not self._bus:
            return ""
        plugin_id = getattr(self._ctx, "plugin_id", "unknown")
        tid = tenant_id or getattr(self._ctx, "tenant_id", None)
        sub_id = self._bus.subscribe(
            [pattern],
            handler,
            sub_id=f"{plugin_id}_{pattern.replace('*','x').replace('.','_')}",
            tenant_filter=tid,
        )
        self._subs.append(sub_id)
        return sub_id

    def on_all(
        self,
        handler: Callable[[Any], Coroutine[Any, Any, None]],
    ) -> str:
        return self.on("*", handler)

    def off(self, sub_id: str) -> None:
        if self._bus:
            self._bus.unsubscribe(sub_id)
        if sub_id in self._subs:
            self._subs.remove(sub_id)

    def cleanup(self) -> None:
        """Unsubscribe all subscriptions created via this SDK instance."""
        for sid in list(self._subs):
            self.off(sid)
