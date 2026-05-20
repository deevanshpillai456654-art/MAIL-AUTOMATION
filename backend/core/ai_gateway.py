"""Lightweight AI gateway policy.

The gateway is intentionally policy-only: it reports which AI mode is active
and which provider family may be used, without loading local models or running
inference at import time. Heavy AI modules must consult this layer before doing
work.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from backend.core.runtime_control import RuntimeControl, get_runtime_control


class AIGateway:
    def __init__(self, runtime: Optional[RuntimeControl] = None):
        self.runtime = runtime or get_runtime_control()

    def provider_order(self) -> list[str]:
        if not self.runtime.is_ai_enabled():
            return []
        if self.runtime.ai_mode == "lite":
            return ["deterministic", "tiny_local_optional"]
        if self.runtime.ai_mode == "shared":
            return ["shared_office"]
        if self.runtime.ai_mode == "hybrid":
            return ["cloud", "shared_office", "tiny_local_optional"]
        if self.runtime.ai_mode == "cloud":
            return ["cloud"]
        return []

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.runtime.ai_mode,
            "profile": self.runtime.profile,
            "enabled": self.runtime.is_ai_enabled(),
            "offline_mode": self.runtime.offline_mode,
            "low_resource": self.runtime.low_resource,
            "provider_order": self.provider_order(),
            "local_models_loaded": False,
            "always_on_models": False,
            "heavy_local_models_allowed": False,
            "ai_on_demand_only": True,
            "limits": {
                "max_workers": self.runtime.limits["max_workers"],
                "queue_limit": self.runtime.limits["queue_limit"],
            },
        }


def get_ai_gateway(runtime: Optional[RuntimeControl] = None) -> AIGateway:
    return AIGateway(runtime=runtime)


__all__ = ["AIGateway", "get_ai_gateway"]
