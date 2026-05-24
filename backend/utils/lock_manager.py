"""
Distributed Lock Manager
========================

Distributed locking for concurrency control:
- File-based locks
- Lock timeouts
- Deadlock prevention
- Lock acquisition tracking
"""

import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from backend import config

logger = logging.getLogger("lock.manager")


class LockAcquireError(Exception):
    """Lock acquisition failed"""
    pass


class DistributedLock:
    """Distributed file-based lock"""

    def __init__(self, name: str, timeout: float = 30.0, lock_dir: str = None):
        self.name = name
        self.timeout = timeout
        self.lock_dir = Path(lock_dir or config.DATA_DIR) / "locks"
        self.lock_dir.mkdir(parents=True, exist_ok=True)

        self.lock_file = self.lock_dir / f"{name}.lock"
        self._acquired = False
        self._acquired_at: Optional[float] = None
        self._lock = threading.Lock()

    def acquire(self, blocking: bool = True, timeout: float = None) -> bool:
        """Acquire lock"""
        timeout = timeout or self.timeout

        with self._lock:
            if self._acquired:
                if not blocking:
                    return False

                # Wait for timeout
                start = time.time()
                while self._acquired and time.time() - start < timeout:
                    time.sleep(0.1)

                if self._acquired:
                    return False

            # Try to acquire
            if self.lock_file.exists():
                # Check if stale
                try:
                    mtime = os.path.getmtime(str(self.lock_file))
                    if time.time() - mtime > timeout:
                        # Stale lock, force acquire
                        self._force_acquire()
                        return True
                except Exception:
                    pass
                return False

            # Create lock file
            try:
                with open(self.lock_file, "w") as f:
                    f.write(f"{os.getpid()},{time.time()}")
                self._acquired = True
                self._acquired_at = time.time()
                return True
            except Exception:
                return False

    def _force_acquire(self):
        """Force acquire stale lock"""
        try:
            self.lock_file.unlink()
        except Exception:
            pass

    def release(self):
        """Release lock"""
        with self._lock:
            if self._acquired:
                try:
                    self.lock_file.unlink()
                except Exception:
                    pass
                self._acquired = False
                self._acquired_at = None

    def is_acquired(self) -> bool:
        """Check if lock is acquired"""
        return self._acquired

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

    def __del__(self):
        self.release()


class LockManager:
    """
    Lock manager for multiple resources.
    """

    def __init__(self):
        self._locks: dict = {}
        self._lock = threading.Lock()

    def get_lock(self, name: str, timeout: float = 30.0) -> DistributedLock:
        """Get or create lock"""
        with self._lock:
            if name not in self._locks:
                self._locks[name] = DistributedLock(name, timeout)
            return self._locks[name]

    def acquire(self, name: str, blocking: bool = True) -> bool:
        """Acquire lock"""
        return self.get_lock(name).acquire(blocking)

    def release(self, name: str):
        """Release lock"""
        lock = self._locks.get(name)
        if lock:
            lock.release()

    def cleanup_stale_locks(self, max_age: float = 3600):
        """Clean up stale lock files"""
        lock_dir = Path(config.DATA_DIR) / "locks"
        if not lock_dir.exists():
            return

        now = time.time()
        for f in lock_dir.glob("*.lock"):
            try:
                mtime = os.path.getmtime(str(f))
                if now - mtime > max_age:
                    f.unlink()
            except Exception:
                pass


# Global lock manager
_lock_manager: Optional[LockManager] = None


def get_lock_manager() -> LockManager:
    """Get global lock manager"""
    global _lock_manager
    if _lock_manager is None:
        _lock_manager = LockManager()
    return _lock_manager


__all__ = ["DistributedLock", "LockManager", "LockAcquireError", "get_lock_manager"]
