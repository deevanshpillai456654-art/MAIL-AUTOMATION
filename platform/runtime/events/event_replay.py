"""
EventReplayService — replay historical events to rebuild state or re-process failures.

Use cases:
  - Replay all CRM events for a tenant from a given timestamp
  - Re-deliver dead-letter events after a handler bug is fixed
  - Rebuild plugin internal state from the event log
  - Development/debug: replay a specific trace_id
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class EventReplayService:
    """
    Reads events from an EventStore and re-publishes them through the RuntimeEventBus.

    Replay events are flagged with ``replay=True`` so handlers can choose
    to skip side-effects (e.g. skip sending emails during replay).
    """

    def __init__(self, store: Any, bus: Any) -> None:
        self._store = store
        self._bus   = bus

    async def replay(
        self,
        *,
        tenant_id: Optional[str] = None,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        trace_id: Optional[str] = None,
        batch_size: int = 100,
        delay_between_batches_s: float = 0.0,
        on_event: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Replay matching events in chronological order.

        Args:
            tenant_id: replay only for this tenant.
            event_type: glob-compatible filter ("crm.*").
            source: filter by originating connector.
            since/until: ISO8601 time window.
            trace_id: replay an exact trace.
            batch_size: events per DB fetch.
            delay_between_batches_s: throttle between batches.
            on_event: optional async callback(event_dict) for progress tracking.

        Returns:
            dict with total, replayed, errors counters.
        """
        from .event_bus import RuntimeEvent, EventPriority

        total = replayed = errors = 0
        offset = 0

        log.info(
            "EventReplay: starting replay tenant=%s type=%s since=%s",
            tenant_id, event_type, since,
        )

        while True:
            rows = self._store.query(
                tenant_id=tenant_id,
                event_type=event_type,
                source=source,
                since=since,
                until=until,
                trace_id=trace_id,
                limit=batch_size,
                offset=offset,
            )
            if not rows:
                break

            for row in rows:
                total += 1
                try:
                    evt = RuntimeEvent(
                        event_id=f"rpl_{row['event_id']}",
                        event_type=row["event_type"],
                        source=row["source"],
                        tenant_id=row["tenant_id"],
                        payload=row["payload"],
                        priority=EventPriority(row.get("priority", 2)),
                        published_at=row["published_at"],
                        trace_id=row.get("trace_id"),
                        correlation_id=row.get("correlation_id"),
                        replay=True,
                    )
                    await self._bus.publish_event(evt)
                    replayed += 1
                    if on_event:
                        try:
                            await on_event(row)
                        except Exception:
                            pass
                except Exception as exc:
                    errors += 1
                    log.error("EventReplay: error replaying %s: %s", row.get("event_id"), exc)

            offset += batch_size
            if delay_between_batches_s > 0:
                await asyncio.sleep(delay_between_batches_s)

        log.info(
            "EventReplay: done — total=%d replayed=%d errors=%d",
            total, replayed, errors,
        )
        return {"total": total, "replayed": replayed, "errors": errors}

    async def replay_trace(self, trace_id: str) -> Dict[str, Any]:
        """Replay all events belonging to a specific trace."""
        return await self.replay(trace_id=trace_id)

    async def replay_since(
        self,
        since: str,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Replay all events since an ISO8601 timestamp."""
        return await self.replay(since=since, tenant_id=tenant_id)
