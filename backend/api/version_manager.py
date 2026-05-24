"""
API Version Manager
==================

API versioning:
- Version negotiation
- Deprecation warnings
- Version redirects
- API changelog
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("api.version")


class VersionStatus(Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    Sunset = "sunset"
    RETIRED = "retired"


@dataclass
class APIVersion:
    """API version"""
    version: str
    status: VersionStatus = VersionStatus.ACTIVE
    released_at: float = field(default_factory=time.time)
    sunset_at: Optional[float] = None
    features: List[str] = field(default_factory=list)
    breaking_changes: List[str] = field(default_factory=list)


class VersionManager:
    """
    API version manager.
    """

    def __init__(self):
        self._versions: Dict[str, APIVersion] = {}
        self._current = "v1"

        # Register versions
        self._register_versions()

        logger.info("VersionManager initialized")

    def _register_versions(self):
        """Register API versions"""
        versions = [
            APIVersion(
                version="v1",
                status=VersionStatus.ACTIVE,
                features=["classify", "rules", "sync", "accounts", "oauth"]
            ),
            APIVersion(
                version="v2",
                status=VersionStatus.DEPRECATED,
                released_at=time.time() - 86400 * 30,
                sunset_at=time.time() + 86400 * 30,
                features=["classify_v2", "rules", "sync", "accounts", "oauth", "streaming"]
            ),
        ]

        for v in versions:
            self._versions[v.version] = v

    def get_current_version(self) -> str:
        """Get current version"""
        return self._current

    def get_version_info(self, version: str) -> Optional[APIVersion]:
        """Get version info"""
        return self._versions.get(version)

    def is_supported(self, version: str) -> bool:
        """Check if version is supported"""
        v = self._versions.get(version)
        return v and v.status != VersionStatus.RETIRED

    def is_deprecated(self, version: str) -> bool:
        """Check if version is deprecated"""
        v = self._versions.get(version)
        return v and v.status == VersionStatus.DEPRECATED

    def should_upgrade(self, version: str) -> Tuple[bool, str]:
        """Check if client should upgrade"""
        if version == self._current:
            return False, ""

        current = self._versions.get(self._current)
        old = self._versions.get(version)

        if not old or not current:
            return True, "Version not found"

        if old.status == VersionStatus.DEPRECATED:
            return True, f"Version {version} is deprecated. Please upgrade to {self._current}"

        return False, ""

    def get_supported_versions(self) -> List[str]:
        """Get list of supported versions"""
        return [v for v in self._versions if self.is_supported(v)]

    def get_version_headers(self) -> Dict[str, str]:
        """Get version headers for responses"""
        return {
            "X-API-Version": self._current,
            "X-API-Versions-Available": ",".join(self.get_supported_versions()),
            "X-API-Current-Version": self._current
        }


# Global version manager
_version_manager: Optional[VersionManager] = None


def get_version_manager() -> VersionManager:
    """Get global version manager"""
    global _version_manager
    if _version_manager is None:
        _version_manager = VersionManager()
    return _version_manager


__all__ = ["VersionManager", "APIVersion", "VersionStatus", "get_version_manager"]
