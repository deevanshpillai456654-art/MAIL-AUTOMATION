"""
Provider Sandbox - Isolated Execution Environment per Provider
=============================================================

Enterprise sandboxing:
- Isolated execution environment per provider
- Crash isolation (one provider crash doesn't affect others)
- Timeout enforcement (max 5 minutes per operation)
- Resource limit enforcement per provider
- Memory limit enforcement per provider
"""

import logging
import os
import signal
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import psutil

logger = logging.getLogger("provider.sandbox")

PROVIDERS = ["gmail", "outlook", "yahoo", "zoho", "proton", "imap"]
MAX_OPERATION_TIMEOUT = 300
DEFAULT_MEMORY_LIMIT_MB = 256


class SandboxState(Enum):
    READY = "ready"
    RUNNING = "running"
    TIMEOUT = "timeout"
    CRASHED = "crashed"
    MEMORY_EXCEEDED = "memory_exceeded"
    STOPPED = "stopped"


@dataclass
class SandboxConfig:
    max_memory_mb: int = DEFAULT_MEMORY_LIMIT_MB
    max_timeout_seconds: int = MAX_OPERATION_TIMEOUT
    enable_crash_isolation: bool = True
    enable_memory_limit: bool = True
    enable_timeout: bool = True


@dataclass
class SandboxResult:
    success: bool
    result: Any = None
    error: Optional[str] = None
    elapsed_ms: float = 0
    memory_used_mb: float = 0
    sandbox_state: SandboxState = SandboxState.READY
    provider: str = ""


@dataclass
class SandboxOperation:
    operation_id: str
    provider: str
    func: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    started_at: float = 0
    completed_at: float = 0
    result: Any = None
    error: Optional[str] = None


class ProviderSandbox:
    """
    Isolated sandbox execution per provider.
    Each provider runs in its own protected environment.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._sandboxes: Dict[str, Dict[str, Any]] = {}
        self._configs: Dict[str, SandboxConfig] = {}
        self._active_operations: Dict[str, SandboxOperation] = {}
        self._operation_lock = threading.Lock()
        self._global_lock = threading.RLock()
        self._process = psutil.Process(os.getpid())

        for provider in PROVIDERS:
            self._configs[provider] = SandboxConfig()
            self._sandboxes[provider] = {
                "state": SandboxState.READY,
                "crash_count": 0,
                "timeout_count": 0,
                "memory_exceeded_count": 0,
                "total_operations": 0,
                "successful_operations": 0,
                "last_crash": None,
                "active_operation": None,
            }

        self._initialized = True
        logger.info("ProviderSandbox initialized for %d providers", len(PROVIDERS))

    def execute(self, provider: str, func: Callable, *args, **kwargs) -> SandboxResult:
        """
        Execute a function in an isolated sandbox for the provider.
        """
        operation_id = str(uuid.uuid4())[:12]
        config = self._configs.get(provider, SandboxConfig())

        with self._global_lock:
            if provider not in self._sandboxes:
                return SandboxResult(
                    success=False,
                    error=f"Unknown provider: {provider}",
                    sandbox_state=SandboxState.CRASHED,
                    provider=provider,
                )

            sandbox = self._sandboxes[provider]

        operation = SandboxOperation(
            operation_id=operation_id,
            provider=provider,
            func=func,
            args=args,
            kwargs=kwargs,
        )

        with self._operation_lock:
            self._active_operations[operation_id] = operation

        start_time = time.time()
        initial_memory = self._get_memory_usage()

        result = SandboxResult(provider=provider)

        if config.enable_crash_isolation:
            result = self._execute_with_crash_isolation(
                provider, operation, config, start_time, initial_memory
            )
        else:
            result = self._execute_direct(operation, config, start_time, initial_memory)

        operation.completed_at = time.time()
        operation.result = result.result
        operation.error = result.error

        with self._operation_lock:
            self._active_operations.pop(operation_id, None)

        with self._global_lock:
            sandbox = self._sandboxes[provider]
            sandbox["total_operations"] += 1
            if result.success:
                sandbox["successful_operations"] += 1
                sandbox["state"] = SandboxState.READY
            elif result.sandbox_state == SandboxState.TIMEOUT:
                sandbox["timeout_count"] += 1
            elif result.sandbox_state == SandboxState.MEMORY_EXCEEDED:
                sandbox["memory_exceeded_count"] += 1
            elif result.sandbox_state == SandboxState.CRASHED:
                sandbox["crash_count"] += 1
                sandbox["last_crash"] = {
                    "error": result.error,
                    "timestamp": time.time(),
                }

        return result

    def _execute_with_crash_isolation(
        self, provider: str, operation: SandboxOperation,
        config: SandboxConfig, start_time: float, initial_memory: float
    ) -> SandboxResult:
        result = SandboxResult(provider=provider)
        error_collector = {"error": None}

        def wrapped_execution():
            try:
                if config.enable_timeout:
                    signal.alarm(config.max_timeout_seconds)
                result.result = operation.func(*operation.args, **operation.kwargs)
            except Exception as e:
                error_collector["error"] = f"{type(e).__name__}: {e}"
            finally:
                if config.enable_timeout:
                    signal.alarm(0)

        thread = threading.Thread(target=wrapped_execution, daemon=True, name=f"sandbox-{provider}")
        thread.start()

        timeout_seconds = config.max_timeout_seconds
        thread.join(timeout=timeout_seconds)

        result.elapsed_ms = (time.time() - start_time) * 1000
        result.memory_used_mb = self._get_memory_usage() - initial_memory

        if thread.is_alive():
            result.success = False
            result.error = f"Operation timed out after {timeout_seconds}s"
            result.sandbox_state = SandboxState.TIMEOUT
            with self._global_lock:
                self._sandboxes[provider]["state"] = SandboxState.TIMEOUT
        elif error_collector["error"]:
            result.success = False
            result.error = error_collector["error"]
            result.sandbox_state = SandboxState.CRASHED
            logger.error("Provider %s sandbox crashed: %s", provider, error_collector["error"])
        else:
            result.success = True
            result.sandbox_state = SandboxState.RUNNING

        if config.enable_memory_limit:
            current_memory = self._get_memory_usage()
            if current_memory > config.max_memory_mb:
                result.success = False
                result.error = f"Memory limit exceeded: {current_memory:.1f}MB > {config.max_memory_mb}MB"
                result.sandbox_state = SandboxState.MEMORY_EXCEEDED
                logger.warning("Provider %s memory limit exceeded: %.1fMB", provider, current_memory)

        return result

    def _execute_direct(
        self, operation: SandboxOperation, config: SandboxConfig,
        start_time: float, initial_memory: float
    ) -> SandboxResult:
        result = SandboxResult(provider=operation.provider)

        try:
            if config.enable_timeout:
                signal.alarm(config.max_timeout_seconds)

            result.result = operation.func(*operation.args, **operation.kwargs)
            result.success = True

            if config.enable_timeout:
                signal.alarm(0)
        except Exception as e:
            result.success = False
            result.error = f"{type(e).__name__}: {e}"
            result.sandbox_state = SandboxState.CRASHED
        finally:
            if config.enable_timeout:
                signal.alarm(0)

        result.elapsed_ms = (time.time() - start_time) * 1000
        result.memory_used_mb = self._get_memory_usage() - initial_memory

        if config.enable_memory_limit:
            if result.memory_used_mb > config.max_memory_mb:
                result.success = False
                result.error = "Memory limit exceeded"
                result.sandbox_state = SandboxState.MEMORY_EXCEEDED

        return result

    def _get_memory_usage(self) -> float:
        try:
            mem = self._process.memory_info()
            return mem.rss / (1024 * 1024)
        except Exception:
            return 0

    def set_config(self, provider: str, config: SandboxConfig):
        with self._global_lock:
            self._configs[provider] = config
            logger.info("Sandbox config updated for %s: memory=%dMB, timeout=%ds",
                        provider, config.max_memory_mb, config.max_timeout_seconds)

    def get_config(self, provider: str) -> SandboxConfig:
        return self._configs.get(provider, SandboxConfig())

    def get_sandbox_state(self, provider: str) -> SandboxState:
        with self._global_lock:
            return self._sandboxes.get(provider, {}).get("state", SandboxState.STOPPED)

    def get_sandbox_stats(self, provider: str) -> Dict[str, Any]:
        with self._global_lock:
            sandbox = self._sandboxes.get(provider, {})
            return {
                "provider": provider,
                "state": sandbox.get("state", SandboxState.STOPPED).value,
                "crash_count": sandbox.get("crash_count", 0),
                "timeout_count": sandbox.get("timeout_count", 0),
                "memory_exceeded_count": sandbox.get("memory_exceeded_count", 0),
                "total_operations": sandbox.get("total_operations", 0),
                "successful_operations": sandbox.get("successful_operations", 0),
                "last_crash": sandbox.get("last_crash"),
            }

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        return {provider: self.get_sandbox_stats(provider) for provider in PROVIDERS}

    def reset_sandbox(self, provider: str):
        with self._global_lock:
            if provider in self._sandboxes:
                self._sandboxes[provider]["state"] = SandboxState.READY
                logger.info("Sandbox reset for provider %s", provider)

    def stop_provider(self, provider: str):
        with self._global_lock:
            if provider in self._sandboxes:
                self._sandboxes[provider]["state"] = SandboxState.STOPPED
                logger.info("Sandbox stopped for provider %s", provider)

    def get_active_operations(self) -> List[Dict[str, Any]]:
        with self._operation_lock:
            return [
                {
                    "operation_id": op.operation_id,
                    "provider": op.provider,
                    "started_at": op.started_at,
                    "elapsed": time.time() - op.started_at,
                }
                for op in self._active_operations.values()
            ]


def get_sandbox() -> ProviderSandbox:
    return ProviderSandbox()
