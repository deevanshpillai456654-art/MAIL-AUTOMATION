"""Platform Security — permission engine, secret vault, scope validator, audit."""
from .secret_vault    import SecretVault
from .scope_validator import ScopeValidator
from ..runtime.permissions.permission_engine import PermissionEngine, PermissionDenied

__all__ = [
    "SecretVault",
    "ScopeValidator",
    "PermissionEngine",
    "PermissionDenied",
]
