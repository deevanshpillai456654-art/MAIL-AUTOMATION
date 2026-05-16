"""
Software bill of materials from the active environment (importlib.metadata).

Generates CycloneDX-like JSON without external build tools when possible.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sbom")

try:
    from importlib import metadata as importlib_metadata
except ImportError:  # pragma: no cover
    importlib_metadata = None  # type: ignore


class SBOMManager:
    def __init__(self):
        self._lock = threading.Lock()

    def collect_installed(self) -> List[Dict[str, Any]]:
        if importlib_metadata is None:
            return []
        out: List[Dict[str, Any]] = []
        for dist in importlib_metadata.distributions():
            try:
                out.append(
                    {
                        "name": dist.metadata["Name"],
                        "version": dist.version,
                    }
                )
            except Exception:  # noqa: BLE001
                continue
        return sorted(out, key=lambda x: x["name"].lower())

    def write_cyclonedx_json(self, path: Path) -> None:
        with self._lock:
            components = self.collect_installed()
            doc = {
                "bomFormat": "CycloneDX",
                "specVersion": "1.4",
                "version": 1,
                "metadata": {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "tools": [{"name": "ai-email-organizer", "version": "sbom_manager"}],
                },
                "components": [
                    {"type": "library", "name": c["name"], "version": c["version"]} for c in components
                ],
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
            logger.info("SBOM written %s (%s components)", path, len(components))


__all__ = ["SBOMManager"]
