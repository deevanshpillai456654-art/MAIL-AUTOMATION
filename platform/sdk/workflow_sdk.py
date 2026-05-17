"""
WorkflowSDK — workflow node registration and trigger API for plugins.

Usage::

    sdk = WorkflowSDK(context)

    # Register a node type this plugin provides
    @sdk.node("fetch_contacts", label="Fetch Contacts", category="CRM")
    async def fetch_contacts(inputs, ctx):
        ...

    # Trigger a workflow by workflow_id
    run_id = await sdk.trigger("wf_abc123", {"contact_id": "C1"})
    result = await sdk.wait_for(run_id, timeout=30)

    # Subscribe to workflow events
    sdk.on_completion("wf_abc123", handle_done)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

log = logging.getLogger(__name__)

NodeHandler = Callable[[Dict[str, Any], Any], Coroutine[Any, Any, Dict[str, Any]]]


@dataclass
class WorkflowNode:
    """Descriptor for a workflow node contributed by a plugin."""
    node_type:    str
    label:        str
    category:     str
    description:  str = ""
    icon:         str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    handler:      Optional[NodeHandler] = field(default=None, repr=False)
    plugin_id:    str = ""


class WorkflowSDK:
    """
    Workflow node registration and execution trigger API for plugins.

    Node registration is local to the SDK instance; the runtime loader
    calls get_nodes() during plugin startup and registers them with the
    global WorkflowNodeRegistry.
    """

    def __init__(self, context: Any) -> None:
        self._ctx   = context
        self._nodes: List[WorkflowNode] = []

    @property
    def _engine(self) -> Optional[Any]:
        return getattr(self._ctx, "workflow_engine", None)

    def _plugin_id(self) -> str:
        return getattr(self._ctx, "plugin_id", "unknown")

    def _tenant_id(self) -> str:
        return getattr(self._ctx, "tenant_id", "__system__")

    # ── Node Registration ─────────────────────────────────────────────────

    def node(
        self,
        node_type: str,
        *,
        label: str,
        category: str = "General",
        description: str = "",
        icon: str = "",
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
    ):
        """Decorator that registers an async function as a workflow node."""
        def decorator(fn: NodeHandler) -> NodeHandler:
            wn = WorkflowNode(
                node_type=node_type,
                label=label,
                category=category,
                description=description,
                icon=icon,
                input_schema=input_schema or {},
                output_schema=output_schema or {},
                handler=fn,
                plugin_id=self._plugin_id(),
            )
            self._nodes.append(wn)
            return fn
        return decorator

    def register_node(self, wn: WorkflowNode) -> None:
        """Programmatically register a WorkflowNode descriptor."""
        if not wn.plugin_id:
            wn.plugin_id = self._plugin_id()
        self._nodes.append(wn)

    def get_nodes(self) -> List[WorkflowNode]:
        """Return all nodes registered on this SDK instance."""
        return list(self._nodes)

    # ── Trigger & Control ─────────────────────────────────────────────────

    async def trigger(
        self,
        workflow_id: str,
        inputs: Optional[Dict[str, Any]] = None,
        *,
        tenant_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Start a workflow run and return the run_id.
        Returns None if no workflow engine is available.
        """
        if not self._engine:
            log.warning("WorkflowSDK: no workflow engine available")
            return None
        tid = tenant_id or self._tenant_id()
        return await self._engine.trigger(
            workflow_id,
            inputs=inputs or {},
            tenant_id=tid,
            triggered_by=self._plugin_id(),
            correlation_id=correlation_id,
        )

    async def wait_for(
        self,
        run_id: str,
        *,
        timeout: float = 60.0,
    ) -> Optional[Dict[str, Any]]:
        """
        Wait for a workflow run to complete. Returns the run result dict.
        Returns None on timeout or if engine is absent.
        """
        if not self._engine:
            return None
        try:
            return await asyncio.wait_for(
                self._engine.await_run(run_id), timeout=timeout
            )
        except asyncio.TimeoutError:
            log.warning("WorkflowSDK.wait_for: timeout waiting for run %s", run_id)
            return None

    async def cancel(self, run_id: str) -> bool:
        """Cancel a running workflow. Returns True if cancelled."""
        if not self._engine:
            return False
        return await self._engine.cancel(run_id)

    def get_run_status(self, run_id: str) -> Optional[str]:
        """Return the current status string of a workflow run."""
        if not self._engine:
            return None
        return self._engine.get_status(run_id)

    # ── Event hooks ───────────────────────────────────────────────────────

    def on_completion(
        self,
        workflow_id: str,
        handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """Subscribe to completion events for a specific workflow."""
        if self._engine and hasattr(self._engine, "on_completion"):
            self._engine.on_completion(
                workflow_id,
                handler,
                tenant_id=self._tenant_id(),
            )

    def on_failure(
        self,
        workflow_id: str,
        handler: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """Subscribe to failure events for a specific workflow."""
        if self._engine and hasattr(self._engine, "on_failure"):
            self._engine.on_failure(
                workflow_id,
                handler,
                tenant_id=self._tenant_id(),
            )
