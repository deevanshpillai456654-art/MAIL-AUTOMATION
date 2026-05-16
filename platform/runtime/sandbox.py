from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List

@dataclass
class SandboxPolicy:
    allow_network: bool = False
    allow_filesystem: bool = True
    allowed_paths: List[str] = field(default_factory=lambda: ["/platform"])
    max_runtime_seconds: int = 60
    metadata: Dict[str, str] = field(default_factory=dict)

class SandboxIsolation:
    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self.policy = policy or SandboxPolicy()

    def validate_path(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.policy.allowed_paths)

    def describe(self) -> dict:
        return {
            "allow_network": self.policy.allow_network,
            "allow_filesystem": self.policy.allow_filesystem,
            "allowed_paths": self.policy.allowed_paths,
            "max_runtime_seconds": self.policy.max_runtime_seconds,
        }
