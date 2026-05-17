"""Platform UI Extensions — dynamic sidebar, widget, and route injection."""
from .extension_registry import UIExtensionRegistry, SidebarItem, UIWidget, UIRoute
from .router             import ui_extension_router

__all__ = [
    "UIExtensionRegistry",
    "SidebarItem",
    "UIWidget",
    "UIRoute",
    "ui_extension_router",
]
