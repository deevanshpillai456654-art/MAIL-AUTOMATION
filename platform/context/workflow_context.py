"""WorkflowContext — context object threaded through workflow node execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class WorkflowContext:
    run_id:      str
    workflow_id: str
    tenant_id:   str
    step_id:     str       = ""
    inputs:      Dict[str, Any] = field(default_factory=dict)
    variables:   Dict[str, Any] = field(default_factory=dict)
    correlation_id: Optional[str] = None

    def get(self, key: str, default: Any = None) -> Any:
        return self.variables.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.variables[key] = value
