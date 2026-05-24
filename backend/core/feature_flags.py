"""
Feature Flags & Safe Deployment Management
=========================================

Enterprise feature flags:
- Staged rollout
- Canary release
- Emergency kill switch
- Tenant-specific rollout
- Rollback orchestration
"""

import hashlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("feature_flags")


class FlagState(Enum):
    DRAFT = "draft"
    ENABLED = "enabled"
    DISABLED = "disabled"
    ROLLING_OUT = "rolling_out"
    ROLLED_BACK = "rolled_back"
    EMERGENCY_KILL = "emergency_kill"


@dataclass
class FeatureFlag:
    """Feature flag"""
    flag_id: str
    name: str
    description: str
    state: FlagState = FlagState.DRAFT
    rollout_percentage: float = 0.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    created_by: str = ""
    target_tenants: List[str] = field(default_factory=list)
    exclude_tenants: List[str] = field(default_factory=list)


@dataclass
class RolloutEvent:
    """Rollout event"""
    event_id: str
    flag_id: str
    tenant_id: str
    event_type: str
    timestamp: float = field(default_factory=time.time)


class FeatureFlagManager:
    """Feature flag management"""

    def __init__(self):
        self._flags: Dict[str, FeatureFlag] = {}
        self._rollout_events: List[RolloutEvent] = []
        self._lock = threading.RLock()
        self._emergency_kill: Set[str] = set()

        logger.info("Feature flag manager initialized")

    def create_flag(self,
                  name: str,
                  description: str,
                  created_by: str = "system") -> str:
        """Create feature flag"""
        flag_id = f"flag_{name.lower().replace(' ', '_')}"

        with self._lock:
            self._flags[flag_id] = FeatureFlag(
                flag_id=flag_id,
                name=name,
                description=description,
                created_by=created_by
            )

        logger.info(f"Feature flag created: {flag_id}")
        return flag_id

    def update_flag(self,
                   flag_id: str,
                   state: Optional[FlagState] = None,
                   rollout_percentage: Optional[float] = None,
                   target_tenants: Optional[List[str]] = None) -> bool:
        """Update feature flag"""
        with self._lock:
            if flag_id not in self._flags:
                return False

            flag = self._flags[flag_id]

            if state:
                flag.state = state
            if rollout_percentage is not None:
                flag.rollout_percentage = rollout_percentage
            if target_tenants:
                flag.target_tenants = target_tenants

            flag.updated_at = time.time()

            return True

    def enable(self, flag_id: str) -> bool:
        """Enable feature flag"""
        return self.update_flag(flag_id, FlagState.ENABLED)

    def disable(self, flag_id: str) -> bool:
        """Disable feature flag"""
        return self.update_flag(flag_id, FlagState.DISABLED)

    def emergency_kill(self, flag_id: str) -> bool:
        """Emergency kill (disable all)"""
        with self._lock:
            self._emergency_kill.add(flag_id)

            if flag_id in self._flags:
                self._flags[flag_id].state = FlagState.EMERGENCY_KILL

            logger.warning(f"Emergency kill: {flag_id}")

            return True

    def clear_emergency_kill(self, flag_id: str) -> bool:
        """Clear emergency kill"""
        with self._lock:
            self._emergency_kill.discard(flag_id)

            if flag_id in self._flags:
                self._flags[flag_id].state = FlagState.ENABLED

            return True

    def is_enabled(self, flag_id: str, tenant_id: str = "") -> bool:
        """Check if feature is enabled for tenant"""
        with self._lock:
            if flag_id in self._emergency_kill:
                return False

            if flag_id not in self._flags:
                return False

            flag = self._flags[flag_id]

            if flag.state == FlagState.EMERGENCY_KILL:
                return False

            if flag.state != FlagState.ENABLED and flag.state != FlagState.ROLLING_OUT:
                return False

            if flag.exclude_tenants and tenant_id in flag.exclude_tenants:
                return False

            if flag.target_tenants:
                return tenant_id in flag.target_tenants

            if flag.state == FlagState.ROLLING_OUT:
                if not tenant_id:
                    return False

                hash_val = int(hashlib.sha256(
                    f"{flag_id}:{tenant_id}".encode()
                ).hexdigest(), 16)

                bucket = (hash_val % 100) + 1
                return bucket <= flag.rollout_percentage

            return True

    def get_flag(self, flag_id: str) -> Optional[FeatureFlag]:
        """Get feature flag"""
        return self._flags.get(flag_id)

    def list_flags(self) -> List[FeatureFlag]:
        """List all flags"""
        return list(self._flags.values())

    def record_rollout(self, flag_id: str, tenant_id: str, event_type: str):
        """Record rollout event"""
        event = RolloutEvent(
            event_id=str(uuid.uuid4()),
            flag_id=flag_id,
            tenant_id=tenant_id,
            event_type=event_type
        )

        with self._lock:
            self._rollout_events.append(event)


class CanaryManager:
    """Canary release management"""

    def __init__(self, flag_manager: FeatureFlagManager):
        self._flags = flag_manager
        self._canary_metrics: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def schedule_rollout(self,
                       flag_id: str,
                       target_percentage: float,
                       step: float = 10.0,
                       interval_seconds: int = 300) -> bool:
        """Schedule gradual rollout"""
        with self._lock:
            flag = self._flags.get_flag(flag_id)
            if not flag:
                return False

            current = flag.rollout_percentage

            while current < target_percentage:
                current = min(current + step, target_percentage)
                self._flags.update_flag(flag_id, rollout_percentage=current)

                logger.info(f"Rollout step: {flag_id} -> {current}%")

            return True

    def record_metric(self, flag_id: str, metric: Dict[str, Any]):
        """Record canary metric"""
        with self._lock:
            if flag_id not in self._canary_metrics:
                self._canary_metrics[flag_id] = []

            self._canary_metrics[flag_id].append({
                **metric,
                "timestamp": time.time()
            })

    def check_canary_health(self, flag_id: str) -> Dict[str, Any]:
        """Check canary health"""
        with self._lock:
            metrics = self._canary_metrics.get(flag_id, [])

            if not metrics:
                return {"status": "unknown"}

            errors = sum(1 for m in metrics if m.get("error"))
            success = sum(1 for m in metrics if m.get("success"))
            total = len(metrics)

            error_rate = errors / max(1, total)

            if error_rate > 0.05:
                return {"status": "unhealthy", "error_rate": error_rate}
            elif error_rate > 0.01:
                return {"status": "degraded", "error_rate": error_rate}
            else:
                return {"status": "healthy", "error_rate": error_rate}


_global_flag_manager: Optional[FeatureFlagManager] = None


def get_feature_flags() -> FeatureFlagManager:
    """Get global feature flag manager"""
    global _global_flag_manager
    if _global_flag_manager is None:
        _global_flag_manager = FeatureFlagManager()
    return _global_flag_manager


__all__ = [
    "FlagState",
    "FeatureFlag",
    "RolloutEvent",
    "FeatureFlagManager",
    "CanaryManager",
    "get_feature_flags"
]
