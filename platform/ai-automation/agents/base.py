"""Base agent interface."""
from __future__ import annotations

import abc
from typing import Any, Dict, Optional


class BaseAgent(abc.ABC):
    agent_type: str = "base"

    @abc.abstractmethod
    async def run(self, task_name: str, input_data: Dict[str, Any],
                  tenant_id: Optional[str] = None) -> Dict[str, Any]:
        pass
