"""
Self-Healing Orchestrator - Phase 18 Enterprise Upgrade
======================================================

Comprehensive self-healing orchestrator:
- DependencyGraphManager
- CascadingFailureDetector
- AutoRestartEngine
- DegradedModeController
- DynamicThrottlingEngine
- HealthBasedOrchestrator
- SelfHealingRecoveryEngine
- AutomaticProviderIsolation
- AdaptiveWorkerScaling
- OrchestrationAPIs
"""

import logging
import sqlite3
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set

from backend import config

logger = logging.getLogger("orchestrator.self_healing")


class ComponentState(Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    RESTARTING = "restarting"
    ISOLATED = "isolated"
    RECOVERING = "recovering"


class HealthLevel(Enum):
    UNKNOWN = "unknown"
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"


class DegradationLevel(Enum):
    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


class ThrottleType(Enum):
    NONE = "none"
    LOAD = "load"
    RESOURCE = "resource"
    PROVIDER = "provider"
    MANUAL = "manual"


@dataclass
class Component:
    name: str
    component_type: str
    dependencies: List[str]
    state: ComponentState = ComponentState.UNKNOWN
    health: HealthLevel = HealthLevel.UNKNOWN
    restart_count: int = 0
    last_restart: float = 0
    last_health_check: float = 0
    health_score: float = 1.0
    metadata: Dict = field(default_factory=dict)
    health_check_func: Optional[Callable] = None
    restart_func: Optional[Callable] = None


@dataclass
class HealthCheck:
    component_name: str
    timestamp: float
    is_healthy: bool
    health_score: float
    error: Optional[str]
    metrics: Dict = field(default_factory=dict)


@dataclass
class RecoveryAction:
    action_id: str
    component_name: str
    action_type: str
    target_state: ComponentState
    details: Dict
    executed_at: Optional[float] = None
    result: Optional[str] = None
    success: bool = False


@dataclass
class CascadeEvent:
    root_cause: str
    affected_components: List[str]
    timestamp: float
    resolved: bool = False
    blast_radius: float = 0.0
    impact_score: float = 0.0


@dataclass
class ThrottleConfig:
    throttle_type: ThrottleType
    threshold: float
    current_factor: float = 1.0
    cooldown: float = 30.0
    last_throttle: float = 0


@dataclass
class WorkerPool:
    name: str
    min_workers: int = 1
    max_workers: int = 10
    current_workers: int = 1
    active_tasks: int = 0
    queue_size: int = 0
    scale_cooldown: float = 60.0
    last_scale: float = 0
    target_utilization: float = 0.7
    enable_scale_to_zero: bool = False


class DependencyGraphManager:
    """System component dependency graph management"""

    def __init__(self):
        self._components: Dict[str, Component] = {}
        self._adjacency: Dict[str, Set[str]] = defaultdict(set)
        self._reverse_adjacency: Dict[str, Set[str]] = defaultdict(set)

    def add_component(self, component: Component):
        self._components[component.name] = component
        for dep in component.dependencies:
            self._reverse_adjacency[component.name].add(dep)
            self._adjacency[dep].add(component.name)

    def get_component(self, name: str) -> Optional[Component]:
        return self._components.get(name)

    def get_dependencies(self, name: str) -> Set[str]:
        return self._reverse_adjacency.get(name, set())

    def get_dependents(self, name: str) -> Set[str]:
        return self._adjacency.get(name, set())

    def get_all_dependents(self, name: str) -> Set[str]:
        result = set()
        to_visit = list(self.get_dependents(name))
        while to_visit:
            comp = to_visit.pop()
            if comp not in result:
                result.add(comp)
                to_visit.extend(self.get_dependents(comp))
        return result

    def get_all_dependencies(self, name: str) -> Set[str]:
        result = set()
        to_visit = list(self.get_dependencies(name))
        while to_visit:
            comp = to_visit.pop()
            if comp not in result:
                result.add(comp)
                to_visit.extend(self.get_dependencies(comp))
        return result

    def detect_circular(self) -> Optional[List[str]]:
        visited = set()
        rec_stack = set()
        path = []

        def dfs(node: str) -> Optional[List[str]]:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self.get_dependencies(node):
                if neighbor not in visited:
                    result = dfs(neighbor)
                    if result:
                        return result
                elif neighbor in rec_stack:
                    return path[path.index(neighbor):] + [neighbor]

            path.pop()
            rec_stack.remove(node)
            return None

        for component in self._components:
            if component not in visited:
                cycle = dfs(component)
                if cycle:
                    return cycle
        return None

    def topological_sort_startup(self) -> List[str]:
        in_degree = defaultdict(int)
        for comp in self._components:
            for dep in self.get_dependencies(comp):
                if dep in self._components:
                    in_degree[comp] += 1

        result = []
        queue = [c for c in self._components if in_degree[c] == 0]

        while queue:
            comp = queue.pop(0)
            result.append(comp)
            for dependent in self.get_dependents(comp):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        return result

    def topological_sort_shutdown(self) -> List[str]:
        return list(reversed(self.topological_sort_startup()))

    def calculate_health_score(self, name: str) -> float:
        component = self.get_component(name)
        if not component:
            return 0.0
        if component.state == ComponentState.HEALTHY:
            return component.health_score
        return 0.0

    def get_dependency_health(self, name: str) -> float:
        deps = self.get_all_dependencies(name)
        if not deps:
            return 1.0
        scores = [self.calculate_health_score(d) for d in deps if d in self._components]
        return statistics.mean(scores) if scores else 1.0

    def calculate_blast_radius(self, failed_component: str) -> float:
        affected = self.get_all_dependents(failed_component)
        total = len(self._components)
        if total == 0:
            return 0.0
        return len(affected) / total


class CascadingFailureDetector:
    """Cascading failure tracking and prevention"""

    def __init__(self):
        self._cascade_history: deque = deque(maxlen=100)
        self._failure_graph: Dict[str, List[str]] = defaultdict(list)
        self._root_causes: Dict[str, str] = {}
        self._prevention_rules: Dict[str, List[str]] = {}

    def register_prevention_rule(self, failure_point: str, prevention_actions: List[str]):
        self._prevention_rules[failure_point] = prevention_actions

    def detect_cascade(self, graph: DependencyGraphManager, failed_component: str) -> CascadeEvent:
        affected = list(graph.get_all_dependents(failed_component))
        blast_radius = graph.calculate_blast_radius(failed_component)

        impact_score = 0.0
        for comp_name in affected:
            comp = graph.get_component(comp_name)
            if comp:
                impact_score += (1.0 - comp.health_score)

        event = CascadeEvent(
            root_cause=failed_component,
            affected_components=affected,
            timestamp=time.time(),
            blast_radius=blast_radius,
            impact_score=impact_score
        )

        self._cascade_history.append(event)
        self._failure_graph[failed_component] = affected

        return event

    def predict_cascade(self, graph: DependencyGraphManager, potential_failure: str) -> float:
        if graph.get_component(potential_failure):
            deps = graph.get_all_dependents(potential_failure)
            critical_deps = [d for d in deps if graph.get_component(d) and
                          graph.get_component(d).health_score < 0.5]
            return len(critical_deps) / max(len(deps), 1)
        return 0.0

    def get_prevention_actions(self, failure_point: str) -> List[str]:
        return self._prevention_rules.get(failure_point, [])

    def get_recent_cascades(self, limit: int = 10) -> List[Dict]:
        return [
            {
                "root_cause": e.root_cause,
                "affected": e.affected_components,
                "timestamp": e.timestamp,
                "resolved": e.resolved,
                "blast_radius": e.blast_radius
            }
            for e in list(self._cascade_history)[-limit:]
        ]


class AutoRestartEngine:
    """Component auto-restart management"""

    def __init__(self):
        self._restart_cooldowns: Dict[str, float] = {}
        self._restart_history: deque = deque(maxlen=500)
        self._config = {
            "max_restart_attempts": 3,
            "restart_cooldown": 60.0,
            "restart_timeout": 30.0
        }

    def configure(self, max_attempts: int = 3, cooldown: float = 60.0, timeout: float = 30.0):
        self._config["max_restart_attempts"] = max_attempts
        self._config["restart_cooldown"] = cooldown
        self._config["restart_timeout"] = timeout

    def can_restart(self, component: Component) -> bool:
        if component.restart_count >= self._config["max_restart_attempts"]:
            return False
        if time.time() - component.last_restart < self._config["restart_cooldown"]:
            return False
        return True

    def execute_restart(self, component: Component) -> bool:
        if not self.can_restart(component):
            return False

        component.state = ComponentState.RESTARTING
        restart_success = False

        try:
            if component.restart_func:
                restart_success = component.restart_func()
            else:
                time.sleep(0.1)
                restart_success = True

            if restart_success:
                component.state = ComponentState.HEALTHY
                component.health = HealthLevel.GOOD
                component.health_score = 1.0
            else:
                component.state = ComponentState.FAILED

            component.restart_count += 1
            component.last_restart = time.time()

            self._restart_history.append({
                "component": component.name,
                "timestamp": time.time(),
                "success": restart_success,
                "attempt": component.restart_count
            })

            return restart_success

        except Exception as e:
            logger.error(f"Restart failed for {component.name}: {e}")
            component.state = ComponentState.FAILED
            component.restart_count += 1
            return False

    def get_restart_stats(self, component_name: str) -> Dict:
        history = [h for h in self._restart_history if h["component"] == component_name]
        if not history:
            return {"total": 0, "successes": 0, "failures": 0}

        return {
            "total": len(history),
            "successes": sum(1 for h in history if h["success"]),
            "failures": sum(1 for h in history if not h["success"]),
            "last_restart": history[-1]["timestamp"] if history else None
        }


class DegradedModeController:
    """Degraded mode management"""

    def __init__(self):
        self._degradation_level = DegradationLevel.NONE
        self._enabled_features: Set[str] = set()
        self._disabled_features: Set[str] = set()
        self._degradation_reason: Optional[str] = None
        self._degradation_start: float = 0
        self._feature_flags: Dict[str, bool] = {}

    def enter_degraded_mode(self, level: DegradationLevel, reason: str):
        self._degradation_level = level
        self._degradation_reason = reason
        self._degradation_start = time.time()
        logger.warning(f"Entering degraded mode ({level.value}): {reason}")

    def exit_degraded_mode(self):
        logger.info("Exiting degraded mode")
        self._degradation_level = DegradationLevel.NONE
        self._degradation_reason = None

    def set_feature_enabled(self, feature: str, enabled: bool):
        if enabled:
            self._enabled_features.add(feature)
            self._disabled_features.discard(feature)
        else:
            self._disabled_features.add(feature)
            self._enabled_features.discard(feature)
        self._feature_flags[feature] = enabled

    def is_feature_enabled(self, feature: str) -> bool:
        if self._degradation_level != DegradationLevel.NONE:
            if feature in self._disabled_features:
                return False
        return self._feature_flags.get(feature, True)

    def get_degradation_status(self) -> Dict:
        return {
            "level": self._degradation_level.value,
            "reason": self._degradation_reason,
            "duration": time.time() - self._degradation_start if self._degradation_start else 0,
            "enabled_features": list(self._enabled_features),
            "disabled_features": list(self._disabled_features)
        }

    def should_reduce_feature(self, feature: str) -> bool:
        if self._degradation_level in [DegradationLevel.SEVERE, DegradationLevel.CRITICAL]:
            return feature in self._disabled_features
        return False


class DynamicThrottlingEngine:
    """Dynamic load and resource throttling"""

    def __init__(self):
        self._throttle_configs: Dict[str, ThrottleConfig] = {}
        self._throttle_history: deque = deque(maxlen=1000)
        self._current_global_factor = 1.0

    def register_throttle(self, name: str, throttle_type: ThrottleType,
                         threshold: float, cooldown: float = 30.0):
        self._throttle_configs[name] = ThrottleConfig(
            throttle_type=throttle_type,
            threshold=threshold,
            cooldown=cooldown
        )

    def apply_throttle(self, name: str, utilization: float) -> float:
        config = self._throttle_configs.get(name)
        if not config:
            return 1.0

        now = time.time()
        if now - config.last_throttle < config.cooldown:
            return config.current_factor

        if utilization > config.threshold:
            config.current_factor = max(0.1, config.current_factor - 0.1)
            config.last_throttle = now
            self._throttle_history.append({
                "name": name, "timestamp": now, "factor": config.current_factor
            })
        elif utilization < config.threshold * 0.5:
            config.current_factor = min(1.0, config.current_factor + 0.05)
            config.last_throttle = now

        return config.current_factor

    def apply_global_throttle(self, resource_type: str, current_value: float,
                           threshold: float) -> float:
        if current_value > threshold:
            factor = max(0.2, 1.0 - (current_value - threshold) / threshold)
            self._current_global_factor = factor
            self._throttle_history.append({
                "type": resource_type, "timestamp": time.time(),
                "factor": factor, "value": current_value
            })
            return factor
        return 1.0

    def get_current_throttle(self, name: str) -> float:
        config = self._throttle_configs.get(name)
        return config.current_factor if config else 1.0


class HealthBasedOrchestrator:
    """Health-based routing and scaling"""

    def __init__(self):
        self._health_weights: Dict[str, float] = {}
        self._aggregate_health: float = 1.0

    def register_component_weight(self, component_name: str, weight: float):
        self._health_weights[component_name] = weight

    def calculate_weighted_health(self, components: Dict[str, Component]) -> float:
        if not components:
            return 1.0

        total_weight = sum(self._health_weights.get(c, 1.0) for c in components)
        weighted_score = sum(
            components[c].health_score * self._health_weights.get(c, 1.0)
            for c in components
        )

        self._aggregate_health = weighted_score / total_weight if total_weight > 0 else 0.0
        return self._aggregate_health

    def should_failover(self, component_name: str, threshold: float = 0.3) -> bool:
        return self._aggregate_health < threshold

    def get_health_report(self) -> Dict:
        return {
            "aggregate_health": self._aggregate_health,
            "component_weights": self._health_weights
        }


class SelfHealingRecoveryEngine:
    """Recovery playbook execution"""

    def __init__(self):
        self._playbooks: Dict[str, Callable] = {}
        self._recovery_history: deque = deque(maxlen=500)
        self._recovery_times: Dict[str, List[float]] = defaultdict(list)
        self._automation_level = "full"

    def register_playbook(self, failure_type: str, recovery_func: Callable):
        self._playbooks[failure_type] = recovery_func

    def execute_playbook(self, failure_type: str, context: Dict) -> bool:
        playbook = self._playbooks.get(failure_type)
        if not playbook:
            logger.warning(f"No playbook for {failure_type}")
            return False

        start_time = time.time()
        try:
            result = playbook(context)
            recovery_time = time.time() - start_time

            self._recovery_history.append({
                "type": failure_type, "timestamp": start_time,
                "success": result, "duration": recovery_time
            })
            self._recovery_times[failure_type].append(recovery_time)

            return result

        except Exception as e:
            logger.error(f"Playbook execution failed for {failure_type}: {e}")
            return False

    def get_recovery_stats(self, failure_type: str = None) -> Dict:
        if failure_type:
            times = self._recovery_times.get(failure_type, [])
            if not times:
                return {"count": 0, "avg_time": 0}
            return {
                "count": len(times),
                "avg_time": statistics.mean(times),
                "min_time": min(times),
                "max_time": max(times)
            }

        all_types = defaultdict(lambda: {"success": 0, "total": 0})
        for rec in self._recovery_history:
            all_types[rec["type"]]["total"] += 1
            if rec["success"]:
                all_types[rec["type"]]["success"] += 1

        return {
            "failure_types": {
                t: {"success": v["success"], "total": v["total"]}
                for t, v in all_types.items()
            }
        }

    def set_automation_level(self, level: str):
        self._automation_level = level


class AutomaticProviderIsolation:
    """Provider health-based isolation"""

    def __init__(self):
        self._provider_states: Dict[str, str] = {}
        self._isolation_rules: Dict[str, Dict] = {}
        self._isolation_history: deque = deque(maxlen=100)

    def register_provider(self, provider: str, isolation_config: Dict = None):
        self._provider_states[provider] = "active"
        if isolation_config:
            self._isolation_rules[provider] = isolation_config

    def isolate_provider(self, provider: str, isolation_type: str = "full") -> bool:
        if provider not in self._provider_states:
            return False

        self._provider_states[provider] = isolation_type
        self._isolation_history.append({
            "provider": provider, "isolation_type": isolation_type,
            "timestamp": time.time()
        })
        logger.warning(f"Provider {provider} isolated ({isolation_type})")
        return True

    def release_provider(self, provider: str) -> bool:
        if provider not in self._provider_states:
            return False

        self._provider_states[provider] = "active"
        logger.info(f"Provider {provider} released from isolation")
        return True

    def should_isolate(self, provider: str, error_rate: float,
                     error_threshold: float = 0.3) -> bool:
        if provider in self._isolation_rules:
            config = self._isolation_rules[provider]
            return error_rate > config.get("error_threshold", error_threshold)
        return error_rate > error_threshold

    def get_provider_state(self, provider: str) -> str:
        return self._provider_states.get(provider, "unknown")

    def get_isolation_report(self) -> Dict:
        return {
            provider: state for provider, state in self._provider_states.items()
        }


class AdaptiveWorkerScaling:
    """Worker pool adaptive scaling"""

    def __init__(self):
        self._pools: Dict[str, WorkerPool] = {}
        self._scale_history: deque = deque(maxlen=500)

    def register_pool(self, name: str, min_workers: int = 1, max_workers: int = 10,
                  enable_scale_to_zero: bool = False):
        pool = WorkerPool(
            name=name, min_workers=min_workers, max_workers=max_workers,
            current_workers=min_workers, enable_scale_to_zero=enable_scale_to_zero
        )
        self._pools[name] = pool

    def scale_pool(self, pool_name: str, queue_size: int = None,
                target_utilization: float = 0.7) -> int:
        pool = self._pools.get(pool_name)
        if not pool:
            return 0

        if queue_size is not None:
            pool.queue_size = queue_size

        now = time.time()
        if now - pool.last_scale < pool.scale_cooldown:
            return pool.current_workers

        utilization = pool.active_tasks / pool.current_workers if pool.current_workers > 0 else 0

        if pool.queue_size > pool.current_workers * 5 or utilization > pool.target_utilization:
            new_workers = min(pool.current_workers + 1, pool.max_workers)
            if new_workers != pool.current_workers:
                pool.current_workers = new_workers
                pool.last_scale = now
                self._scale_history.append({
                    "pool": pool_name, "workers": new_workers, "timestamp": now, "reason": "scale_up"
                })

        elif utilization < pool.target_utilization * 0.3 and pool.queue_size == 0:
            if pool.enable_scale_to_zero:
                new_workers = 0
            else:
                new_workers = max(pool.current_workers - 1, pool.min_workers)

            if new_workers != pool.current_workers:
                pool.current_workers = new_workers
                pool.last_scale = now
                self._scale_history.append({
                    "pool": pool_name, "workers": new_workers, "timestamp": now, "reason": "scale_down"
                })

        return pool.current_workers

    def get_pool_status(self, pool_name: str) -> Optional[Dict]:
        pool = self._pools.get(pool_name)
        if not pool:
            return None

        return {
            "name": pool.name,
            "current_workers": pool.current_workers,
            "active_tasks": pool.active_tasks,
            "queue_size": pool.queue_size,
            "last_scale": pool.last_scale
        }


class SelfHealingOrchestrator:
    """Main self-healing orchestrator"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(Path(config.DATA_DIR) / "orchestrator.db")
        self._init_db()

        self.graph = DependencyGraphManager()
        self.cascade_detector = CascadingFailureDetector()
        self.auto_restart = AutoRestartEngine()
        self.degraded_controller = DegradedModeController()
        self.throttling = DynamicThrottlingEngine()
        self.health_orchestrator = HealthBasedOrchestrator()
        self.recovery_engine = SelfHealingRecoveryEngine()
        self.provider_isolation = AutomaticProviderIsolation()
        self.worker_scaling = AdaptiveWorkerScaling()

        self._health_checks: Dict[str, Callable] = {}
        self._running = False
        self._monitor_thread = None
        self._lock = threading.RLock()

        self.health_check_interval = 30
        self._started = False

        self._init_default_components()
        self._register_default_throttles()
        logger.info("SelfHealingOrchestrator initialized")

    def _init_db(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS component_state (
                name TEXT PRIMARY KEY, component_type TEXT,
                dependencies TEXT, state TEXT, health TEXT,
                restart_count INTEGER, last_restart REAL,
                health_score REAL, metadata TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS health_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                component_name TEXT NOT NULL, timestamp REAL NOT NULL,
                is_healthy INTEGER, health_score REAL, error TEXT, metrics TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recovery_actions (
                action_id TEXT PRIMARY KEY, component_name TEXT NOT NULL,
                action_type TEXT NOT NULL, target_state TEXT,
                details TEXT, executed_at REAL, result TEXT, success INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cascade_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                root_cause TEXT NOT NULL, affected_components TEXT,
                timestamp REAL NOT NULL, resolved INTEGER DEFAULT 0,
                blast_radius REAL, impact_score REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orchestrator_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL, metric_type TEXT,
                metric_value REAL
            )
        """)

        conn.commit()
        conn.close()

    def _init_default_components(self):
        defaults = [
            ("database", "storage", []),
            ("event_store", "storage", ["database"]),
            ("event_bus", "messaging", ["database"]),
            ("resource_manager", "system", []),
            ("provider_isolator", "provider", []),
            ("sync_engine", "sync", ["database", "provider_isolator"]),
            ("ai_classifier", "ai", ["database"]),
            ("oauth_manager", "auth", []),
            ("websocket", "realtime", ["event_bus"]),
            ("scheduler", "scheduler", ["database"]),
            ("policy_engine", "policy", ["database"]),
        ]

        for name, comp_type, deps in defaults:
            self.register_component(name, comp_type, deps)

    def _register_default_throttles(self):
        self.throttling.register_throttle("load", ThrottleType.LOAD, 0.8)
        self.throttling.register_throttle("memory", ThrottleType.RESOURCE, 0.85)
        self.throttling.register_throttle("cpu", ThrottleType.RESOURCE, 0.9)

    def register_component(self, name: str, component_type: str,
                        dependencies: List[str] = None):
        component = Component(
            name=name, component_type=component_type,
            dependencies=dependencies or [], state=ComponentState.UNKNOWN
        )
        self.graph.add_component(component)
        logger.info(f"Component registered: {name}")

    def register_health_check(self, component_name: str, health_check: Callable):
        self._health_checks[component_name] = health_check
        comp = self.graph.get_component(component_name)
        if comp:
            comp.health_check_func = health_check

    def register_restart_func(self, component_name: str, restart_func: Callable):
        comp = self.graph.get_component(component_name)
        if comp:
            comp.restart_func = restart_func

    def register_worker_pool(self, name: str, min_workers: int = 1,
                          max_workers: int = 10, enable_scale_to_zero: bool = False):
        self.worker_scaling.register_pool(name, min_workers, max_workers, enable_scale_to_zero)

    def start(self):
        if self._started:
            return

        self._started = True
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

        logger.info("SelfHealingOrchestrator started")

    def stop(self):
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        self._started = False
        logger.info("SelfHealingOrchestrator stopped")

    def _monitor_loop(self):
        while self._running:
            try:
                self._run_health_checks()
                self._detect_and_handle_failures()
                self._execute_recovery()
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

            time.sleep(self.health_check_interval)

    def _run_health_checks(self):
        for name, check in self._health_checks.items():
            try:
                result = check()
                if isinstance(result, tuple):
                    is_healthy, health_score = result[0], result[1]
                else:
                    is_healthy, health_score = result, 1.0 if result else 0.0

                self._update_component_health(name, is_healthy, health_score)

            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                self._update_component_health(name, False, 0.0, str(e))

    def _update_component_health(self, name: str, is_healthy: bool,
                          health_score: float = 1.0, error: str = None):
        comp = self.graph.get_component(name)
        if not comp:
            return

        comp.last_health_check = time.time()
        comp.health_score = health_score

        if is_healthy:
            if health_score >= 0.7:
                comp.state = ComponentState.HEALTHY
                comp.health = HealthLevel.GOOD
            elif health_score >= 0.4:
                comp.state = ComponentState.DEGRADED
                comp.health = HealthLevel.FAIR
            else:
                comp.state = ComponentState.DEGRADED
                comp.health = HealthLevel.POOR
        else:
            comp.state = ComponentState.FAILED
            comp.health = HealthLevel.CRITICAL

    def _detect_and_handle_failures(self):
        for name, comp in self.graph._components.items():
            if comp.state == ComponentState.FAILED:
                event = self.cascade_detector.detect_cascade(self.graph, name)
                if event.blast_radius > 0.3:
                    self.degraded_controller.enter_degraded_mode(
                        DegradationLevel.MODERATE,
                        f"Cascade from {name}"
                    )

                if comp.restart_count < self.auto_restart._config["max_restart_attempts"]:
                    if self.auto_restart.can_restart(comp):
                        self.auto_restart.execute_restart(comp)

    def _execute_recovery(self):
        for name, comp in self.graph._components.items():
            if comp.state == ComponentState.ISOLATED:
                pass

    def get_status(self) -> Dict:
        total = len(self.graph._components)
        healthy = sum(1 for c in self.graph._components.values()
                    if c.state == ComponentState.HEALTHY)
        degraded = sum(1 for c in self.graph._components.values()
                      if c.state == ComponentState.DEGRADED)
        failed = sum(1 for c in self.graph._components.values()
                   if c.state == ComponentState.FAILED)

        system_score = statistics.mean(
            c.health_score for c in self.graph._components.values()
        ) if total > 0 else 0

        return {
            "running": self._started,
            "system_health": "healthy" if system_score > 0.7 else "degraded" if system_score > 0.4 else "critical",
            "system_score": system_score,
            "components": {
                "total": total, "healthy": healthy,
                "degraded": degraded, "failed": failed
            },
            "degraded_mode": self.degraded_controller.get_degradation_status(),
            "throttle_factor": self.throttling._current_global_factor
        }

    def get_dependency_graph(self) -> List[Dict]:
        result = []
        for name, comp in self.graph._components.items():
            result.append({
                "name": comp.name,
                "type": comp.component_type,
                "dependencies": list(comp.dependencies),
                "dependents": list(self.graph.get_dependents(name))
            })
        return result

    def restart_component(self, component_name: str) -> bool:
        comp = self.graph.get_component(component_name)
        if not comp:
            return False
        return self.auto_restart.execute_restart(comp)

    def enter_degraded_mode(self, reason: str):
        self.degraded_controller.enter_degraded_mode(DegradationLevel.MODERATE, reason)

    def get_metrics(self) -> Dict:
        return {
            "system": self.get_status(),
            "recovery_stats": self.recovery_engine.get_recovery_stats(),
            "worker_pools": {
                name: self.worker_scaling.get_pool_status(name)
                for name in self.worker_scaling._pools
            },
            "throttling": {
                name: config.current_factor
                for name, config in self.throttling._throttle_configs.items()
            }
        }

    def scale_worker_pool(self, pool_name: str, workers: int) -> bool:
        pool = self.worker_scaling._pools.get(pool_name)
        if not pool:
            return False
        pool.current_workers = min(max(workers, pool.min_workers), pool.max_workers)
        return True


_orchestrator: Optional[SelfHealingOrchestrator] = None


def get_orchestrator() -> SelfHealingOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = SelfHealingOrchestrator()
    return _orchestrator
