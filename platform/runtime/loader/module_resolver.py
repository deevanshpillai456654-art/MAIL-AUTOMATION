"""
ModuleResolver — resolves plugin entrypoint paths from plugin IDs or module strings.

Handles the edge case where the plugins directory has hyphens in names
(like 'connectors-panel') by using importlib rather than normal package import.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Optional


class ModuleResolver:
    """
    Resolves module paths for plugins and connectors.

    Priority order:
      1. Absolute path given directly
      2. Relative to a registered search path
      3. Standard sys.path import
    """

    def __init__(self) -> None:
        self._search_paths: list[Path] = []

    def add_search_path(self, path: str | Path) -> None:
        p = Path(path)
        if p.exists() and p not in self._search_paths:
            self._search_paths.append(p)

    def resolve(self, entrypoint: str, base_dir: Optional[str | Path] = None) -> Optional[Path]:
        """
        Resolve an entrypoint string to an absolute Path.

        *entrypoint* can be:
          - ``"connector.py"``           → file relative to base_dir
          - ``"connector/main.py"``      → nested file relative to base_dir
          - ``"connectors.xero"``        → dotted module name → search paths
          - ``"/abs/path/connector.py"`` → absolute path (returned as-is)
        """
        # Absolute path
        p = Path(entrypoint)
        if p.is_absolute() and p.exists():
            return p

        # Relative to base_dir
        if base_dir:
            candidate = Path(base_dir) / entrypoint
            if candidate.exists():
                return candidate.resolve()

        # Search paths
        for search in self._search_paths:
            candidate = search / entrypoint
            if candidate.exists():
                return candidate.resolve()

        # Dotted module → convert to path
        if "." in entrypoint and not entrypoint.endswith(".py"):
            parts = entrypoint.split(".")
            for search in self._search_paths:
                candidate = search.joinpath(*parts[:-1]) / f"{parts[-1]}.py"
                if candidate.exists():
                    return candidate.resolve()

        return None

    def import_from_path(self, path: str | Path, module_name: Optional[str] = None) -> Any:
        """Import a module from an absolute file path."""
        p = Path(path)
        name = module_name or p.stem
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, p)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot create spec for {p}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module
