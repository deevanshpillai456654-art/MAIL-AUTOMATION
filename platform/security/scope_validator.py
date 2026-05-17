"""
ScopeValidator — validates OAuth scopes and capability scopes for plugins.

Ensures that a token's granted scopes are sufficient for the requested
capability, and that a plugin only requests scopes it declared in its
manifest.
"""
from __future__ import annotations

import fnmatch
import logging
from typing import List, Optional

log = logging.getLogger(__name__)


class ScopeValidator:
    """
    Validates that a required scope is satisfied by a set of granted scopes.

    Scope format mirrors permission format: "domain:resource:action"
    Wildcard expansion is supported on both sides.

    Usage::

        sv = ScopeValidator()
        sv.validate_required("crm:contacts:write", granted=["crm:contacts:*"])  # True
        sv.validate_required("admin:*:*", granted=["crm:contacts:read"])         # False
    """

    def validate_required(
        self,
        required: str,
        *,
        granted: List[str],
    ) -> bool:
        return any(fnmatch.fnmatch(required, g) for g in granted)

    def validate_all(
        self,
        required: List[str],
        *,
        granted: List[str],
    ) -> bool:
        return all(self.validate_required(r, granted=granted) for r in required)

    def missing(
        self,
        required: List[str],
        *,
        granted: List[str],
    ) -> List[str]:
        return [r for r in required if not self.validate_required(r, granted=granted)]

    def validate_manifest_scopes(
        self,
        requested_scopes: List[str],
        manifest_scopes:  List[str],
    ) -> bool:
        """
        Ensure a token's requested_scopes are all declared in the plugin manifest.
        Prevents scope creep at token exchange time.
        """
        return self.validate_all(requested_scopes, granted=manifest_scopes)

    def filter_to_manifest(
        self,
        requested: List[str],
        manifest:  List[str],
    ) -> List[str]:
        """Return only the requested scopes that are declared in the manifest."""
        return [r for r in requested if self.validate_required(r, granted=manifest)]
