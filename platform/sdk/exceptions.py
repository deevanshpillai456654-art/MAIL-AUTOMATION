class PlatformError(Exception):
    """Base platform exception."""

class PluginLoadError(PlatformError):
    """Raised when plugin load fails without affecting core app."""

class PermissionDenied(PlatformError):
    """Raised when tenant/user lacks required permission."""

class AutomationBlocked(PlatformError):
    """Raised when approval-first safety rules block automation."""

class ConnectorExecutionError(PlatformError):
    """Raised for connector execution failures."""
