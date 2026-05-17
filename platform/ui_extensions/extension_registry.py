"""
UIExtensionRegistry — plugin-contributed UI contributions registry.

Plugins register:
  - sidebar items   (nav links)
  - widgets         (dashboard cards / embedded panels)
  - routes          (full page views accessible via the client router)
  - settings pages  (per-plugin config UI)

The registry is read by the frontend extension loader on page load or
after a plugin hot-reload notification.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SidebarItem:
    plugin_id:  str
    item_id:    str
    label:      str
    icon:       str = ""
    route:      str = ""          # frontend route to navigate to
    order:      int = 100
    permissions: List[str] = field(default_factory=list)   # required roles


@dataclass
class UIWidget:
    plugin_id:    str
    widget_id:    str
    label:        str
    component:    str    # JS component name / import path
    placement:    str = "dashboard"  # dashboard | connector-detail | global
    min_width:    int = 3            # grid columns (1–12)
    permissions:  List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UIRoute:
    plugin_id:  str
    route_id:   str
    path:       str          # e.g. "/plugins/salesforce/contacts"
    component:  str          # JS component path
    label:      str = ""
    icon:       str = ""
    permissions: List[str] = field(default_factory=list)


class UIExtensionRegistry:
    """Thread-safe singleton for all plugin UI contributions."""

    _instance: Optional["UIExtensionRegistry"] = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "UIExtensionRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._sidebar: Dict[str, List[SidebarItem]] = {}
        self._widgets: Dict[str, List[UIWidget]]    = {}
        self._routes:  Dict[str, List[UIRoute]]     = {}
        self._lock     = threading.RLock()

    # ── Registration ──────────────────────────────────────────────────────

    def register_sidebar_item(self, item: SidebarItem) -> None:
        with self._lock:
            self._sidebar.setdefault(item.plugin_id, []).append(item)

    def register_widget(self, widget: UIWidget) -> None:
        with self._lock:
            self._widgets.setdefault(widget.plugin_id, []).append(widget)

    def register_route(self, route: UIRoute) -> None:
        with self._lock:
            self._routes.setdefault(route.plugin_id, []).append(route)

    def deregister_plugin(self, plugin_id: str) -> None:
        with self._lock:
            self._sidebar.pop(plugin_id, None)
            self._widgets.pop(plugin_id, None)
            self._routes.pop(plugin_id, None)

    # ── Query ─────────────────────────────────────────────────────────────

    def get_sidebar_items(self, tenant_id: Optional[str] = None) -> List[Dict]:
        with self._lock:
            items = [i for lst in self._sidebar.values() for i in lst]
        items.sort(key=lambda i: i.order)
        return [
            {
                "plugin_id":   i.plugin_id,
                "item_id":     i.item_id,
                "label":       i.label,
                "icon":        i.icon,
                "route":       i.route,
                "permissions": i.permissions,
            }
            for i in items
        ]

    def get_widgets(self, placement: Optional[str] = None) -> List[Dict]:
        with self._lock:
            widgets = [w for lst in self._widgets.values() for w in lst]
        if placement:
            widgets = [w for w in widgets if w.placement == placement]
        return [
            {
                "plugin_id":    w.plugin_id,
                "widget_id":    w.widget_id,
                "label":        w.label,
                "component":    w.component,
                "placement":    w.placement,
                "min_width":    w.min_width,
                "permissions":  w.permissions,
                "config_schema": w.config_schema,
            }
            for w in widgets
        ]

    def get_routes(self) -> List[Dict]:
        with self._lock:
            routes = [r for lst in self._routes.values() for r in lst]
        return [
            {
                "plugin_id":   r.plugin_id,
                "route_id":    r.route_id,
                "path":        r.path,
                "component":   r.component,
                "label":       r.label,
                "permissions": r.permissions,
            }
            for r in routes
        ]

    def manifest(self) -> Dict[str, Any]:
        """Full UI manifest — serialised to JSON and sent to the frontend."""
        return {
            "sidebar": self.get_sidebar_items(),
            "widgets": self.get_widgets(),
            "routes":  self.get_routes(),
        }
