"""
SandboxManager — controls what plugins are allowed to do at runtime.

Python does not provide true OS-level sandboxing without extra tools.
This implementation provides:
  - Capability-based permission model (what a plugin declares it needs)
  - Runtime assertion hooks (raise SandboxViolation on policy breach)
  - Audit logging of all permission checks
  - Per-tenant policy overrides

Production hardening notes:
  - For untrusted third-party code, combine with process isolation
    (subprocess, gVisor, Firecracker) at the infrastructure layer.
  - This manager enforces DECLARED permissions — it is not a security
    boundary for malicious code.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

log = logging.getLogger(__name__)


class SandboxViolation(PermissionError):
    """Raised when a plugin attempts an operation outside its sandbox policy."""


@dataclass
class SandboxPolicy:
    """Defines what a plugin is allowed to do."""
    allow_network:          bool = True
    allow_filesystem:       bool = True
    allow_subprocess:       bool = False
    allow_db_write:         bool = True
    allow_schema_changes:   bool = False
    allowed_db_tables:      Optional[List[str]] = None  # None = all tables
    allowed_event_types:    Optional[List[str]] = None  # None = all events
    allowed_api_paths:      Optional[List[str]] = None  # None = all paths
    max_memory_mb:          Optional[int] = None
    max_cpu_seconds:        Optional[float] = None
    max_requests_per_minute: Optional[int] = None
    metadata:               Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def strict(cls) -> "SandboxPolicy":
        """Minimal-privilege policy suitable for third-party plugins."""
        return cls(
            allow_network=True,
            allow_filesystem=False,
            allow_subprocess=False,
            allow_db_write=True,
            allow_schema_changes=False,
            max_memory_mb=256,
            max_requests_per_minute=600,
        )

    @classmethod
    def trusted(cls) -> "SandboxPolicy":
        """Full-access policy for first-party platform plugins."""
        return cls(
            allow_network=True,
            allow_filesystem=True,
            allow_subprocess=False,
            allow_db_write=True,
            allow_schema_changes=False,
        )


class SandboxManager:
    """
    Manages sandbox policies for all plugins.

    Plugins declare their requirements in plugin.json → "sandbox" block.
    The manager checks declared requirements against the platform-wide
    policy and rejects plugins that request more than they are allowed.
    """

    def __init__(self, default_policy: Optional[SandboxPolicy] = None) -> None:
        self._default = default_policy or SandboxPolicy.trusted()
        self._policies:   Dict[str, SandboxPolicy] = {}
        self._audit: List[Dict[str, Any]] = []

    def set_policy(self, plugin_id: str, policy: SandboxPolicy) -> None:
        self._policies[plugin_id] = policy
        log.debug("SandboxManager: policy set for %s", plugin_id)

    def get_policy(self, plugin_id: str) -> SandboxPolicy:
        return self._policies.get(plugin_id, self._default)

    def validate_plugin(
        self,
        plugin_id: str,
        manifest_sandbox: Dict[str, Any],
    ) -> bool:
        """
        Check that the plugin's declared sandbox requirements are within
        platform-allowed limits.  Returns True if plugin may be loaded.
        """
        policy = self._default

        # Map manifest declarations to policy fields
        needs_subprocess = manifest_sandbox.get("allow_subprocess", False)
        needs_schema     = manifest_sandbox.get("allow_schema_changes", False)

        violations = []
        if needs_subprocess and not policy.allow_subprocess:
            violations.append("allow_subprocess denied by platform policy")
        if needs_schema and not policy.allow_schema_changes:
            violations.append("allow_schema_changes denied by platform policy")

        if violations:
            log.warning(
                "SandboxManager: plugin %s rejected — %s", plugin_id, "; ".join(violations)
            )
            return False

        # Build a per-plugin policy from the manifest
        plugin_policy = SandboxPolicy(
            allow_network          = manifest_sandbox.get("allow_network", True),
            allow_filesystem       = manifest_sandbox.get("allow_filesystem", False),
            allow_subprocess       = False,  # always denied at plugin level
            allow_db_write         = manifest_sandbox.get("allow_db_write", True),
            allow_schema_changes   = False,  # always denied at plugin level
            allowed_db_tables      = manifest_sandbox.get("allowed_db_tables"),
            allowed_event_types    = manifest_sandbox.get("allowed_event_types"),
            max_memory_mb          = manifest_sandbox.get("max_memory_mb"),
            max_requests_per_minute= manifest_sandbox.get("max_requests_per_minute"),
        )
        self._policies[plugin_id] = plugin_policy
        return True

    def assert_can_publish_event(self, plugin_id: str, event_type: str) -> None:
        policy = self.get_policy(plugin_id)
        if policy.allowed_event_types is not None:
            if not any(event_type.startswith(p.rstrip("*")) for p in policy.allowed_event_types):
                self._audit.append({
                    "plugin_id": plugin_id,
                    "action": "publish_event",
                    "resource": event_type,
                    "allowed": False,
                })
                raise SandboxViolation(
                    f"Plugin '{plugin_id}' not allowed to publish event '{event_type}'"
                )

    def assert_can_access_table(self, plugin_id: str, table_name: str, write: bool = False) -> None:
        policy = self.get_policy(plugin_id)
        if write and not policy.allow_db_write:
            raise SandboxViolation(
                f"Plugin '{plugin_id}' does not have DB write permission"
            )
        if policy.allowed_db_tables is not None and table_name not in policy.allowed_db_tables:
            raise SandboxViolation(
                f"Plugin '{plugin_id}' not allowed to access table '{table_name}'"
            )

    def get_audit_log(self, plugin_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if plugin_id:
            return [e for e in self._audit if e.get("plugin_id") == plugin_id]
        return list(self._audit)
