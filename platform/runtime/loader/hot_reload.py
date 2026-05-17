"""
HotReloadWatcher — watches plugin source files for changes and triggers hot reload.

Uses Python's built-in watchdog pattern via asyncio file polling (no extra deps).
Falls back silently in production if watching is disabled.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Set

log = logging.getLogger(__name__)


class HotReloadWatcher:
    """
    Polls plugin source files for mtime changes and calls reload_callback.

    Usage::

        watcher = HotReloadWatcher(poll_interval_s=2.0)
        watcher.watch("salesforce", Path("/plugins/salesforce/connector.py"))
        watcher.on_change = lambda plugin_id: asyncio.create_task(loader.hot_reload(plugin_id))
        asyncio.create_task(watcher.run())
    """

    def __init__(self, poll_interval_s: float = 2.0) -> None:
        self._interval = poll_interval_s
        self._files: Dict[str, Path]    = {}   # plugin_id → file path
        self._mtimes: Dict[str, float]  = {}   # plugin_id → last mtime
        self._running = False
        self.on_change: Optional[Callable[[str], Any]] = None

    def watch(self, plugin_id: str, path: str | Path) -> None:
        p = Path(path)
        self._files[plugin_id] = p
        try:
            self._mtimes[plugin_id] = p.stat().st_mtime
        except Exception:
            self._mtimes[plugin_id] = 0.0

    def unwatch(self, plugin_id: str) -> None:
        self._files.pop(plugin_id, None)
        self._mtimes.pop(plugin_id, None)

    async def run(self) -> None:
        """Start watching loop. Call asyncio.create_task(watcher.run())."""
        self._running = True
        log.info("HotReloadWatcher: started, polling %d files every %.1fs",
                 len(self._files), self._interval)
        while self._running:
            await asyncio.sleep(self._interval)
            changed: Set[str] = set()
            for pid, path in list(self._files.items()):
                try:
                    mtime = path.stat().st_mtime
                except Exception:
                    continue
                if mtime != self._mtimes.get(pid, -1.0):
                    self._mtimes[pid] = mtime
                    changed.add(pid)

            for pid in changed:
                log.info("HotReloadWatcher: %s changed — triggering reload", pid)
                if self.on_change:
                    try:
                        result = self.on_change(pid)
                        if asyncio.iscoroutine(result):
                            await result
                    except Exception as exc:
                        log.error("HotReloadWatcher: reload callback error for %s: %s", pid, exc)

    def stop(self) -> None:
        self._running = False
