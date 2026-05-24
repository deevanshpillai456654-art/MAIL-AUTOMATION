"""
Startup Orchestrator - Parallel startup with degraded mode support

Features:
- Dependency graph-based startup
- Parallel component initialization
- Partial availability mode
- Degraded startup mode
- Startup retries
- Startup diagnostics
"""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("startup.orchestrator")


class StartupState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    DEGRADED = "degraded"
    TIMEOUT = "timeout"


class DependencyLevel(Enum):
    FOUNDATION = 0   # Port, config, logging
    CORE = 1         # Database, event bus
    SERVICES = 2     # Providers, auth
    APPLICATION = 3 # Sync, AI
    UI = 4           # Dashboard, extensions


@dataclass
class StartupComponent:
    """A component that needs to start"""
    name: str
    level: DependencyLevel
    dependencies: List[str] = field(default_factory=list)
    start_func: Optional[Callable] = None
    health_check_func: Optional[Callable] = None
    timeout: float = 30.0
    retry_count: int = 3
    retry_delay: float = 2.0

    state: StartupState = StartupState.PENDING
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    attempt_count: int = 0


@dataclass
class StartupReport:
    """Report of startup process"""
    total_components: int
    successful: int
    failed: int
    degraded: int
    total_time: float
    components: Dict[str, StartupState]
    errors: Dict[str, str]


class StartupOrchestrator:
    """
    Enterprise startup orchestrator with parallel initialization.
    
    Features:
    - Dependency graph resolution
    - Parallel startup where possible
    - Degraded mode for partial failures
    - Health checks after startup
    - Startup diagnostics
    """

    def __init__(self, max_workers: int = 8):
        self.max_workers = max_workers
        self._components: Dict[str, StartupComponent] = {}
        self._level_map: Dict[DependencyLevel, List[str]] = {}
        self._lock = threading.RLock()

        # Callbacks
        self._on_component_start: Optional[Callable] = None
        self._on_component_success: Optional[Callable] = None
        self._on_component_failure: Optional[Callable] = None

        logger.info("Startup orchestrator initialized")

    def register_component(
        self,
        name: str,
        level: DependencyLevel,
        dependencies: List[str] = None,
        start_func: Callable = None,
        health_check: Callable = None,
        timeout: float = 30.0,
        retry_count: int = 3
    ):
        """Register a component for startup"""
        with self._lock:
            component = StartupComponent(
                name=name,
                level=level,
                dependencies=dependencies or [],
                start_func=start_func,
                health_check_func=health_check,
                timeout=timeout,
                retry_count=retry_count
            )

            self._components[name] = component

            # Add to level map
            if level not in self._level_map:
                self._level_map[level] = []
            self._level_map[level].append(name)

            logger.info(f"Registered component: {name} at level {level.name}")

    def _resolve_dependencies(self) -> bool:
        """Validate dependency graph"""
        with self._lock:
            for name, component in self._components.items():
                for dep in component.dependencies:
                    if dep not in self._components:
                        logger.error(f"Component {name} depends on unknown: {dep}")
                        return False
            return True

    def _can_start(self, component: StartupComponent) -> bool:
        """Check if all dependencies are satisfied"""
        for dep_name in component.dependencies:
            dep = self._components.get(dep_name)
            if not dep or dep.state != StartupState.SUCCESS:
                return False
        return True

    async def start(self, degraded_mode: bool = True) -> StartupReport:
        """
        Start all registered components.
        
        Args:
            degraded_mode: If True, continue even if some components fail
        """
        start_time = time.time()

        # Validate dependencies
        if not self._resolve_dependencies():
            return self._create_error_report("Dependency validation failed")

        # Sort levels
        levels = sorted(self._level_map.keys(), key=lambda x: x.value)

        results = {}
        failed_components = []

        # Start each level
        for level in levels:
            component_names = self._level_map[level]
            logger.info(f"Starting level {level.name} with {len(component_names)} components")

            # Start components in this level in parallel
            level_results = await self._start_level_parallel(component_names)

            results.update(level_results)

            # Check for failures
            for name, state in level_results.items():
                if state == StartupState.FAILED:
                    failed_components.append(name)

            # If critical components failed and not in degraded mode, stop
            critical_failed = any(
                self._components[name].level.value <= DependencyLevel.CORE.value
                for name in failed_components
                if name in self._components
            )

            if critical_failed and not degraded_mode:
                logger.error("Critical component failed, stopping startup")
                break

        # Calculate results
        total = len(self._components)
        successful = sum(1 for s in results.values() if s == StartupState.SUCCESS)
        failed = sum(1 for s in results.values() if s == StartupState.FAILED)
        degraded = sum(1 for s in results.values() if s == StartupState.DEGRADED)

        # Get errors
        errors = {
            name: comp.error
            for name, comp in self._components.items()
            if comp.error
        }

        report = StartupReport(
            total_components=total,
            successful=successful,
            failed=failed,
            degraded=degraded,
            total_time=time.time() - start_time,
            components=results,
            errors=errors
        )

        logger.info(f"Startup complete: {successful}/{total} successful, {failed} failed, {degraded} degraded")

        return report

    async def _start_level_parallel(self, component_names: List[str]) -> Dict[str, StartupState]:
        """Start components in a level in parallel"""
        results = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._start_component, name): name
                for name in component_names
            }

            for future in as_completed(futures):
                name = futures[future]
                try:
                    state = future.result()
                    results[name] = state
                except Exception as e:
                    logger.error(f"Failed to start {name}: {e}")
                    results[name] = StartupState.FAILED

        return results

    def _start_component(self, name: str) -> StartupState:
        """Start a single component with retries"""
        component = self._components[name]
        component.state = StartupState.RUNNING
        component.start_time = time.time()

        if self._on_component_start:
            self._on_component_start(name)

        # Retry loop
        for attempt in range(component.retry_count + 1):
            component.attempt_count = attempt + 1

            try:
                # Start the component
                if component.start_func:
                    if asyncio.iscoroutinefunction(component.start_func):
                        # Run async in new event loop
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(component.start_func())
                        finally:
                            loop.close()
                    else:
                        component.start_func()

                # Check health
                if component.health_check_func:
                    if not component.health_check_func():
                        raise Exception("Health check failed")

                # Success
                component.state = StartupState.SUCCESS
                component.end_time = time.time()

                if self._on_component_success:
                    self._on_component_success(name)

                logger.info(f"Component {name} started successfully (attempt {attempt + 1})")
                return StartupState.SUCCESS

            except Exception as e:
                error_msg = str(e)
                component.error = error_msg
                logger.warning(f"Component {name} start attempt {attempt + 1} failed: {error_msg}")

                if attempt < component.retry_count:
                    time.sleep(component.retry_delay)

        # All retries exhausted
        component.state = StartupState.FAILED
        component.end_time = time.time()

        if self._on_component_failure:
            self._on_component_failure(name, component.error)

        logger.error(f"Component {name} failed after {component.retry_count + 1} attempts")

        return StartupState.FAILED

    def _create_error_report(self, error_msg: str) -> StartupReport:
        """Create an error report"""
        return StartupReport(
            total_components=len(self._components),
            successful=0,
            failed=len(self._components),
            degraded=0,
            total_time=0,
            components={name: StartupState.FAILED for name in self._components},
            errors={name: error_msg for name in self._components}
        )

    def get_status(self) -> Dict:
        """Get current startup status"""
        with self._lock:
            return {
                name: {
                    "state": comp.state.value,
                    "level": comp.level.name,
                    "error": comp.error,
                    "attempts": comp.attempt_count
                }
                for name, comp in self._components.items()
            }

    def retry_failed(self, component_name: str) -> bool:
        """Retry a failed component"""
        component = self._components.get(component_name)
        if not component:
            return False

        component.state = StartupState.PENDING
        component.error = None

        # Re-run
        self._start_component(component_name)

        return component.state == StartupState.SUCCESS


# Global instance
startup_orchestrator = StartupOrchestrator()
