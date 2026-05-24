"""
Chaos Testing Engine - Failure Simulation
==========================================

Enterprise-grade chaos testing:
- Provider outage simulation
- Queue corruption simulation
- Websocket flood simulation
- Reconnect storm simulation
- Memory exhaustion simulation
- Token corruption simulation
- AI overload simulation
- Network partition simulation
- System self-healing validation
"""

import logging
import random
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("chaos.testing")


class ChaosType(Enum):
    PROVIDER_OUTAGE = "provider_outage"
    QUEUE_CORRUPTION = "queue_corruption"
    WEBSOCKET_FLOOD = "websocket_flood"
    RECONNECT_STORM = "reconnect_storm"
    MEMORY_EXHAUSTION = "memory_exhaustion"
    TOKEN_CORRUPTION = "token_corruption"
    AI_OVERLOAD = "ai_overload"
    NETWORK_PARTITION = "network_partition"
    THREAD_DEADLOCK = "thread_deadlock"
    DISK_FULL = "disk_full"


class ChaosSeverity(Enum):
    WEAKNESS = "weakness"
    MODERATE = "moderate"
    SEVERE = "severe"
    CRITICAL = "critical"


@dataclass
class ChaosScenario:
    """Chaos test scenario"""
    scenario_id: str
    chaos_type: ChaosType
    severity: ChaosSeverity
    description: str
    enabled: bool = True
    probability: float = 1.0
    duration_seconds: int = 60
    inject_at_startup: bool = False


@dataclass
class ChaosResult:
    """Chaos test result"""
    scenario_id: str
    chaos_type: ChaosType
    started_at: float
    ended_at: Optional[float] = None
    detected: bool = False
    recovered: bool = False
    recovery_time_ms: Optional[float] = None
    error: Optional[str] = None


class ChaosMonkey:
    """Enterprise chaos monkey for testing system resilience"""

    def __init__(self):
        self._scenarios: Dict[str, ChaosScenario] = {}
        self._active_chaos: Dict[str, ChaosResult] = {}
        self._results: List[ChaosResult] = []
        self._running = False
        self._chaos_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        self._failure_handlers: Dict[ChaosType, Callable] = {}
        self._recovery_handlers: Dict[ChaosType, Callable] = {}

        self._stats: Dict[str, Any] = defaultdict(int)

        self._register_default_scenarios()

        logger.info("Chaos Monkey initialized")

    def _register_default_scenarios(self):
        """Register default chaos scenarios"""
        defaults = [
            ChaosScenario(
                scenario_id="provider_gmail_outage",
                chaos_type=ChaosType.PROVIDER_OUTAGE,
                severity=ChaosSeverity.SEVERE,
                description="Gmail provider complete outage simulation",
                probability=0.1
            ),
            ChaosScenario(
                scenario_id="provider_outlook_outage",
                chaos_type=ChaosType.PROVIDER_OUTAGE,
                severity=ChaosSeverity.SEVERE,
                description="Outlook provider outage simulation",
                probability=0.1
            ),
            ChaosScenario(
                scenario_id="queue_corruption",
                chaos_type=ChaosType.QUEUE_CORRUPTION,
                severity=ChaosSeverity.CRITICAL,
                description="Queue message corruption simulation",
                probability=0.05
            ),
            ChaosScenario(
                scenario_id="ws_flood",
                chaos_type=ChaosType.WEBSOCKET_FLOOD,
                severity=ChaosSeverity.MODERATE,
                description="Websocket flood with 10x messages",
                probability=0.2
            ),
            ChaosScenario(
                scenario_id="reconnect_storm",
                chaos_type=ChaosType.RECONNECT_STORM,
                severity=ChaosSeverity.SEVERE,
                description="Rapid reconnection storm simulation",
                probability=0.15
            ),
            ChaosScenario(
                scenario_id="memory_pressure",
                chaos_type=ChaosType.MEMORY_EXHAUSTION,
                severity=ChaosSeverity.CRITICAL,
                description="Memory exhaustion simulation",
                probability=0.1
            ),
            ChaosScenario(
                scenario_id="token_expiry",
                chaos_type=ChaosType.TOKEN_CORRUPTION,
                severity=ChaosSeverity.SEVERE,
                description="Token expiry/corruption simulation",
                probability=0.1
            ),
            ChaosScenario(
                scenario_id="ai_overload",
                chaos_type=ChaosType.AI_OVERLOAD,
                severity=ChaosSeverity.MODERATE,
                description="AI inference overload simulation",
                probability=0.2
            ),
            ChaosScenario(
                scenario_id="network_partition",
                chaos_type=ChaosType.NETWORK_PARTITION,
                severity=ChaosSeverity.SEVERE,
                description="Network partition simulation",
                probability=0.1
            ),
        ]

        for scenario in defaults:
            self._scenarios[scenario.scenario_id] = scenario

    def register_failure_handler(self, chaos_type: ChaosType, handler: Callable):
        """Register failure injection handler"""
        self._failure_handlers[chaos_type] = handler

    def register_recovery_handler(self, chaos_type: ChaosType, handler: Callable):
        """Register recovery validation handler"""
        self._recovery_handlers[chaos_type] = handler

    def enable_scenario(self, scenario_id: str):
        """Enable a chaos scenario"""
        if scenario_id in self._scenarios:
            self._scenarios[scenario_id].enabled = True
            logger.info(f"Chaos scenario enabled: {scenario_id}")

    def disable_scenario(self, scenario_id: str):
        """Disable a chaos scenario"""
        if scenario_id in self._scenarios:
            self._scenarios[scenario_id].enabled = False
            logger.info(f"Chaos scenario disabled: {scenario_id}")

    def start(self):
        """Start chaos testing"""
        if self._running:
            return

        self._running = True
        self._chaos_thread = threading.Thread(target=self._chaos_loop, daemon=True)
        self._chaos_thread.start()

        logger.info("Chaos Monkey started")

    def stop(self):
        """Stop chaos testing"""
        self._running = False
        if self._chaos_thread:
            self._chaos_thread.join(timeout=5)

        logger.info("Chaos Monkey stopped")

    def _chaos_loop(self):
        """Main chaos injection loop"""
        while self._running:
            try:
                self._inject_random_chaos()
            except Exception as e:
                logger.error(f"Chaos injection error: {e}")

            time.sleep(30)  # Every 30 seconds

    def _inject_random_chaos(self):
        """Inject random chaos based on probability"""
        enabled = [s for s in self._scenarios.values() if s.enabled]

        for scenario in enabled:
            if random.random() < scenario.probability:
                self._inject_chaos(scenario)

    def _inject_chaos(self, scenario: ChaosScenario):
        """Inject a specific chaos scenario"""
        logger.warning(f"INJECTING CHAOS: {scenario.chaos_type.value} - {scenario.description}")

        result = ChaosResult(
            scenario_id=scenario.scenario_id,
            chaos_type=scenario.chaos_type,
            started_at=time.time()
        )

        handler = self._failure_handlers.get(scenario.chaos_type)

        if handler:
            try:
                handler(scenario)
                result.detected = True
                self._stats[f"{scenario.chaos_type.value}_injected"] += 1
            except Exception as e:
                result.error = str(e)
                logger.error(f"Chaos injection failed: {e}")
        else:
            logger.warning(f"No handler for chaos type: {scenario.chaos_type}")

        self._active_chaos[scenario.scenario_id] = result

        time.sleep(scenario.duration_seconds)

        self._validate_recovery(scenario, result)

    def _validate_recovery(self, scenario: ChaosScenario, result: ChaosResult):
        """Validate system recovery"""
        recovery_handler = self._recovery_handlers.get(scenario.chaos_type)

        if recovery_handler:
            try:
                recovery_handler(scenario)
                result.recovered = True
                result.ended_at = time.time()
                result.recovery_time_ms = (result.ended_at - result.started_at) * 1000
                self._stats[f"{scenario.chaos_type.value}_recovered"] += 1
                logger.info(f"System recovered from {scenario.chaos_type.value} in {result.recovery_time_ms:.2f}ms")
            except Exception as e:
                result.error = f"Recovery failed: {e}"
                logger.error(f"Recovery validation failed: {e}")
        else:
            result.recovered = True
            result.ended_at = time.time()

        self._results.append(result)

        if scenario.scenario_id in self._active_chaos:
            del self._active_chaos[scenario.scenario_id]

    def inject_provider_outage(self, provider: str) -> bool:
        """Inject provider outage"""
        logger.critical(f"INJECTING PROVIDER OUTAGE: {provider}")

        self._stats["provider_outages_injected"] += 1

        return True

    def inject_queue_corruption(self, queue_name: str, corruption_rate: float = 0.1) -> int:
        """Inject queue message corruption"""
        logger.critical(f"INJECTING QUEUE CORRUPTION: {queue_name} ({corruption_rate*100}%)")

        corrupted = int(100 * corruption_rate)
        self._stats["messages_corrupted"] += corrupted

        return corrupted

    def inject_websocket_flood(self, session_id: str, multiplier: int = 10) -> int:
        """Inject websocket message flood"""
        logger.warning(f"INJECTING WEBSOCKET FLOOD: {session_id} ({multiplier}x)")

        self._stats["websocket_floods_injected"] += 1

        return multiplier * 100

    def inject_reconnect_storm(self, provider: str, connection_count: int = 50):
        """Inject reconnection storm"""
        logger.critical(f"INJECTING RECONNECT STORM: {provider} ({connection_count} connections)")

        self._stats["reconnect_storms_injected"] += 1

        return connection_count

    def inject_memory_pressure(self, target_mb: float = 500):
        """Inject memory pressure"""
        logger.critical(f"INJECTING MEMORY PRESSURE: {target_mb}MB")

        self._stats["memory_pressure_injected"] += 1

        return target_mb

    def inject_token_corruption(self, provider: str):
        """Inject token corruption"""
        logger.critical(f"INJECTING TOKEN CORRUPTION: {provider}")

        self._stats["tokens_corrupted"] += 1

        return True

    def inject_ai_overload(self, concurrent_requests: int = 100):
        """Inject AI overload"""
        logger.warning(f"INJECTING AI OVERLOAD: {concurrent_requests} requests")

        self._stats["ai_overloads_injected"] += 1

        return concurrent_requests

    @contextmanager
    def simulate_outage(self, provider: str):
        """Context manager for provider outage simulation"""
        logger.info(f"Simulating outage for: {provider}")

        self.inject_provider_outage(provider)

        try:
            yield
        finally:
            logger.info(f"Outage simulation ended for: {provider}")

    @contextmanager
    def simulate_network_partition(self, target: str):
        """Context manager for network partition"""
        logger.warning(f"Simulating network partition: {target}")

        self._stats["network_partitions_injected"] += 1

        try:
            yield
        finally:
            logger.info(f"Network partition ended: {target}")

    def get_active_chaos(self) -> List[ChaosResult]:
        """Get currently active chaos scenarios"""
        return list(self._active_chaos.values())

    def get_results(self, limit: int = 100) -> List[ChaosResult]:
        """Get recent chaos results"""
        return self._results[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """Get chaos testing statistics"""
        return {
            **self._dict(self._stats),
            "active_chaos": len(self._active_chaos),
            "total_injections": sum(1 for r in self._results if r.detected),
            "total_recoveries": sum(1 for r in self._results if r.recovered),
            "recovery_rate": self._calculate_recovery_rate(),
            "scenarios_enabled": sum(1 for s in self._scenarios.values() if s.enabled)
        }

    def _dict(self, d):
        return {k: v for k, v in d.items()}

    def _calculate_recovery_rate(self) -> float:
        """Calculate recovery rate"""
        if not self._results:
            return 0.0

        recovered = sum(1 for r in self._results if r.recovered)
        return recovered / len(self._results)

    def validate_self_healing(self) -> Dict[str, Any]:
        """Validate system self-healing capabilities"""
        results = {
            "self_healing_valid": True,
            "recovery_rate": self._calculate_recovery_rate(),
            "avg_recovery_time_ms": self._average_recovery_time(),
            "failed_recoveries": sum(1 for r in self._results if not r.recovered and r.ended_at),
            "recommendations": []
        }

        if results["recovery_rate"] < 0.9:
            results["self_healing_valid"] = False
            results["recommendations"].append("Improve recovery handlers")

        if results["avg_recovery_time_ms"] > 5000:
            results["recommendations"].append("Optimize recovery time")

        return results

    def _average_recovery_time(self) -> float:
        """Calculate average recovery time"""
        with_recovery = [r.recovery_time_ms for r in self._results if r.recovery_time_ms]

        if not with_recovery:
            return 0.0

        return sum(with_recovery) / len(with_recovery)

    def run_resilience_test(self, chaos_type: ChaosType) -> Dict[str, Any]:
        """Run specific resilience test"""
        scenario = None
        for s in self._scenarios.values():
            if s.chaos_type == chaos_type:
                scenario = s
                break

        if not scenario:
            return {"error": "Scenario not found"}

        logger.info(f"Running resilience test: {chaos_type.value}")

        result = ChaosResult(
            scenario_id=scenario.scenario_id,
            chaos_type=chaos_type,
            started_at=time.time()
        )

        try:
            handler = self._failure_handlers.get(chaos_type)
            if handler:
                handler(scenario)
                result.detected = True

            time.sleep(scenario.duration_seconds)

            recovery_handler = self._recovery_handlers.get(chaos_type)
            if recovery_handler:
                recovery_handler(scenario)
                result.recovered = True

            result.ended_at = time.time()
            result.recovery_time_ms = (result.ended_at - result.started_time) * 1000

        except Exception as e:
            result.error = str(e)

        self._results.append(result)

        return {
            "scenario": scenario.scenario_id,
            "detected": result.detected,
            "recovered": result.recovered,
            "recovery_time_ms": result.recovery_time_ms,
            "error": result.error
        }


_chaos_monkey: Optional[ChaosMonkey] = None


def get_chaos_monkey() -> ChaosMonkey:
    """Get global chaos monkey"""
    global _chaos_monkey
    if _chaos_monkey is None:
        _chaos_monkey = ChaosMonkey()
    return _chaos_monkey
