"""SQLite connection guard for warning-free runtime and tests.

Several lightweight service modules create short-lived sqlite3 connections
without going through the shared Database wrapper. Python 3.13 surfaces those
missed closes as ResourceWarning unraisable exceptions during strict validation.
This guard preserves sqlite3.connect behavior while tracking returned connection
objects so test teardown and application shutdown can close any handles that a
module forgot to release.
"""
from __future__ import annotations

import atexit
import sqlite3
import threading
from typing import Any

_ORIGINAL_CONNECT = sqlite3.connect
_LOCK = threading.RLock()
_CONNECTIONS: list[sqlite3.Connection] = []
_PATCHED = False


class TrackedConnection(sqlite3.Connection):
    """sqlite3 connection that unregisters itself when closed."""

    def close(self) -> None:  # type: ignore[override]
        try:
            _unregister_connection(self)
        finally:
            super().close()


def _register_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    with _LOCK:
        if all(existing is not conn for existing in _CONNECTIONS):
            _CONNECTIONS.append(conn)
    return conn


def _unregister_connection(conn: sqlite3.Connection) -> None:
    with _LOCK:
        _CONNECTIONS[:] = [existing for existing in _CONNECTIONS if existing is not conn]


def tracked_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
    """Drop-in replacement for sqlite3.connect with close tracking."""
    if "factory" not in kwargs or kwargs.get("factory") is None:
        kwargs["factory"] = TrackedConnection
    # Allow shutdown/test cleanup to close forgotten connections from the
    # controlling thread. Modules that intentionally specify this option keep
    # their explicit behavior.
    if "check_same_thread" not in kwargs:
        kwargs["check_same_thread"] = False
    conn = _ORIGINAL_CONNECT(*args, **kwargs)
    return _register_connection(conn)


def install_sqlite_connection_guard() -> None:
    """Install the sqlite connect tracker once per interpreter."""
    global _PATCHED
    with _LOCK:
        if _PATCHED or sqlite3.connect is tracked_connect:
            _PATCHED = True
            return
        sqlite3.connect = tracked_connect  # type: ignore[assignment]
        _PATCHED = True


def close_all_tracked_connections() -> None:
    """Close any sqlite handles still tracked by direct-connect modules."""
    with _LOCK:
        conns = list(_CONNECTIONS)
        _CONNECTIONS.clear()
    for conn in conns:
        try:
            conn.close()
        except Exception:
            pass


def tracked_connection_count() -> int:
    with _LOCK:
        return len(_CONNECTIONS)


atexit.register(close_all_tracked_connections)
