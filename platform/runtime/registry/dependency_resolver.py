"""
DependencyResolver — resolves plugin load order based on declared dependencies.

Plugins declare dependencies in plugin.json::

    {
      "plugin_id": "erp_invoice",
      "depends_on": ["crm_contacts", "xero"]
    }

The resolver returns a topological sort so plugins are started in the
correct order and stopped in reverse.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Dict, List, Optional, Set

log = logging.getLogger(__name__)


class DependencyResolver:
    """
    Topological sort (Kahn's algorithm) for plugin dependency graphs.
    Raises on circular dependencies.
    """

    def __init__(self) -> None:
        self._deps: Dict[str, List[str]] = {}

    def add(self, plugin_id: str, depends_on: Optional[List[str]] = None) -> None:
        self._deps[plugin_id] = depends_on or []

    def add_many(self, plugins: Dict[str, List[str]]) -> None:
        for pid, deps in plugins.items():
            self.add(pid, deps)

    def resolve_load_order(self) -> List[str]:
        """Return plugin IDs in dependency-safe load order (topological sort)."""
        # Build in-degree and adjacency
        in_degree: Dict[str, int] = {pid: 0 for pid in self._deps}
        graph: Dict[str, List[str]] = defaultdict(list)

        for pid, deps in self._deps.items():
            for dep in deps:
                if dep not in in_degree:
                    in_degree[dep] = 0
                graph[dep].append(pid)
                in_degree[pid] = in_degree.get(pid, 0) + 1

        # All nodes
        all_nodes = set(self._deps.keys()) | {
            dep for deps in self._deps.values() for dep in deps
        }
        for node in all_nodes:
            if node not in in_degree:
                in_degree[node] = 0

        queue = deque(sorted(n for n, d in in_degree.items() if d == 0))
        order: List[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbour in sorted(graph[node]):
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        if len(order) != len(all_nodes):
            cycle_nodes = {n for n, d in in_degree.items() if d > 0}
            raise RuntimeError(f"Circular dependency detected among plugins: {cycle_nodes}")

        # Only return nodes that were registered with add()
        known = set(self._deps.keys())
        return [n for n in order if n in known]

    def resolve_stop_order(self) -> List[str]:
        """Return stop order (reverse of load order)."""
        return list(reversed(self.resolve_load_order()))

    def validate(self, plugin_id: str) -> List[str]:
        """Return list of missing dependencies for *plugin_id*."""
        registered = set(self._deps.keys())
        return [d for d in self._deps.get(plugin_id, []) if d not in registered]
