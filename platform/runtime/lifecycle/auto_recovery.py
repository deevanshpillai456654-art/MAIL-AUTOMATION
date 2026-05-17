"""
AutoRecovery — watches for failed/degraded plugins and attempts automatic restart.

Strategy: exponential backoff with jitter, max *max_attempts* per plugin.
After max_attempts the plugin is marked DEAD and requires manual intervention.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)


@dataclass
class RecoveryState:
    plugin_id:   str
    attempts:    int = 0
    max_attempts: int = 5
    backoff_base: float = 2.0   # seconds
    backoff_max:  float = 300.0 # 5 minutes
    dead:        bool = False

    def next_delay(self) -> float:
        delay = min(self.backoff_base * (2 ** self.attempts), self.backoff_max)
        return delay + random.uniform(0, delay * 0.1)  # 10% jitter


class AutoRecovery:
    """
    Subscribes to health monitor failures and lifecycle FAILED events,
    then schedules automatic restart with backoff.
    """

    def __init__(
        self,
        lifecycle_manager: Any,
        bus: Any,
        *,
        max_attempts: int = 5,
    ) -> None:
        self._lifecycle = lifecycle_manager
        self._bus       = bus
        self._max       = max_attempts
        self._states:   Dict[str, RecoveryState] = {}
        self._tasks:    Dict[str, asyncio.Task] = {}

    def attach(self) -> None:
        """Subscribe to bus events. Call once at startup."""
        if not self._bus:
            return
        self._bus.subscribe(
            ["plugin.health.degraded", "plugin.lifecycle.failed"],
            self._on_failure,
            sub_id="__auto_recovery__",
        )

    async def _on_failure(self, event: Any) -> None:
        plugin_id = event.payload.get("plugin_id", "")
        if not plugin_id:
            return
        await self.schedule_recovery(plugin_id)

    async def schedule_recovery(self, plugin_id: str) -> None:
        state = self._states.setdefault(
            plugin_id,
            RecoveryState(plugin_id=plugin_id, max_attempts=self._max),
        )
        if state.dead:
            log.warning("AutoRecovery: %s is marked DEAD — manual restart required", plugin_id)
            return

        # Cancel any pending recovery task
        existing = self._tasks.get(plugin_id)
        if existing and not existing.done():
            return  # already scheduled

        delay = state.next_delay()
        log.info(
            "AutoRecovery: scheduling restart of %s in %.1fs (attempt %d/%d)",
            plugin_id, delay, state.attempts + 1, state.max_attempts,
        )
        task = asyncio.create_task(self._recover_after(plugin_id, delay, state))
        self._tasks[plugin_id] = task

    async def _recover_after(
        self, plugin_id: str, delay: float, state: RecoveryState
    ) -> None:
        await asyncio.sleep(delay)
        state.attempts += 1

        log.info("AutoRecovery: attempting restart of %s", plugin_id)
        ok = await self._lifecycle.restart(plugin_id)
        if ok:
            state.attempts = 0  # reset on success
            log.info("AutoRecovery: %s recovered successfully", plugin_id)
            if self._bus:
                await self._bus.publish(
                    "plugin.lifecycle.recovered",
                    source="auto_recovery",
                    tenant_id="__system__",
                    payload={"plugin_id": plugin_id},
                )
        else:
            if state.attempts >= state.max_attempts:
                state.dead = True
                log.error(
                    "AutoRecovery: %s exhausted %d recovery attempts — marked DEAD",
                    plugin_id, state.max_attempts,
                )
                if self._bus:
                    await self._bus.publish(
                        "plugin.lifecycle.dead",
                        source="auto_recovery",
                        tenant_id="__system__",
                        payload={"plugin_id": plugin_id, "attempts": state.attempts},
                    )

    def reset(self, plugin_id: str) -> None:
        """Clear recovery state (e.g., after manual restart)."""
        self._states.pop(plugin_id, None)
        task = self._tasks.pop(plugin_id, None)
        if task and not task.done():
            task.cancel()

    def status(self) -> Dict[str, Any]:
        return {
            pid: {
                "attempts": s.attempts,
                "max_attempts": s.max_attempts,
                "dead": s.dead,
            }
            for pid, s in self._states.items()
        }
