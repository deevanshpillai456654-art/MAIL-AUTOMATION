from __future__ import annotations
import importlib.util
import json
from pathlib import Path
from typing import List
from sdk.models import PluginManifest
from runtime.plugin_registry import PluginRegistry

class PluginLoader:
    def __init__(self, plugin_root: str | Path, registry: PluginRegistry) -> None:
        self.plugin_root = Path(plugin_root)
        self.registry = registry

    def discover_manifests(self) -> List[Path]:
        if not self.plugin_root.exists():
            return []
        return sorted(self.plugin_root.glob("*/plugin.json"))

    def load_manifests(self) -> List[PluginManifest]:
        manifests: List[PluginManifest] = []
        for path in self.discover_manifests():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                manifest = PluginManifest.from_dict(data)
                self.registry.register(manifest)
                manifests.append(manifest)
            except Exception as exc:
                # Keep core app alive; register a synthetic failed manifest if possible.
                failed_id = path.parent.name
                self.registry.fail(failed_id, str(exc)) if self.registry.get(failed_id) else None
        return manifests

    def import_module_file(self, module_path: str | Path):
        path = Path(module_path)
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot import plugin module from {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
