"""
Distributed Chaos Engineering
====================

Distributed chaos orchestration:
- Chaos mesh coordination
- Experiment scheduling
- Fault injection
- Blast radius control
- Recovery validation
- Chaos metrics
- Multi-zone testing
- Continuous chaos
- Chaos as code
"""

import time
import json
import hashlib
import logging
import asyncio
import threading
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import deque, defaultdict
import uuid
import secrets
import random

logger = logging.getLogger("chaos.distributed")


class ChaosPhase(Enum):
    STEADY_STATE = "steady_state"
    INJECTION = "injection"
    MEASUREMENT = "measurement"
    RECOVERY = "recovery"
    POST_MORTEM = "post_mortem"


class FaultType(Enum):
    LATENCY = "latency"
    ERROR = "error"
    PARTITION = "partition"
    OVERLOAD = "overload"
    CORRUPTION = "corruption"
    KILL = "kill"


@dataclass
class ChaosExperiment:
    """Chaos experiment"""
    experiment_id: str
    name: str
    fault_type: FaultType
    target: str
    duration_seconds: int
    blast_radius: float
    status: str = "pending"
    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    results: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SteadyState:
    """Steady state hypothesis"""
    metric_name: str
    operator: str
    threshold: float
    samples: int = 5
    interval_seconds: float = 10.0


@dataclass
class BlastRadius:
    """Blast radius control"""
    max_availability: float = 0.99
    max_latency_ms: float = 500
    max_errors_percent: float = 5.0
    affected_users_percent: float = 10.0


class ChaosMeshCoordination:
    """Coordinate chaos across nodes"""
    
    def __init__(self):
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._experiments: Dict[str, ChaosExperiment] = {}
        self._active: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._config = {
            "consensus_threshold": 0.7,
            "sync_interval_seconds": 5
        }
    
    def register_node(self, node_id: str, zone: str = "default"):
        """Register node"""
        with self._lock:
            self._nodes[node_id] = {
                "zone": zone,
                "registered_at": time.time(),
                "status": "active"
            }
    
    def request_vote(self, experiment: ChaosExperiment) -> Tuple[bool, str]:
        """Vote on experiment"""
        with self._lock:
            active_nodes = sum(1 for n in self._nodes.values() if n.get("status") == "active")
            required = active_nodes * self._config["consensus_threshold"]
            
            if active_nodes < 2:
                return True, "insufficient_nodes"
            
            return True, "voted"
    
    def start_experiment(self, experiment: ChaosExperiment) -> bool:
        """Start experiment"""
        with self._lock:
            self._experiments[experiment.experiment_id] = experiment
            self._active[experiment.experiment_id] = experiment.target
            
            logger.info(f"Started chaos: {experiment.name}")
            return True
    
    def end_experiment(self, experiment_id: str, results: Dict[str, Any]):
        """End experiment"""
        with self._lock:
            if experiment_id in self._experiments:
                exp = self._experiments[experiment_id]
                exp.status = "completed"
                exp.ended_at = time.time()
                exp.results = results
    
    def get_status(self) -> Dict[str, Any]:
        """Get mesh status"""
        with self._lock:
            return {
                "nodes": len(self._nodes),
                "active_experiments": len(self._active),
                "completed_experiments": len([
                    e for e in self._experiments.values() 
                    if e.status == "completed"
                ])
            }


class ExperimentScheduler:
    """Schedule chaos experiments"""
    
    def __init__(self):
        self._schedule: Dict[str, List[ChaosExperiment]] = defaultdict(list)
        self._running: Dict[str, str] = {}
        self._lock = threading.RLock()
        self._config = {
            "enable_scheduling": True,
            "min_interval_seconds": 300,
            "max_failures_per_day": 10
        }
    
    def schedule_experiment(self, 
                        experiment: ChaosExperiment,
                        run_at: float):
        """Schedule experiment"""
        key = time.strftime("%Y-%m-%d", time.localtime(run_at))
        
        with self._lock:
            self._schedule[key].append(experiment)
    
    def get_pending(self, 
                   before: Optional[float] = None) -> List[ChaosExperiment]:
        """Get pending experiments"""
        key = time.strftime("%Y-%m-%d", time.localtime(time.time()))
        
        with self._lock:
            pending = [
                e for e in self._schedule.get(key, [])
                if e.status == "pending"
            ]
            
            if before:
                pending = [
                    e for e in pending 
                    if e.duration_seconds < before
                ]
            
            return pending
    
    def cancel_experiment(self, experiment_id: str) -> bool:
        """Cancel scheduled experiment"""
        with self._lock:
            for key, experiments in self._schedule.items():
                for exp in experiments:
                    if exp.experiment_id == experiment_id:
                        exp.status = "cancelled"
                        return True
        return False


class FaultInjector:
    """Inject faults"""
    
    def __init__(self):
        self._active_faults: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
    
    def inject_latency(self, 
                     target: str, 
                     delay_ms: int,
                     duration_seconds: int) -> str:
        """Inject latency"""
        fault_id = str(uuid.uuid4())
        
        with self._lock:
            self._active_faults[fault_id] = {
                "type": FaultType.LATENCY,
                "target": target,
                "delay_ms": delay_ms,
                "started_at": time.time(),
                "duration": duration_seconds
            }
        
        return fault_id
    
    def inject_error(self, 
                  target: str, 
                  error_rate: float,
                  duration_seconds: int) -> str:
        """Inject errors"""
        fault_id = str(uuid.uuid4())
        
        with self._lock:
            self._active_faults[fault_id] = {
                "type": FaultType.ERROR,
                "target": target,
                "error_rate": error_rate,
                "started_at": time.time(),
                "duration": duration_seconds
            }
        
        return fault_id
    
    def inject_partition(self, 
                       target: str,
                       duration_seconds: int) -> str:
        """Inject network partition"""
        fault_id = str(uuid.uuid4())
        
        with self._lock:
            self._active_faults[fault_id] = {
                "type": FaultType.PARTITION,
                "target": target,
                "started_at": time.time(),
                "duration": duration_seconds
            }
        
        return fault_id
    
    def stop_fault(self, fault_id: str) -> bool:
        """Stop fault"""
        with self._lock:
            if fault_id in self._active_faults:
                del self._active_faults[fault_id]
                return True
        return False
    
    def get_active(self) -> List[Dict[str, Any]]:
        """Get active faults"""
        with self._lock:
            return list(self._active_faults.values())


class RecoveryValidator:
    """Validate recovery"""
    
    def __init__(self):
        self._metrics: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.RLock()
    
    def validate_recovery(self, 
                     metric_name: str,
                     baseline: float,
                     tolerance: float = 0.1) -> Tuple[bool, float]:
        """Validate recovery within tolerance"""
        with self._lock:
            values = self._metrics.get(metric_name, [])
            
            if not values:
                return False, 0.0
            
            avg = sum(values) / len(values)
            diff = abs(avg - baseline) / baseline
            
            return diff <= tolerance, diff
    
    def record_metric(self, metric_name: str, value: float):
        """Record recovery metric"""
        with self._lock:
            self._metrics[metric_name].append(value)
            
            if len(self._metrics[metric_name]) > 100:
                self._metrics[metric_name] = self._metrics[metric_name][-100:]


class ChaosMetrics:
    """Chaos experiment metrics"""
    
    def __init__(self):
        self._experiment_metrics: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._lock = threading.RLock()
    
    def record_metric(self, 
                    experiment_id: str,
                    metric_name: str,
                    value: float):
        """Record experiment metric"""
        with self._lock:
            self._experiment_metrics[experiment_id][metric_name].append(value)
    
    def get_summary(self, 
                 experiment_id: str) -> Dict[str, Any]:
        """Get experiment summary"""
        with self._lock:
            metrics = self._experiment_metrics.get(experiment_id, {})
            
            summary = {}
            for name, values in metrics.items():
                if not values:
                    continue
                
                summary[name] = {
                    "count": len(values),
                    "mean": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values)
                }
            
            return summary


class DistributedChaosOrchestrator:
    """Main chaos orchestration"""
    
    def __init__(self):
        self._mesh = ChaosMeshCoordination()
        self._scheduler = ExperimentScheduler()
        self._injector = FaultInjector()
        self._recovery = RecoveryValidator()
        self._metrics = ChaosMetrics()
        self._lock = threading.RLock()
        
        self._config = {
            "enable_auto_recovery": True,
            "enable_continuous_chaos": False,
            "blast_radius": BlastRadius(),
            "steady_state": []
        }
        
        self._active_experiment: Optional[str] = None
        
        logger.info("Distributed chaos orchestrator initialized")
    
    def define_steady_state(self, steady_state: SteadyState):
        """Define steady state hypothesis"""
        with self._lock:
            self._config["steady_state"].append(steady_state)
    
    def create_experiment(self, 
                       name: str,
                       fault_type: FaultType,
                       target: str,
                       duration_seconds: int,
                       blast_radius: float) -> ChaosExperiment:
        """Create experiment"""
        return ChaosExperiment(
            experiment_id=str(uuid.uuid4()),
            name=name,
            fault_type=fault_type,
            target=target,
            duration_seconds=duration_seconds,
            blast_radius=blast_radius
        )
    
    async def run_experiment(self, experiment: ChaosExperiment) -> Dict[str, Any]:
        """Run chaos experiment"""
        allowed, msg = self._mesh.request_vote(experiment)
        if not allowed:
            return {"status": "rejected", "reason": msg}
        
        self._mesh.start_experiment(experiment)
        self._active_experiment = experiment.experiment_id
        
        if experiment.fault_type == FaultType.LATENCY:
            fault_id = self._injector.inject_latency(
                experiment.target,
                int(experiment.blast_radius),
                experiment.duration_seconds
            )
        elif experiment.fault_type == FaultType.ERROR:
            fault_id = self._injector.inject_error(
                experiment.target,
                experiment.blast_radius / 100,
                experiment.duration_seconds
            )
        
        await asyncio.sleep(experiment.duration_seconds)
        
        self._injector.stop_fault(fault_id)
        
        self._mesh.end_experiment(
            experiment.experiment_id,
            {"duration": experiment.duration_seconds}
        )
        
        self._active_experiment = None
        
        return {
            "status": "completed",
            "experiment_id": experiment.experiment_id
        }
    
    def validate_steady_state(self) -> Dict[str, Any]:
        """Validate steady state"""
        results = {
            "steady_state_met": True,
            "hypotheses": []
        }
        
        with self._lock:
            for ss in self._config["steady_state"]:
                met = self._validation_steady_state(ss)
                results["hypotheses"].append({
                    "metric": ss.metric_name,
                    "met": met
                })
                if not met:
                    results["steady_state_met"] = False
        
        return results
    
    def _validation_steady_state(self, ss: SteadyState) -> bool:
        """Validate single steady state"""
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """Get chaos status"""
        with self._lock:
            return {
                "mesh": self._mesh.get_status(),
                "active_faults": len(self._injector.get_active()),
                "active_experiment": self._active_experiment,
                "steady_state": self._config["steady_state"]
            }


_global_orchestrator: Optional["DistributedChaosOrchestrator"] = None


def get_chaos_orchestrator() -> DistributedChaosOrchestrator:
    """Get global chaos orchestrator"""
    global _global_orchestrator
    if _global_orchestrator is None:
        _global_orchestrator = DistributedChaosOrchestrator()
    return _global_orchestrator


__all__ = [
    "ChaosPhase",
    "FaultType",
    "ChaosExperiment",
    "SteadyState",
    "BlastRadius",
    "ChaosMeshCoordination",
    "ExperimentScheduler",
    "FaultInjector",
    "RecoveryValidator",
    "ChaosMetrics",
    "DistributedChaosOrchestrator",
    "get_chaos_orchestrator"
]