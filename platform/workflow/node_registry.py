"""
WorkflowNodeRegistry — global registry of plugin-contributed workflow nodes.

Plugins register WorkflowNode instances here during startup.
The workflow engine looks up nodes by node_type when executing a workflow.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional

from ..sdk.workflow_sdk import WorkflowNode, NodeHandler

log = logging.getLogger(__name__)


class WorkflowNodeRegistry:
    """Thread-safe singleton registry for all workflow nodes."""

    _instance: Optional["WorkflowNodeRegistry"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "WorkflowNodeRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._nodes: Dict[str, WorkflowNode] = {}   # node_type → WorkflowNode
        self._lock = threading.RLock()

    def register(self, node: WorkflowNode) -> None:
        with self._lock:
            self._nodes[node.node_type] = node
        log.debug("NodeRegistry: registered node_type=%s from plugin=%s", node.node_type, node.plugin_id)

    def register_many(self, nodes: List[WorkflowNode]) -> None:
        for n in nodes:
            self.register(n)

    def deregister_plugin(self, plugin_id: str) -> None:
        with self._lock:
            removed = [k for k, v in self._nodes.items() if v.plugin_id == plugin_id]
            for k in removed:
                del self._nodes[k]
        log.debug("NodeRegistry: deregistered %d node(s) for plugin=%s", len(removed), plugin_id)

    def get(self, node_type: str) -> Optional[WorkflowNode]:
        with self._lock:
            return self._nodes.get(node_type)

    def get_handler(self, node_type: str) -> Optional[NodeHandler]:
        node = self.get(node_type)
        return node.handler if node else None

    def list_nodes(self, plugin_id: Optional[str] = None) -> List[Dict]:
        with self._lock:
            nodes = self._nodes.values()
        if plugin_id:
            nodes = [n for n in nodes if n.plugin_id == plugin_id]
        return [
            {
                "node_type":    n.node_type,
                "label":        n.label,
                "category":     n.category,
                "description":  n.description,
                "plugin_id":    n.plugin_id,
                "icon":         n.icon,
                "input_schema": n.input_schema,
                "output_schema": n.output_schema,
            }
            for n in nodes
        ]
